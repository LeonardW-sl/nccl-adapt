#!/usr/bin/env python3
import json
import math
import os
import socket
import time
from collections import defaultdict

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
        "min_ms": round(ordered[0], 3),
        "avg_ms": round(sum(ordered) / len(ordered), 3),
        "median_ms": round(percentile(ordered, 50), 3),
        "p95_ms": round(percentile(ordered, 95), 3),
        "max_ms": round(ordered[-1], 3),
    }


def phase_for_step(mode: str, step: int, candidate_count: int, recheck_after: int) -> tuple[str, int]:
    if mode != "weak-online":
        return "steady", step
    warmup_span = int(os.environ.get("NCCL_ADAPTIVE_WARMUP_SAMPLES_PER_CANDIDATE", "1")) * candidate_count
    recheck_span = int(os.environ.get("NCCL_ADAPTIVE_RECHECK_SAMPLES_PER_CANDIDATE", "1")) * candidate_count

    if step < warmup_span:
        return "warmup", step

    if recheck_after <= 0 or recheck_span <= 0:
        return "steady", step - warmup_span

    post_warmup_step = step - warmup_span
    cycle = recheck_after + recheck_span
    cycle_offset = post_warmup_step % cycle
    if cycle_offset < recheck_after:
        return "steady", cycle_offset
    return "recheck", cycle_offset - recheck_after


def main() -> None:
    rank = int(os.environ["RANK"])
    local_rank = int(os.environ["LOCAL_RANK"])
    world_size = int(os.environ["WORLD_SIZE"])

    torch.cuda.set_device(local_rank)
    device = torch.device(f"cuda:{local_rank}")

    dist.init_process_group(backend="nccl")

    message_mb = int(os.environ.get("ADAPTIVE_MESSAGE_MB", "8"))
    warmup_iters = int(os.environ.get("ADAPTIVE_WARMUP_ITERS", "4"))
    measure_iters = int(os.environ.get("ADAPTIVE_MEASURE_ITERS", "12"))
    candidate_count = int(os.environ.get("ADAPTIVE_CANDIDATE_COUNT", "4"))
    mode_name = os.environ.get("ADAPTIVE_EXPERIMENT_MODE_NAME", os.environ.get("NCCL_ADAPTIVE_MODE", "baseline"))
    recheck_after = int(os.environ.get("NCCL_ADAPTIVE_RECHECK_AFTER", "64")) if mode_name == "weak-online" else 0
    numel = message_mb * 1024 * 1024 // 4

    tensor = torch.ones(numel, device=device, dtype=torch.float32) * (rank + 1)
    latencies_ms: list[float] = []
    phase_latencies_ms: dict[str, list[float]] = defaultdict(list)

    for _ in range(warmup_iters):
        dist.all_reduce(tensor)
        torch.cuda.synchronize(device)

    for step in range(measure_iters):
        tensor.fill_(rank + 1)
        torch.cuda.synchronize(device)
        start = time.perf_counter()
        dist.all_reduce(tensor)
        torch.cuda.synchronize(device)
        latency_ms = (time.perf_counter() - start) * 1000.0
        phase_name, phase_step = phase_for_step(mode_name, step, candidate_count, recheck_after)
        latencies_ms.append(latency_ms)
        phase_latencies_ms[phase_name].append(latency_ms)

        if rank == 0:
            print(
                json.dumps(
                    {
                        "event": "iteration",
                        "step": step,
                        "phase": phase_name,
                        "phase_step": phase_step,
                        "message_mb": message_mb,
                        "latency_ms": round(latency_ms, 3),
                        "world_size": world_size,
                    }
                ),
                flush=True,
            )

    reduced = tensor[0].item()
    rank_payload = {
        "rank": rank,
        "reduced_value": round(reduced, 3),
        "latency_stats": build_stats(latencies_ms),
        "phase_stats": {name: build_stats(values) for name, values in sorted(phase_latencies_ms.items())},
    }

    gathered_payloads = [None for _ in range(world_size)] if rank == 0 else None
    dist.gather_object(rank_payload, gathered_payloads, dst=0)

    if rank == 0 and gathered_payloads is not None:
        per_rank = []
        overall_avg_ms: list[float] = []
        overall_phase_averages: dict[str, list[float]] = defaultdict(list)
        for payload in gathered_payloads:
            if payload is None:
                continue
            latency_stats = payload["latency_stats"]
            per_rank.append(
                {
                    "rank": payload["rank"],
                    "min_ms": latency_stats["min_ms"],
                    "avg_ms": latency_stats["avg_ms"],
                    "median_ms": latency_stats["median_ms"],
                    "p95_ms": latency_stats["p95_ms"],
                    "max_ms": latency_stats["max_ms"],
                    "reduced_value": payload["reduced_value"],
                    "phase_stats": payload["phase_stats"],
                }
            )
            overall_avg_ms.append(float(latency_stats["avg_ms"]))
            for phase_name, stats in payload["phase_stats"].items():
                overall_phase_averages[phase_name].append(float(stats["avg_ms"]))

        summary = {
            "event": "summary",
            "host": socket.gethostname(),
            "world_size": world_size,
            "mode": mode_name,
            "message_mb": message_mb,
            "warmup_iters": warmup_iters,
            "measure_iters": measure_iters,
            "candidate_count": candidate_count,
            "recheck_after": recheck_after,
            "per_rank": per_rank,
            "overall_avg_ms": build_stats(overall_avg_ms),
            "phase_avg_ms": {
                phase_name: build_stats(values) for phase_name, values in sorted(overall_phase_averages.items())
            },
        }
        print(json.dumps(summary), flush=True)

    dist.barrier()
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
