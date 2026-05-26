#!/usr/bin/env python3
import json
import math
import os
import socket
import time
from collections import defaultdict

import torch
import torch.distributed as dist

METRIC_FIELDS = [
    "collective_device_elapsed_ms",
    "collective_algbw_gbps",
    "collective_busbw_gbps",
    "microstep_time_ms",
    "microstep_device_elapsed_ms",
    "boundary_tail_ms",
    "boundary_anchor_window_ms",
]


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


def env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    return int(raw_value)


def env_float(name: str, default: float | None = None) -> float | None:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    return float(raw_value)


def parse_gemm_shape(default_shape: int = 2048) -> tuple[int, int, int]:
    raw_shape = os.environ.get("ADAPTIVE_MICROSTEP_GEMM_SHAPE", "")
    if raw_shape:
        parts = [part for part in raw_shape.lower().replace("x", ",").split(",") if part]
        if len(parts) == 1:
            side = int(parts[0])
            return side, side, side
        if len(parts) == 3:
            return int(parts[0]), int(parts[1]), int(parts[2])
        raise ValueError("ADAPTIVE_MICROSTEP_GEMM_SHAPE must be '<side>' or '<m>x<n>x<k>'")
    m = env_int("ADAPTIVE_MICROSTEP_GEMM_M", default_shape)
    n = env_int("ADAPTIVE_MICROSTEP_GEMM_N", default_shape)
    k = env_int("ADAPTIVE_MICROSTEP_GEMM_K", default_shape)
    return m, n, k


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
    raise ValueError(f"unsupported ADAPTIVE_MICROSTEP_GEMM_DTYPE={requested_dtype!r}")


