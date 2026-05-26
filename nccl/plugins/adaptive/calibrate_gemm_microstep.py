#!/usr/bin/env python3
import argparse
import json
import math
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
import torch.distributed as dist


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = math.ceil((pct / 100.0) * len(ordered)) - 1
    rank = min(max(rank, 0), len(ordered) - 1)
    return ordered[rank]


def build_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "count": 0,
            "min_ms": 0.0,
            "avg_ms": 0.0,
            "median_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
        }
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min_ms": round(ordered[0], 6),
        "avg_ms": round(sum(ordered) / len(ordered), 6),
        "median_ms": round(percentile(ordered, 50), 6),
        "p95_ms": round(percentile(ordered, 95), 6),
        "max_ms": round(ordered[-1], 6),
    }


def resolve_gemm_dtype(requested_dtype: str) -> tuple[torch.dtype, str]:
    normalized = requested_dtype.strip().lower()
    if normalized in {"", "auto"}:
        if torch.cuda.is_bf16_supported():
            return torch.bfloat16, "bfloat16"
        return torch.float16, "float16"
    if normalized in {"bfloat16", "bf16"}:
        if not torch.cuda.is_bf16_supported():
            raise RuntimeError("requested bfloat16 GEMM dtype is not supported on this CUDA device")
        return torch.bfloat16, "bfloat16"
    if normalized in {"float16", "fp16", "half"}:
        return torch.float16, "float16"
    if normalized in {"float32", "fp32"}:
        return torch.float32, "float32"
    raise ValueError(f"unsupported GEMM dtype: {requested_dtype!r}")


def parse_ladder(raw_ladder: str) -> list[int]:
    values = [int(item.strip()) for item in raw_ladder.split(",") if item.strip()]
    if not values:
        raise ValueError("shape ladder must not be empty")
    return values


def measure_shape(
    *,
    shape: int,
    dtype: torch.dtype,
    device: torch.device,
    rank: int,
    warmup_iters: int,
    measure_iters: int,
) -> dict[str, Any]:
    try:
        lhs = torch.full((shape, shape), 1.0 + rank * 0.001, device=device, dtype=dtype)
        rhs = torch.full((shape, shape), 0.5, device=device, dtype=dtype)
        out = torch.empty((shape, shape), device=device, dtype=dtype)
        torch.cuda.synchronize(device)
        for _ in range(warmup_iters):
            torch.mm(lhs, rhs, out=out)
        torch.cuda.synchronize(device)

        start_event = torch.cuda.Event(enable_timing=True)
        end_event = torch.cuda.Event(enable_timing=True)
        start_event.record()
        for _ in range(measure_iters):
            torch.mm(lhs, rhs, out=out)
        end_event.record()
        end_event.synchronize()
        elapsed_ms = start_event.elapsed_time(end_event)
        return {
            "rank": rank,
            "shape": shape,
            "available": True,
            "avg_ms": round(elapsed_ms / measure_iters, 6),
            "elapsed_ms": round(elapsed_ms, 6),
            "measure_iters": measure_iters,
            "error": None,
        }
    except torch.cuda.OutOfMemoryError as exc:
        torch.cuda.empty_cache()
        return {
            "rank": rank,
            "shape": shape,
            "available": False,
            "avg_ms": None,
            "elapsed_ms": None,
            "measure_iters": measure_iters,
            "error": f"cuda-oom: {exc}",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure GEMM unit latency for tail-anchored microstep calibration.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--ladder", default="2048,3072,4096,5120,6144,7168,8192")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--warmup-iters", type=int, default=5)
    parser.add_argument("--measure-iters", type=int, default=20)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required for GEMM microstep calibration")

    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    torch.cuda.set_device(local_rank)
    device = torch.device(f"cuda:{local_rank}")
    if world_size > 1:
        dist.init_process_group(backend="nccl")

    ladder = parse_ladder(args.ladder)
    dtype, resolved_dtype = resolve_gemm_dtype(args.dtype)
    local_results = [
        measure_shape(
            shape=shape,
            dtype=dtype,
            device=device,
            rank=rank,
            warmup_iters=args.warmup_iters,
            measure_iters=args.measure_iters,
        )
        for shape in ladder
    ]

    gathered: list[list[dict[str, Any]]] | None = [None for _ in range(world_size)] if rank == 0 else None
    if world_size > 1:
        dist.gather_object(local_results, gathered, dst=0)
    else:
        gathered = [local_results]

    if rank == 0 and gathered is not None:
        by_shape: dict[int, list[dict[str, Any]]] = {shape: [] for shape in ladder}
        for rank_results in gathered:
            if rank_results is None:
                continue
            for item in rank_results:
                by_shape[int(item["shape"])].append(item)

        shape_results = []
        for shape in ladder:
            rank_entries = by_shape[shape]
            available_entries = [item for item in rank_entries if item.get("available")]
            avg_values = [float(item["avg_ms"]) for item in available_entries if item.get("avg_ms") is not None]
            shape_results.append(
                {
                    "shape": shape,
                    "available": len(available_entries) == world_size,
                    "rank_results": rank_entries,
                    "rank_avg_ms": build_stats(avg_values),
                    "rank_max_avg_ms": round(max(avg_values), 6) if avg_values else None,
                    "error_count": len(rank_entries) - len(available_entries),
                }
            )

        payload = {
            "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "host": socket.gethostname(),
            "world_size": world_size,
            "requested_dtype": args.dtype,
            "resolved_dtype": resolved_dtype,
            "warmup_iters": args.warmup_iters,
            "measure_iters": args.measure_iters,
            "shape_ladder": ladder,
            "selection_latency_field": "rank_max_avg_ms",
            "shapes": shape_results,
        }
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(json.dumps({"event": "gemm-calibration", "output": str(output_path), "resolved_dtype": resolved_dtype}))

    if world_size > 1:
        dist.barrier()
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
