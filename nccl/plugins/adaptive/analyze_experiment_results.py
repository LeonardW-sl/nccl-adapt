#!/usr/bin/env python3
import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


EVENT_PREFIX = "ADAPTIVE/"
JSON_EVENTS = {"iteration", "summary"}
COORDINATOR_RE = re.compile(
    r"ADAPTIVE/coordinator (?P<kind>publish|activate) "
    r"comm=(?P<comm>\d+) key=(?P<key>\S+) "
    r"(?:(?:observed_epoch=(?P<observed_epoch>\d+) window=(?P<window>\d+) next_epoch=(?P<next_epoch>\d+) )|)"
    r"(?:epoch=(?P<epoch>\d+) call=(?P<call>\d+) )?"
    r"candidate=(?P<candidate>\S+)(?: effective_call=(?P<effective_call>\d+))?"
    r"(?: recheck_after=(?P<recheck_after>\d+))?"
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


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


def parse_log(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
    iterations: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    trajectory: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("{") and '"event"' in line:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = None
                if event and event.get("event") in JSON_EVENTS:
                    if event["event"] == "iteration":
                        iterations.append(event)
                    elif event["event"] == "summary":
                        summary = event
                    continue
            if EVENT_PREFIX not in line:
                continue
            match = COORDINATOR_RE.search(line)
            if not match:
                continue
            groups = match.groupdict()
            item = {
                "event": groups["kind"],
                "comm_id": int(groups["comm"]),
                "key": groups["key"],
                "candidate": groups["candidate"],
            }
            for name in (
                "observed_epoch",
                "window",
                "next_epoch",
                "epoch",
                "call",
                "effective_call",
                "recheck_after",
            ):
                if groups.get(name) is not None:
                    item[name] = int(groups[name])
            trajectory.append(item)
    return iterations, summary, trajectory


def summarize_run(args: argparse.Namespace) -> None:
    log_path = Path(args.log)
    metadata_path = Path(args.metadata)
    output_path = Path(args.output)
    trajectory_path = Path(args.trajectory_output)

    metadata = load_json(metadata_path)
    iterations, summary, trajectory = parse_log(log_path)
    if summary is None:
      raise SystemExit(f"missing summary event in {log_path}")

    phase_iterations: dict[str, list[float]] = defaultdict(list)
    for item in iterations:
        phase_iterations[item.get("phase", "steady")].append(float(item["latency_ms"]))

    run_summary = {
        "experiment_type": metadata["experiment_type"],
        "mode": metadata["mode"],
        "replicate_id": metadata["replicate_id"],
        "run_order": metadata["run_order"],
        "message_mb": metadata.get("message_mb"),
        "size_bucket": metadata.get("size_bucket"),
        "phase_iteration_stats": {phase: build_stats(values) for phase, values in sorted(phase_iterations.items())},
        "iteration_count": len(iterations),
        "summary": summary,
        "trajectory_event_count": len(trajectory),
    }
    dump_json(output_path, run_summary)
    dump_json(
        trajectory_path,
        {
            "experiment_type": metadata["experiment_type"],
            "mode": metadata["mode"],
            "replicate_id": metadata["replicate_id"],
            "run_order": metadata["run_order"],
            "message_mb": metadata.get("message_mb"),
            "size_bucket": metadata.get("size_bucket"),
            "events": trajectory,
        },
    )


def aggregate_mode_comparison(args: argparse.Namespace) -> None:
    result_dir = Path(args.result_dir)
    summaries = sorted(result_dir.glob("replicate-*/run-*/summary.json"))
    mode_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for summary_path in summaries:
        payload = load_json(summary_path)
        mode_runs[payload["mode"]].append(payload)

    aggregate: dict[str, Any] = {
        "experiment_type": args.experiment_type,
        "modes": {},
    }
    for mode, runs in sorted(mode_runs.items()):
        avg_values: list[float] = []
        max_values: list[float] = []
        phase_values: dict[str, list[float]] = defaultdict(list)
        for run in runs:
            per_rank = run["summary"].get("per_rank", [])
            avg_values.extend(float(item["avg_ms"]) for item in per_rank)
            max_values.extend(float(item["max_ms"]) for item in per_rank)
            for phase, stats in run.get("phase_iteration_stats", {}).items():
                phase_values[phase].append(float(stats["avg_ms"]))
        aggregate["modes"][mode] = {
            "replicate_count": len(runs),
            "per_rank_avg_ms": build_stats(avg_values),
            "per_rank_max_ms": build_stats(max_values),
            "phase_avg_ms": {phase: build_stats(values) for phase, values in sorted(phase_values.items())},
            "runs": [
                {
                    "replicate_id": run["replicate_id"],
                    "run_order": run["run_order"],
                    "message_mb": run.get("message_mb"),
                    "summary_path": str(
                        Path(f"replicate-{run['replicate_id']:02d}")
                        / f"run-{run['run_order']:02d}-{run['mode']}"
                        / "summary.json"
                    ),
                }
                for run in sorted(runs, key=lambda item: (item["replicate_id"], item["run_order"]))
            ],
        }
    dump_json(Path(args.output), aggregate)


def aggregate_size_sweep(args: argparse.Namespace) -> None:
    result_dir = Path(args.result_dir)
    summaries = sorted(result_dir.glob("replicate-*/run-*/summary.json"))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trajectories: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for summary_path in summaries:
        run_dir = summary_path.parent
        summary = load_json(summary_path)
        trajectory_path = run_dir / "trajectory.json"
        key = f"{summary['message_mb']}MB"
        grouped[key].append(summary)
        if trajectory_path.exists():
            trajectories[key].append(load_json(trajectory_path))

    payload: dict[str, Any] = {
        "experiment_type": args.experiment_type,
        "sizes": {},
    }
    for size_key, runs in sorted(grouped.items(), key=lambda item: int(item[0].removesuffix("MB"))):
        avg_values: list[float] = []
        phases: dict[str, list[float]] = defaultdict(list)
        trajectory_rows: list[dict[str, Any]] = []
        for run in runs:
            per_rank = run["summary"].get("per_rank", [])
            avg_values.extend(float(item["avg_ms"]) for item in per_rank)
            for phase, stats in run.get("phase_iteration_stats", {}).items():
                phases[phase].append(float(stats["avg_ms"]))
        for trajectory in trajectories.get(size_key, []):
            for event in trajectory.get("events", []):
                if event.get("event") not in {"publish", "activate"}:
                    continue
                row = {
                    "replicate_id": trajectory["replicate_id"],
                    "run_order": trajectory["run_order"],
                    "event": event["event"],
                    "candidate": event["candidate"],
                }
                for name in ("next_epoch", "epoch", "window", "effective_call", "call", "recheck_after"):
                    if name in event:
                        row[name] = event[name]
                trajectory_rows.append(row)
        payload["sizes"][size_key] = {
            "replicate_count": len(runs),
            "per_rank_avg_ms": build_stats(avg_values),
            "phase_avg_ms": {phase: build_stats(values) for phase, values in sorted(phases.items())},
            "candidate_trajectory": sorted(
                trajectory_rows,
                key=lambda item: (item["replicate_id"], item["run_order"], item.get("next_epoch", 0), item.get("epoch", 0)),
            ),
        }
    dump_json(Path(args.output), payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize adaptive NCCL experiment outputs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize_parser = subparsers.add_parser("summarize-run")
    summarize_parser.add_argument("--log", required=True)
    summarize_parser.add_argument("--metadata", required=True)
    summarize_parser.add_argument("--output", required=True)
    summarize_parser.add_argument("--trajectory-output", required=True)
    summarize_parser.set_defaults(func=summarize_run)

    comparison_parser = subparsers.add_parser("aggregate-mode-comparison")
    comparison_parser.add_argument("--result-dir", required=True)
    comparison_parser.add_argument("--experiment-type", required=True)
    comparison_parser.add_argument("--output", required=True)
    comparison_parser.set_defaults(func=aggregate_mode_comparison)

    sweep_parser = subparsers.add_parser("aggregate-size-sweep")
    sweep_parser.add_argument("--result-dir", required=True)
    sweep_parser.add_argument("--experiment-type", required=True)
    sweep_parser.add_argument("--output", required=True)
    sweep_parser.set_defaults(func=aggregate_size_sweep)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