class ComputeSlab:
    def __init__(
        self,
        *,
        family: str,
        device: torch.device,
        pointwise_numel: int,
        gemm_shape: tuple[int, int, int],
        requested_gemm_dtype: str,
        unit_gemm_latency_ms: float | None,
        rank: int,
    ) -> None:
        self.family = family
        self.device = device
        self.pointwise_numel = pointwise_numel
        self.requested_gemm_dtype = requested_gemm_dtype
        self.unit_gemm_latency_ms = unit_gemm_latency_ms
        self.gemm_shape = gemm_shape
        self.resolved_gemm_dtype: str | None = None
        self.pointwise_buffer: torch.Tensor | None = None
        self.gemm_lhs: torch.Tensor | None = None
        self.gemm_rhs: torch.Tensor | None = None
        self.gemm_out: torch.Tensor | None = None

        if family == "pointwise":
            self.pointwise_buffer = torch.ones(pointwise_numel, device=device, dtype=torch.float32)
            return
        if family != "gemm":
            raise ValueError(f"unsupported ADAPTIVE_MICROSTEP_COMPUTE_FAMILY={family!r}")

        m, n, k = gemm_shape
        gemm_dtype, resolved_name = resolve_gemm_dtype(requested_gemm_dtype)
        self.resolved_gemm_dtype = resolved_name
        scale = 1.0 + (rank * 0.001)
        self.gemm_lhs = torch.full((m, k), scale, device=device, dtype=gemm_dtype)
        self.gemm_rhs = torch.full((k, n), 0.5, device=device, dtype=gemm_dtype)
        self.gemm_out = torch.empty((m, n), device=device, dtype=gemm_dtype)

    def run(self, repeats: int) -> None:
        if repeats <= 0:
            return
        if self.family == "pointwise":
            assert self.pointwise_buffer is not None
            for _ in range(repeats):
                self.pointwise_buffer.mul_(1.000001)
                self.pointwise_buffer.add_(0.000001)
            return

        assert self.gemm_lhs is not None
        assert self.gemm_rhs is not None
        assert self.gemm_out is not None
        for _ in range(repeats):
            torch.mm(self.gemm_lhs, self.gemm_rhs, out=self.gemm_out)

    def describe(self) -> dict[str, int | float | str | list[int] | None]:
        m, n, k = self.gemm_shape
        return {
            "compute_family": self.family,
            "pointwise_numel": self.pointwise_numel if self.family == "pointwise" else None,
            "gemm_shape": [m, n, k] if self.family == "gemm" else None,
            "requested_gemm_dtype": self.requested_gemm_dtype if self.family == "gemm" else None,
            "resolved_gemm_dtype": self.resolved_gemm_dtype if self.family == "gemm" else None,
            "unit_gemm_latency_ms": self.unit_gemm_latency_ms if self.family == "gemm" else None,
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


def allreduce_busbw_factor(world_size: int) -> float:
    if world_size <= 0:
        return 0.0
    return 2.0 * (world_size - 1) / world_size


def gbps_from_bytes_and_ms(num_bytes: int, elapsed_ms: float) -> float:
    if elapsed_ms <= 0.0:
        return 0.0
    return (float(num_bytes) / elapsed_ms) / 1_000_000.0


def summarize_metrics(metric_values: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    return {
        name: build_stats(values)
        for name, values in sorted(metric_values.items())
        if values
    }


def run_smoke_iteration(
    tensor: torch.Tensor,
    device: torch.device,
    message_bytes: int,
    world_size: int,
) -> dict[str, float]:
    start = time.perf_counter()
    dist.all_reduce(tensor)
    torch.cuda.synchronize(device)
    latency_ms = (time.perf_counter() - start) * 1000.0
    algbw_gbps = gbps_from_bytes_and_ms(message_bytes, latency_ms)
    return {
        "latency_ms": latency_ms,
        "microstep_time_ms": latency_ms,
        "collective_algbw_gbps": algbw_gbps,
        "collective_busbw_gbps": algbw_gbps * allreduce_busbw_factor(world_size),
    }


def run_tail_anchored_microstep(
    tensor: torch.Tensor,
    compute_slab: ComputeSlab,
    control_stream: torch.cuda.Stream,
    compute_stream: torch.cuda.Stream,
    comm_stream: torch.cuda.Stream,
    preamble_repeats: int,
    overlap_repeats: int,
    epilogue_repeats: int,
    message_bytes: int,
    world_size: int,
) -> dict[str, float | str]:
    microstep_start_event = torch.cuda.Event(enable_timing=True)
    blocking_preamble_done_event = torch.cuda.Event(enable_timing=True)
    collective_start_event = torch.cuda.Event(enable_timing=True)
    collective_done_event = torch.cuda.Event(enable_timing=True)
    overlap_slab_done_event = torch.cuda.Event(enable_timing=True)
    epilogue_done_event = torch.cuda.Event(enable_timing=True)
    microstep_end_event = torch.cuda.Event(enable_timing=True)

    with torch.cuda.stream(control_stream):
        microstep_start_event.record(control_stream)
    host_start = time.perf_counter()

    with torch.cuda.stream(compute_stream):
        compute_stream.wait_event(microstep_start_event)
        compute_slab.run(preamble_repeats)
        blocking_preamble_done_event.record(compute_stream)
        compute_slab.run(overlap_repeats)
        overlap_slab_done_event.record(compute_stream)

    collective_completion_mode = "work.block_current_stream"
    with torch.cuda.stream(comm_stream):
        comm_stream.wait_event(blocking_preamble_done_event)
        collective_start_event.record(comm_stream)
        work = dist.all_reduce(tensor, async_op=True)
        if hasattr(work, "block_current_stream"):
            work.block_current_stream()
        else:
            collective_completion_mode = "work.wait"
            work.wait()
        collective_done_event.record(comm_stream)

    with torch.cuda.stream(compute_stream):
        compute_stream.wait_event(overlap_slab_done_event)
        compute_stream.wait_event(collective_done_event)
        compute_slab.run(epilogue_repeats)
        epilogue_done_event.record(compute_stream)

    with torch.cuda.stream(control_stream):
        control_stream.wait_event(epilogue_done_event)
        microstep_end_event.record(control_stream)

    microstep_end_event.synchronize()
    microstep_time_ms = (time.perf_counter() - host_start) * 1000.0
    collective_device_elapsed_ms = collective_start_event.elapsed_time(collective_done_event)
    microstep_device_elapsed_ms = microstep_start_event.elapsed_time(microstep_end_event)
    boundary_tail_ms = collective_done_event.elapsed_time(microstep_end_event)
    boundary_anchor_window_ms = collective_start_event.elapsed_time(microstep_end_event)
    algbw_gbps = gbps_from_bytes_and_ms(message_bytes, collective_device_elapsed_ms)

    return {
        "latency_ms": microstep_time_ms,
        "collective_device_elapsed_ms": collective_device_elapsed_ms,
        "collective_algbw_gbps": algbw_gbps,
        "collective_busbw_gbps": algbw_gbps * allreduce_busbw_factor(world_size),
        "microstep_time_ms": microstep_time_ms,
        "microstep_device_elapsed_ms": microstep_device_elapsed_ms,
        "boundary_tail_ms": boundary_tail_ms,
        "boundary_anchor_window_ms": boundary_anchor_window_ms,
        "collective_completion_mode": collective_completion_mode,
    }


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
    harness_name = os.environ.get("ADAPTIVE_HARNESS", "smoke")
    preamble_repeats = env_int("ADAPTIVE_MICROSTEP_PREAMBLE_REPEATS", 2)
    overlap_repeats = env_int("ADAPTIVE_MICROSTEP_OVERLAP_REPEATS", 4)
    epilogue_repeats = env_int("ADAPTIVE_MICROSTEP_EPILOGUE_REPEATS", 2)
    compute_numel = env_int("ADAPTIVE_MICROSTEP_COMPUTE_NUMEL", 262144)
    compute_family = os.environ.get("ADAPTIVE_MICROSTEP_COMPUTE_FAMILY", "pointwise").strip().lower()
    requested_gemm_dtype = os.environ.get("ADAPTIVE_MICROSTEP_GEMM_DTYPE", "auto")
    gemm_shape = parse_gemm_shape()
    unit_gemm_latency_ms = env_float("ADAPTIVE_MICROSTEP_GEMM_UNIT_MS")
    mode_name = os.environ.get("ADAPTIVE_EXPERIMENT_MODE_NAME", os.environ.get("NCCL_ADAPTIVE_MODE", "baseline"))
    recheck_after = int(os.environ.get("NCCL_ADAPTIVE_RECHECK_AFTER", "64")) if mode_name == "weak-online" else 0
    numel = message_mb * 1024 * 1024 // 4
    message_bytes = numel * 4

    tensor = torch.ones(numel, device=device, dtype=torch.float32) * (rank + 1)
    compute_slab = ComputeSlab(
        family=compute_family,
        device=device,
        pointwise_numel=compute_numel,
        gemm_shape=gemm_shape,
        requested_gemm_dtype=requested_gemm_dtype,
        unit_gemm_latency_ms=unit_gemm_latency_ms,
        rank=rank,
    )
    control_stream = torch.cuda.Stream(device=device)
    compute_stream = torch.cuda.Stream(device=device)
    comm_stream = torch.cuda.Stream(device=device)
    latencies_ms: list[float] = []
    phase_latencies_ms: dict[str, list[float]] = defaultdict(list)
    metric_values: dict[str, list[float]] = defaultdict(list)
    collective_completion_modes: set[str] = set()

    for _ in range(warmup_iters):
        tensor.fill_(rank + 1)
        torch.cuda.synchronize(device)
        if harness_name == "tail-anchored-microstep":
            metrics = run_tail_anchored_microstep(
                tensor=tensor,
                compute_slab=compute_slab,
                control_stream=control_stream,
                compute_stream=compute_stream,
                comm_stream=comm_stream,
                preamble_repeats=preamble_repeats,
                overlap_repeats=overlap_repeats,
                epilogue_repeats=epilogue_repeats,
                message_bytes=message_bytes,
                world_size=world_size,
            )
            collective_completion_modes.add(str(metrics.get("collective_completion_mode", "unknown")))
        else:
            run_smoke_iteration(tensor, device, message_bytes, world_size)

    for step in range(measure_iters):
        tensor.fill_(rank + 1)
        torch.cuda.synchronize(device)
        if harness_name == "tail-anchored-microstep":
            metrics = run_tail_anchored_microstep(
                tensor=tensor,
                compute_slab=compute_slab,
                control_stream=control_stream,
                compute_stream=compute_stream,
                comm_stream=comm_stream,
                preamble_repeats=preamble_repeats,
                overlap_repeats=overlap_repeats,
                epilogue_repeats=epilogue_repeats,
                message_bytes=message_bytes,
                world_size=world_size,
            )
            collective_completion_modes.add(str(metrics.get("collective_completion_mode", "unknown")))
        else:
            metrics = run_smoke_iteration(tensor, device, message_bytes, world_size)
        latency_ms = float(metrics["latency_ms"])
        phase_name, phase_step = phase_for_step(mode_name, step, candidate_count, recheck_after)
        latencies_ms.append(latency_ms)
        phase_latencies_ms[phase_name].append(latency_ms)
        for name in METRIC_FIELDS:
            value = metrics.get(name)
            if isinstance(value, (int, float)):
                metric_values[name].append(float(value))

        if rank == 0:
            event_payload: dict[str, float | int | str] = {
                "event": "iteration",
                "step": step,
                "phase": phase_name,
                "phase_step": phase_step,
                "message_mb": message_mb,
                "latency_ms": round(latency_ms, 3),
                "world_size": world_size,
                "harness": harness_name,
            }
            for name in METRIC_FIELDS:
                value = metrics.get(name)
                if isinstance(value, (int, float)):
                    event_payload[name] = round(float(value), 3)
            print(
                json.dumps(event_payload),
                flush=True,
            )

    reduced = tensor[0].item()
    rank_payload = {
        "rank": rank,
        "reduced_value": round(reduced, 3),
        "latency_stats": build_stats(latencies_ms),
        "phase_stats": {name: build_stats(values) for name, values in sorted(phase_latencies_ms.items())},
        "metric_stats": summarize_metrics(metric_values),
    }

    gathered_payloads = [None for _ in range(world_size)] if rank == 0 else None
    dist.gather_object(rank_payload, gathered_payloads, dst=0)

    if rank == 0 and gathered_payloads is not None:
        per_rank = []
        overall_avg_ms: list[float] = []
        overall_phase_averages: dict[str, list[float]] = defaultdict(list)
        overall_metric_averages: dict[str, list[float]] = defaultdict(list)
        for payload in gathered_payloads:
            if payload is None:
                continue
            latency_stats = payload["latency_stats"]
            metric_stats = payload.get("metric_stats", {})
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
                    "metric_stats": metric_stats,
                }
            )
            overall_avg_ms.append(float(latency_stats["avg_ms"]))
            for phase_name, stats in payload["phase_stats"].items():
                overall_phase_averages[phase_name].append(float(stats["avg_ms"]))
            for metric_name, stats in metric_stats.items():
                if isinstance(stats, dict):
                    overall_metric_averages[metric_name].append(float(stats.get("avg_ms", 0.0)))

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
            "harness": {
                "name": harness_name,
                "stream_geometry": ["control_stream", "compute_stream", "comm_stream"],
                "boundary_events": [
                    "microstep_start_event",
                    "blocking_preamble_done_event",
                    "collective_start_event",
                    "collective_done_event",
                    "overlap_slab_done_event",
                    "epilogue_done_event",
                    "microstep_end_event",
                ],
                "preamble_repeats": preamble_repeats,
                "overlap_repeats": overlap_repeats,
                "epilogue_repeats": epilogue_repeats,
                "compute_numel": compute_numel,
                "compute": compute_slab.describe(),
                "collective_completion_modes": sorted(collective_completion_modes),
            },
            "per_rank": per_rank,
            "overall_avg_ms": build_stats(overall_avg_ms),
            "phase_avg_ms": {
                phase_name: build_stats(values) for phase_name, values in sorted(overall_phase_averages.items())
            },
            "overall_metric_avg_ms": {
                metric_name: build_stats(values) for metric_name, values in sorted(overall_metric_averages.items())
            },
        }
        print(json.dumps(summary), flush=True)

    dist.barrier()
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
