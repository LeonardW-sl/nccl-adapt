#!/usr/bin/env python3
import json
import os
import socket
import time

import torch
import torch.distributed as dist


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
    numel = message_mb * 1024 * 1024 // 4

    tensor = torch.ones(numel, device=device, dtype=torch.float32) * (rank + 1)
    latencies_ms = []

    for _ in range(warmup_iters):
        dist.all_reduce(tensor)
        torch.cuda.synchronize(device)

    for step in range(measure_iters):
        tensor.fill_(rank + 1)
        torch.cuda.synchronize(device)
        start = time.perf_counter()
        dist.all_reduce(tensor)
        torch.cuda.synchronize(device)
        latencies_ms.append((time.perf_counter() - start) * 1000.0)

        if rank == 0:
            print(
                json.dumps(
                    {
                        "event": "iteration",
                        "step": step,
                        "message_mb": message_mb,
                        "latency_ms": round(latencies_ms[-1], 3),
                        "world_size": world_size,
                    }
                ),
                flush=True,
            )

    reduced = tensor[0].item()
    stats = torch.tensor(
        [
            min(latencies_ms) if latencies_ms else 0.0,
            sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0,
            max(latencies_ms) if latencies_ms else 0.0,
            reduced,
        ],
        device=device,
    )

    gather_list = [torch.zeros_like(stats) for _ in range(world_size)] if rank == 0 else None
    dist.gather(stats, gather_list=gather_list, dst=0)

    if rank == 0 and gather_list is not None:
        summary = {
            "event": "summary",
            "host": socket.gethostname(),
            "world_size": world_size,
            "message_mb": message_mb,
            "warmup_iters": warmup_iters,
            "measure_iters": measure_iters,
            "per_rank": [
                {
                    "rank": idx,
                    "min_ms": round(values[0].item(), 3),
                    "avg_ms": round(values[1].item(), 3),
                    "max_ms": round(values[2].item(), 3),
                    "reduced_value": round(values[3].item(), 3),
                }
                for idx, values in enumerate(gather_list)
            ],
        }
        print(json.dumps(summary), flush=True)

    dist.barrier()
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
