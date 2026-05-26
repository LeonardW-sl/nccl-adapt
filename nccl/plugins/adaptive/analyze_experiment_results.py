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
MEASUREMENT_METRIC_FIELDS = [
    "collective_device_elapsed_ms",
    "collective_algbw_gbps",
    "collective_busbw_gbps",
    "microstep_time_ms",
    "microstep_device_elapsed_ms",
    "boundary_tail_ms",
    "boundary_anchor_window_ms",
]
PLUGIN_LOAD_RE = re.compile(
    r"Successfully loaded external (?P<kind>profiler|tuner) plugin (?P<path>/\S+?\.so)(?=\s|$)"
)
DIAGNOSTIC_EVENT_RE = re.compile(
    r"ADAPTIVE/(?P<category>coordinator|completion) (?P<kind>[a-z-]+) (?P<body>.*?)(?=(?:ADAPTIVE/)|$)"
)
TUNER_FALLBACK_RE = re.compile(
    r"ADAPTIVE/tuner fallback=(?P<kind>\w+)(?: (?P<body>.*?))?(?=(?:ADAPTIVE/)|$)"
)
KEY_VALUE_RE = re.compile(r"(?P<key>[a-z_]+)=(?P<value>\S+)")
INT_FIELDS = {
    "attached",
    "call",
    "comm",
    "effective_call",
    "epoch",
    "host_fallback",
    "missing_rank",
    "nchannels",
    "next_epoch",
    "observed_epoch",
    "partial",
    "phase",
    "queue_depth",
    "queue_remaining",
    "rank",
    "recheck_after",
    "representative",
    "sampled",
    "seq",
    "started",
    "stopped",
    "window",
}
BOOL_FIELDS = {"attached", "host_fallback", "partial", "representative", "sampled"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def dump_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)


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


def build_step_stats(values: list[int]) -> dict[str, float]:
    if not values:
        return {
            "count": 0,
            "min_step": 0,
            "avg_step": 0.0,
            "median_step": 0.0,
            "p95_step": 0.0,
            "max_step": 0,
        }
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min_step": ordered[0],
        "avg_step": round(sum(ordered) / len(ordered), 3),
        "median_step": round(percentile([float(item) for item in ordered], 50), 3),
        "p95_step": round(percentile([float(item) for item in ordered], 95), 3),
        "max_step": ordered[-1],
    }


def build_phase_step_ranges(iterations: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped_steps: dict[str, list[int]] = defaultdict(list)
    for item in iterations:
        grouped_steps[item.get("phase", "steady")].append(int(item["step"]))
    ranges: dict[str, dict[str, int]] = {}
    for phase, steps in sorted(grouped_steps.items()):
        ranges[phase] = {
            "count": len(steps),
            "first_step": min(steps),
            "last_step": max(steps),
        }
    return ranges


def build_step_range(steps: list[int]) -> dict[str, int]:
    if not steps:
        return {
            "count": 0,
            "first_step": 0,
            "last_step": 0,
        }
    return {
        "count": len(steps),
        "first_step": min(steps),
        "last_step": max(steps),
    }


def resolve_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return root / path


def iter_json_objects(line: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    index = 0
    while True:
        brace = line.find("{", index)
        if brace < 0:
            break
        try:
            payload, end = decoder.raw_decode(line, brace)
        except json.JSONDecodeError:
            index = brace + 1
            continue
        if isinstance(payload, dict):
            objects.append(payload)
        index = end
    return objects


def parse_key_values(body: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for match in KEY_VALUE_RE.finditer(body):
        key = match.group("key")
        value = match.group("value")
        if key in INT_FIELDS:
            try:
                parsed: Any = int(value)
            except ValueError:
                parsed = value
            if key in BOOL_FIELDS and isinstance(parsed, int):
                payload[key] = bool(parsed)
            else:
                payload[key] = parsed
            continue
        if value in {"true", "false"}:
            payload[key] = value == "true"
            continue
        payload[key] = value
    return payload


def sort_event_value(event: dict[str, Any], *keys: str) -> int:
    missing = 1 << 60
    for key in keys:
        value = event.get(key)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
    return missing


def first_event(events: list[dict[str, Any]], *keys: str) -> dict[str, Any] | None:
    if not events:
        return None
    return min(events, key=lambda item: tuple(sort_event_value(item, key) for key in keys))


def derive_diagnostic_phases(
    mode: str,
    iterations: list[dict[str, Any]],
    coordinator_events: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, int]], dict[str, Any]]:
    if not iterations:
        return {}, {}, {}

    all_steps = [int(item["step"]) for item in iterations]
    all_latencies = [float(item["latency_ms"]) for item in iterations]
    phase_stats: dict[str, dict[str, float]] = {
        "overall": build_stats(all_latencies),
    }
    phase_ranges: dict[str, dict[str, int]] = {
        "overall": build_step_range(all_steps),
    }
    boundary: dict[str, Any] = {}

    if mode == "profiler-only":
        phase_stats["callback-only"] = build_stats(all_latencies)
        phase_ranges["callback-only"] = build_step_range(all_steps)
        boundary["control_mode"] = "callback-only"
        return phase_stats, phase_ranges, boundary

    if mode != "final-steady":
        return phase_stats, phase_ranges, boundary

    publish_events = [item for item in coordinator_events if item.get("event") == "publish"]
    activate_events = [item for item in coordinator_events if item.get("event") == "activate"]
    first_publish = first_event(publish_events, "effective_call", "call", "phase")
    first_activate = first_event(activate_events, "call", "effective_call", "phase")

    first_publish_call = None
    if first_publish is not None:
        first_publish_call = sort_event_value(first_publish, "effective_call", "call", "phase")
        if first_publish_call < (1 << 60):
            boundary["first_publish_effective_call"] = first_publish_call

    first_activate_call = None
    if first_activate is not None:
        first_activate_call = sort_event_value(first_activate, "call", "effective_call", "phase")
        if first_activate_call < (1 << 60):
            boundary["first_activate_call"] = first_activate_call

    if first_publish_call is not None:
        sampled_window = [item for item in iterations if int(item["step"]) < first_publish_call]
        if sampled_window:
            phase_stats["sampled-warmup"] = build_stats([float(item["latency_ms"]) for item in sampled_window])
            phase_ranges["sampled-warmup"] = build_step_range([int(item["step"]) for item in sampled_window])

    if first_activate_call is not None:
        pre_activation = [item for item in iterations if int(item["step"]) < first_activate_call]
        post_activation = [item for item in iterations if int(item["step"]) >= first_activate_call]
        phase_stats["pre-activation"] = build_stats([float(item["latency_ms"]) for item in pre_activation])
        phase_ranges["pre-activation"] = build_step_range([int(item["step"]) for item in pre_activation])
        phase_stats["post-activation"] = build_stats([float(item["latency_ms"]) for item in post_activation])
        phase_ranges["post-activation"] = build_step_range([int(item["step"]) for item in post_activation])

    return phase_stats, phase_ranges, boundary


def summarize_coordinator_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary_ready = [item for item in events if item.get("event") == "summary-ready"]
    wait_summary = [item for item in events if item.get("event") == "wait-summary"]
    observed_publish = [item for item in events if item.get("event") == "observed-publish"]
    publish = [item for item in events if item.get("event") == "publish"]
    activate = [item for item in events if item.get("event") == "activate"]

    return {
        "event_count": len(events),
        "summary_ready_count": len(summary_ready),
        "wait_summary_count": len(wait_summary),
        "wait_summary_missing_ranks": sorted(
            {int(item["missing_rank"]) for item in wait_summary if isinstance(item.get("missing_rank"), int)}
        ),
        "observed_publish_count": len(observed_publish),
        "first_publish": first_event(publish, "effective_call", "call", "phase"),
        "first_activate": first_event(activate, "call", "effective_call", "phase"),
        "activated_candidates": sorted({item["candidate"] for item in activate if "candidate" in item}),
    }


def summarize_completion_events(
    events: list[dict[str, Any]],
    fallback_events: list[dict[str, Any]],
) -> dict[str, Any]:
    records = [item for item in events if item.get("event") == "record-ready"]
    sampled_records = [item for item in records if item.get("sampled") is True]
    partial_records = [item for item in records if item.get("partial") is True]
    host_fallback_records = [item for item in records if item.get("host_fallback") is True]
    unavailable = [item for item in fallback_events if item.get("fallback") == "unavailable"]
    contended = [item for item in fallback_events if item.get("fallback") == "contended"]

    sampled_phases = [int(item["phase"]) for item in sampled_records if isinstance(item.get("phase"), int)]
    return {
        "event_count": len(events),
        "enqueue_count": sum(1 for item in events if item.get("event") == "enqueue"),
        "attach_count": sum(1 for item in events if item.get("event") == "attach"),
        "attach_miss_count": sum(1 for item in events if item.get("event") == "attach-miss"),
        "record_ready_count": len(records),
        "sampled_record_count": len(sampled_records),
        "partial_record_count": len(partial_records),
        "host_fallback_count": len(host_fallback_records),
        "sampled_phase": build_step_stats(sampled_phases) if sampled_phases else None,
        "unavailable_count": len(unavailable),
        "contended_count": len(contended),
        "unavailable_candidates": sorted({item["candidate"] for item in unavailable if "candidate" in item}),
    }


def parse_log(
    path: Path,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[str]],
]:
    iterations: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    coordinator_events: list[dict[str, Any]] = []
    completion_events: list[dict[str, Any]] = []
    fallback_events: list[dict[str, Any]] = []
    plugin_paths: dict[str, set[str]] = {"profiler": set(), "tuner": set()}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            for event in iter_json_objects(line):
                if event.get("event") in JSON_EVENTS:
                    if event["event"] == "iteration":
                        iterations.append(event)
                    elif event["event"] == "summary":
                        summary = event
            if line.startswith("{") and '"event"' in line:
                continue
            for match in PLUGIN_LOAD_RE.finditer(line):
                plugin_paths[match.group("kind")].add(match.group("path"))
            if EVENT_PREFIX not in line:
                continue
            for match in DIAGNOSTIC_EVENT_RE.finditer(line):
                category = match.group("category")
                item: dict[str, Any] = {
                    "event": match.group("kind"),
                }
                item.update(parse_key_values(match.group("body")))
                if "comm" in item:
                    item["comm_id"] = item.pop("comm")
                if category == "coordinator":
                    coordinator_events.append(item)
                else:
                    completion_events.append(item)
            for match in TUNER_FALLBACK_RE.finditer(line):
                item = {
                    "event": "fallback",
                    "fallback": match.group("kind"),
                }
                body = match.group("body") or ""
                item.update(parse_key_values(body))
                fallback_events.append(item)
    return (
        iterations,
        summary,
        coordinator_events,
        completion_events,
        fallback_events,
        {kind: sorted(paths) for kind, paths in plugin_paths.items()},
    )


def summarize_run(args: argparse.Namespace) -> None:
    log_path = Path(args.log)
    metadata_path = Path(args.metadata)
    output_path = Path(args.output)
    trajectory_path = Path(args.trajectory_output)

    metadata = load_json(metadata_path)
    iterations, summary, coordinator_events, completion_events, fallback_events, plugin_paths = parse_log(log_path)
    if summary is None:
        raise SystemExit(f"missing summary event in {log_path}")

    phase_iterations: dict[str, list[float]] = defaultdict(list)
    for item in iterations:
        phase_iterations[item.get("phase", "steady")].append(float(item["latency_ms"]))
    diagnostic_phase_stats, diagnostic_phase_ranges, activation_boundary = derive_diagnostic_phases(
        metadata["mode"],
        iterations,
        coordinator_events,
    )
    selected_path_observability = summarize_selected_path_observability(completion_events, activation_boundary)

    run_summary = {
        "experiment_type": metadata["experiment_type"],
        "mode": metadata["mode"],
        "replicate_id": metadata["replicate_id"],
        "run_order": metadata["run_order"],
        "message_mb": metadata.get("message_mb"),
        "size_bucket": metadata.get("size_bucket"),
        "topology_group": metadata.get("topology_group"),
        "phase_iteration_stats": {phase: build_stats(values) for phase, values in sorted(phase_iterations.items())},
        "phase_step_ranges": build_phase_step_ranges(iterations),
        "diagnostic_phase_iteration_stats": diagnostic_phase_stats,
        "diagnostic_phase_step_ranges": diagnostic_phase_ranges,
        "activation_boundary": activation_boundary,
        "diagnostics": {
            "coordinator": summarize_coordinator_events(coordinator_events),
            "completion": summarize_completion_events(completion_events, fallback_events),
        },
        "selected_path_observability": selected_path_observability,
        "iteration_count": len(iterations),
        "plugin_paths": plugin_paths,
        "harness": summary.get("harness", {}),
        "metric_avg_ms": summary.get("overall_metric_avg_ms", {}),
        "summary": summary,
        "trajectory_event_count": len(coordinator_events),
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
            "events": coordinator_events,
            "completion_events": completion_events,
            "fallback_events": fallback_events,
        },
    )


def aggregate_mode_comparison(args: argparse.Namespace) -> None:
    result_dir = Path(args.result_dir)
    summaries = sorted(result_dir.glob("replicate-*/run-*/summary.json"))
    mode_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for summary_path in summaries:
        payload = load_json(summary_path)
        mode_runs[payload["mode"]].append(payload)

    manifest_path = result_dir / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    aggregate: dict[str, Any] = {
        "experiment_type": args.experiment_type,
        "run_label": manifest.get("run_label"),
        "topology_group": manifest.get("topology_group"),
        "cuda_visible_devices": manifest.get("cuda_visible_devices"),
        "cpu_affinity": manifest.get("cpu_affinity"),
        "numa_nodes": manifest.get("numa_nodes"),
        "cross_socket": manifest.get("cross_socket"),
        "static_replay_candidate": manifest.get("static_replay_candidate"),
        "modes": {},
    }
    for mode, runs in sorted(mode_runs.items()):
        avg_values: list[float] = []
        max_values: list[float] = []
        run_avg_values: list[float] = []
        phase_values: dict[str, list[float]] = defaultdict(list)
        diagnostic_phase_values: dict[str, list[float]] = defaultdict(list)
        metric_run_values: dict[str, list[float]] = defaultdict(list)
        plugin_paths: dict[str, set[str]] = defaultdict(set)
        selected_path_sections: list[dict[str, Any]] = []
        activated_candidates: set[str] = set()
        for run in runs:
            per_rank = run["summary"].get("per_rank", [])
            avg_values.extend(float(item["avg_ms"]) for item in per_rank)
            max_values.extend(float(item["max_ms"]) for item in per_rank)
            run_avg_values.append(float(run["summary"]["overall_avg_ms"]["avg_ms"]))
            for phase, stats in run.get("phase_iteration_stats", {}).items():
                phase_values[phase].append(float(stats["avg_ms"]))
            for phase, stats in run.get("diagnostic_phase_iteration_stats", {}).items():
                diagnostic_phase_values[phase].append(float(stats["avg_ms"]))
            for metric_name, stats in run.get("summary", {}).get("overall_metric_avg_ms", {}).items():
                if metric_name not in MEASUREMENT_METRIC_FIELDS or not isinstance(stats, dict):
                    continue
                if int(stats.get("count", 0)) > 0:
                    metric_run_values[metric_name].append(float(stats.get("avg_ms", 0.0)))
            for kind, values in run.get("plugin_paths", {}).items():
                plugin_paths[kind].update(values)
            selected_path_sections.append(run.get("selected_path_observability", {}))
            coordinator = run.get("diagnostics", {}).get("coordinator", {})
            activated_candidates.update(str(item) for item in coordinator.get("activated_candidates", []))
        aggregate["modes"][mode] = {
            "replicate_count": len(runs),
            "per_rank_avg_ms": build_stats(avg_values),
            "per_rank_max_ms": build_stats(max_values),
            "run_avg_ms": build_stats(run_avg_values),
            "phase_avg_ms": {phase: build_stats(values) for phase, values in sorted(phase_values.items())},
            "diagnostic_phase_avg_ms": {
                phase: build_stats(values) for phase, values in sorted(diagnostic_phase_values.items())
            },
            "metric_run_avg_ms": {
                metric_name: build_stats(values) for metric_name, values in sorted(metric_run_values.items())
            },
            "plugin_paths": {kind: sorted(values) for kind, values in sorted(plugin_paths.items())},
            "activated_candidates": sorted(activated_candidates),
            "selected_path_observability": merge_selected_path_sections(selected_path_sections),
            "runs": [
                {
                    "replicate_id": run["replicate_id"],
                    "run_order": run["run_order"],
                    "message_mb": run.get("message_mb"),
                    "run_avg_ms": round(float(run["summary"]["overall_avg_ms"]["avg_ms"]), 3),
                    "phase_step_ranges": run.get("phase_step_ranges", {}),
                    "diagnostic_phase_iteration_stats": run.get("diagnostic_phase_iteration_stats", {}),
                    "diagnostic_phase_step_ranges": run.get("diagnostic_phase_step_ranges", {}),
                    "activation_boundary": run.get("activation_boundary", {}),
                    "diagnostics": run.get("diagnostics", {}),
                    "plugin_paths": run.get("plugin_paths", {}),
                    "harness": run.get("harness", {}),
                    "metric_avg_ms": run.get("metric_avg_ms", {}),
                    "selected_path_observability": run.get("selected_path_observability", {}),
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

    manifest_path = result_dir / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    payload: dict[str, Any] = {
        "experiment_type": args.experiment_type,
        "topology_group": manifest.get("topology_group"),
        "cuda_visible_devices": manifest.get("cuda_visible_devices"),
        "cpu_affinity": manifest.get("cpu_affinity"),
        "numa_nodes": manifest.get("numa_nodes"),
        "cross_socket": manifest.get("cross_socket"),
        "sizes": {},
    }
    for size_key, runs in sorted(grouped.items(), key=lambda item: int(item[0].removesuffix("MB"))):
        avg_values: list[float] = []
        run_avg_values: list[float] = []
        phases: dict[str, list[float]] = defaultdict(list)
        trajectory_rows: list[dict[str, Any]] = []
        for run in runs:
            per_rank = run["summary"].get("per_rank", [])
            avg_values.extend(float(item["avg_ms"]) for item in per_rank)
            run_avg_values.append(float(run["summary"]["overall_avg_ms"]["avg_ms"]))
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
            "run_avg_ms": build_stats(run_avg_values),
            "phase_avg_ms": {phase: build_stats(values) for phase, values in sorted(phases.items())},
            "candidate_set": sorted({row["candidate"] for row in trajectory_rows}),
            "candidate_trajectory": sorted(
                trajectory_rows,
                key=lambda item: (item["replicate_id"], item["run_order"], item.get("next_epoch", 0), item.get("epoch", 0)),
            ),
        }
    dump_json(Path(args.output), payload)


def aggregate_topology_matrix(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    manifest = load_json(manifest_path)
    result_root = manifest_path.parent

    expected_plugin_path = manifest.get("expected_plugin_path", "")
    summary: dict[str, Any] = {
        "run_label": manifest.get("run_label"),
        "result_root": str(result_root),
        "expected_plugin_path": expected_plugin_path,
        "groups": {},
        "recheck_shift": {
            "group": manifest.get("recheck_shift", {}).get("group"),
            "variants": {},
        },
    }

    candidate_signatures: dict[str, dict[str, tuple[str, ...]]] = {}
    for group_name, group_info in sorted(manifest.get("groups", {}).items()):
        smoke_dir = resolve_path(result_root, group_info["smoke_dir"])
        mode_dir = resolve_path(result_root, group_info["mode_comparison_dir"])
        size_dir = resolve_path(result_root, group_info["size_sweep_dir"])

        smoke_summary = load_json(smoke_dir / "comparison-summary.json")
        mode_summary = load_json(mode_dir / "comparison-summary.json")
        size_summary = load_json(size_dir / "candidate-trajectories.json")

        final_steady_stats = mode_summary.get("modes", {}).get("final-steady", {}).get("phase_avg_ms", {}).get("steady", {})
        weak_online_stats = mode_summary.get("modes", {}).get("weak-online", {}).get("phase_avg_ms", {})
        steady_delta_ms = None
        if final_steady_stats and weak_online_stats.get("steady"):
            steady_delta_ms = round(
                float(weak_online_stats["steady"]["avg_ms"]) - float(final_steady_stats["avg_ms"]),
                3,
            )

        plugin_paths = {
            mode_name: payload.get("plugin_paths", {})
            for mode_name, payload in sorted(mode_summary.get("modes", {}).items())
        }
        plugin_path_matches = {
            mode_name: {
                kind: expected_plugin_path in paths
                for kind, paths in sorted(payload.get("plugin_paths", {}).items())
            }
            for mode_name, payload in sorted(mode_summary.get("modes", {}).items())
        }

        size_candidates = {
            size_key: tuple(payload.get("candidate_set", []))
            for size_key, payload in sorted(size_summary.get("sizes", {}).items())
        }
        candidate_signatures[group_name] = size_candidates

        summary["groups"][group_name] = {
            "placement": {
                "cuda_visible_devices": group_info.get("cuda_visible_devices"),
                "nproc_per_node": group_info.get("nproc_per_node"),
                "cpu_affinity": group_info.get("cpu_affinity"),
                "numa_nodes": group_info.get("numa_nodes"),
                "cross_socket": group_info.get("cross_socket"),
            },
            "smoke_baseline": smoke_summary.get("modes", {}).get("baseline"),
            "mode_comparison": mode_summary.get("modes", {}),
            "weak_online_phase_delta_vs_final_steady_ms": steady_delta_ms,
            "plugin_paths": plugin_paths,
            "plugin_path_matches_expected": plugin_path_matches,
            "size_sweep": size_summary.get("sizes", {}),
        }

    same_socket_groups = [name for name in summary["groups"] if name.startswith("numa")]
    same_socket_signatures = [candidate_signatures[name] for name in same_socket_groups]
    cross_signature = candidate_signatures.get("cross-8gpu", {})

    if same_socket_signatures and all(signature == same_socket_signatures[0] for signature in same_socket_signatures):
        if cross_signature and cross_signature != same_socket_signatures[0]:
            summary["size_bucket_conclusion"] = "cross-only-divergence"
        else:
            summary["size_bucket_conclusion"] = "no-stable-divergence"
    else:
        summary["size_bucket_conclusion"] = "same-socket-divergence"

    for variant in manifest.get("recheck_shift", {}).get("variants", []):
        variant_dir = resolve_path(result_root, variant["result_dir"])
        variant_summary = load_json(variant_dir / "comparison-summary.json")
        weak_online = variant_summary.get("modes", {}).get("weak-online", {})
        first_recheck_steps = [
            int(run["phase_step_ranges"]["recheck"]["first_step"])
            for run in weak_online.get("runs", [])
            if "recheck" in run.get("phase_step_ranges", {})
        ]
        summary["recheck_shift"]["variants"][variant["label"]] = {
            "recheck_after": variant["recheck_after"],
            "run_avg_ms": weak_online.get("run_avg_ms"),
            "phase_avg_ms": weak_online.get("phase_avg_ms"),
            "first_recheck_step": build_step_stats(first_recheck_steps) if first_recheck_steps else None,
        }

    dump_json(Path(args.output), summary)


def nested_get(payload: dict[str, Any], *keys: str) -> Any:
    node: Any = payload
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def avg_ms_from(payload: dict[str, Any], *keys: str) -> float | None:
    node = nested_get(payload, *keys)
    if not isinstance(node, dict):
        return None
    value = node.get("avg_ms")
    return float(value) if isinstance(value, (int, float)) else None


def diff_ms(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 3)


def pct_improvement(reference_ms: float | None, contender_ms: float | None) -> float | None:
    if reference_ms is None or contender_ms is None or reference_ms <= 0:
        return None
    return round(((reference_ms - contender_ms) / reference_ms) * 100.0, 3)


def replicate_run_avg_map(mode_payload: dict[str, Any]) -> dict[int, float]:
    mapping: dict[int, float] = {}
    for run in mode_payload.get("runs", []):
        replicate_id = run.get("replicate_id")
        run_avg = run.get("run_avg_ms")
        if isinstance(replicate_id, int) and isinstance(run_avg, (int, float)):
            mapping[replicate_id] = float(run_avg)
    return mapping


def build_improvement_vote(
    baseline_mode: dict[str, Any],
    contender_mode: dict[str, Any],
    expected_replicates: int,
) -> dict[str, Any]:
    baseline_runs = replicate_run_avg_map(baseline_mode)
    contender_runs = replicate_run_avg_map(contender_mode)
    comparable = sorted(set(baseline_runs) & set(contender_runs))

    improved: list[int] = []
    regressed: list[int] = []
    flat: list[int] = []
    for replicate_id in comparable:
        baseline_avg = baseline_runs[replicate_id]
        contender_avg = contender_runs[replicate_id]
        if contender_avg < baseline_avg:
            improved.append(replicate_id)
        elif contender_avg > baseline_avg:
            regressed.append(replicate_id)
        else:
            flat.append(replicate_id)

    required = max(1, math.ceil((2 * expected_replicates) / 3))
    return {
        "expected_replicates": expected_replicates,
        "comparable_replicates": comparable,
        "comparable_count": len(comparable),
        "improved_replicates": improved,
        "improved_count": len(improved),
        "regressed_replicates": regressed,
        "regressed_count": len(regressed),
        "flat_replicates": flat,
        "flat_count": len(flat),
        "required_improved_count": required,
        "threshold_met": len(comparable) == expected_replicates and len(improved) >= required,
    }


def first_candidate_aligned_summary(root: Path) -> tuple[Path | None, dict[str, Any] | None]:
    if not root.exists():
        return None, None
    candidates = sorted(root.glob("*/comparison-summary.json"))
    if not candidates:
        return None, None
    summary_path = candidates[0]
    return summary_path, load_json(summary_path)


def build_selected_path_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_set: set[str] = set()
    algo_set: set[str] = set()
    proto_set: set[str] = set()
    nchannels_set: set[int] = set()
    signature_counts: dict[tuple[str, str, str, int | None], int] = defaultdict(int)
    parsable_record_count = 0

    for record in records:
        candidate = record.get("candidate")
        selected_algo = record.get("selected_algo")
        selected_proto = record.get("selected_proto")
        raw_nchannels = record.get("nchannels")
        n_channels = raw_nchannels if isinstance(raw_nchannels, int) else None

        if not isinstance(candidate, str):
            candidate = ""
        if not isinstance(selected_algo, str):
            selected_algo = ""
        if not isinstance(selected_proto, str):
            selected_proto = ""

        if not candidate and not selected_algo and not selected_proto and n_channels is None:
            continue

        parsable_record_count += 1
        if candidate:
            candidate_set.add(candidate)
        if selected_algo:
            algo_set.add(selected_algo)
        if selected_proto:
            proto_set.add(selected_proto)
        if n_channels is not None:
            nchannels_set.add(n_channels)
        signature_counts[(candidate, selected_algo, selected_proto, n_channels)] += 1

    signatures = [
        {
            "candidate": candidate,
            "selectedAlgo": selected_algo,
            "selectedProto": selected_proto,
            "nChannels": n_channels,
            "count": count,
        }
        for (candidate, selected_algo, selected_proto, n_channels), count in sorted(
            signature_counts.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2],
                item[0][3] if item[0][3] is not None else -1,
            ),
        )
    ]

    return {
        "record_count": len(records),
        "parsable_record_count": parsable_record_count,
        "candidate_set": sorted(candidate_set),
        "selectedAlgo_set": sorted(algo_set),
        "selectedProto_set": sorted(proto_set),
        "nChannels_set": sorted(nchannels_set),
        "signatures": signatures,
    }


def summarize_selected_path_observability(
    completion_events: list[dict[str, Any]],
    activation_boundary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    records = [item for item in completion_events if item.get("event") == "record-ready"]
    allreduce_records = [
        item for item in records if isinstance(item.get("key"), str) and str(item["key"]).startswith("allreduce:")
    ]
    attached_allreduce_records = [item for item in allreduce_records if item.get("attached") is True]
    sections: dict[str, dict[str, Any]] = {
        "overall": build_selected_path_stats(records),
        "sampled": build_selected_path_stats([item for item in records if item.get("sampled") is True]),
        "allreduce": build_selected_path_stats(allreduce_records),
        "allreduce-attached": build_selected_path_stats(attached_allreduce_records),
        "allreduce-sampled": build_selected_path_stats(
            [item for item in allreduce_records if item.get("sampled") is True]
        ),
    }

    first_activate_call = activation_boundary.get("first_activate_call")
    if isinstance(first_activate_call, int):
        sections["pre-activation"] = build_selected_path_stats(
            [
                item
                for item in records
                if isinstance(item.get("phase"), int) and int(item["phase"]) < first_activate_call
            ]
        )
        sections["post-activation"] = build_selected_path_stats(
            [
                item
                for item in records
                if isinstance(item.get("phase"), int) and int(item["phase"]) >= first_activate_call
            ]
        )
        sections["allreduce-pre-activation"] = build_selected_path_stats(
            [
                item
                for item in attached_allreduce_records
                if isinstance(item.get("phase"), int) and int(item["phase"]) < first_activate_call
            ]
        )
        sections["allreduce-post-activation"] = build_selected_path_stats(
            [
                item
                for item in attached_allreduce_records
                if isinstance(item.get("phase"), int) and int(item["phase"]) >= first_activate_call
            ]
        )

    return sections


def merge_selected_path_stats(path_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_set: set[str] = set()
    algo_set: set[str] = set()
    proto_set: set[str] = set()
    nchannels_set: set[int] = set()
    signature_counts: dict[tuple[str, str, str, int | None], int] = defaultdict(int)
    record_count = 0
    parsable_record_count = 0

    for summary in path_summaries:
        record_count += int(summary.get("record_count", 0))
        parsable_record_count += int(summary.get("parsable_record_count", 0))
        candidate_set.update(str(item) for item in summary.get("candidate_set", []))
        algo_set.update(str(item) for item in summary.get("selectedAlgo_set", []))
        proto_set.update(str(item) for item in summary.get("selectedProto_set", []))
        for item in summary.get("nChannels_set", []):
            if isinstance(item, int):
                nchannels_set.add(item)
        for signature in summary.get("signatures", []):
            candidate = signature.get("candidate")
            selected_algo = signature.get("selectedAlgo")
            selected_proto = signature.get("selectedProto")
            n_channels = signature.get("nChannels")
            count = signature.get("count")
            if not isinstance(candidate, str):
                candidate = ""
            if not isinstance(selected_algo, str):
                selected_algo = ""
            if not isinstance(selected_proto, str):
                selected_proto = ""
            if not isinstance(n_channels, int):
                n_channels = None
            if not isinstance(count, int):
                continue
            signature_counts[(candidate, selected_algo, selected_proto, n_channels)] += count

    signatures = [
        {
            "candidate": candidate,
            "selectedAlgo": selected_algo,
            "selectedProto": selected_proto,
            "nChannels": n_channels,
            "count": count,
        }
        for (candidate, selected_algo, selected_proto, n_channels), count in sorted(
            signature_counts.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2],
                item[0][3] if item[0][3] is not None else -1,
            ),
        )
    ]

    return {
        "record_count": record_count,
        "parsable_record_count": parsable_record_count,
        "candidate_set": sorted(candidate_set),
        "selectedAlgo_set": sorted(algo_set),
        "selectedProto_set": sorted(proto_set),
        "nChannels_set": sorted(nchannels_set),
        "signatures": signatures,
    }


def merge_selected_path_sections(path_sections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    section_order = [
        "overall",
        "sampled",
        "allreduce",
        "allreduce-attached",
        "allreduce-sampled",
        "pre-activation",
        "post-activation",
        "allreduce-pre-activation",
        "allreduce-post-activation",
    ]
    merged: dict[str, dict[str, Any]] = {}
    for section_name in section_order:
        summaries = [sections[section_name] for sections in path_sections if section_name in sections]
        if summaries:
            merged[section_name] = merge_selected_path_stats(summaries)
    return merged


def mode_summary_excerpt(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "replicate_count": payload.get("replicate_count"),
        "run_avg_ms": payload.get("run_avg_ms"),
        "phase_avg_ms": payload.get("phase_avg_ms", {}),
        "diagnostic_phase_avg_ms": payload.get("diagnostic_phase_avg_ms", {}),
        "plugin_paths": payload.get("plugin_paths", {}),
        "activated_candidates": payload.get("activated_candidates", []),
        "selected_path_observability": payload.get("selected_path_observability", {}),
        "runs": payload.get("runs", []),
    }


def single_candidate(candidates: list[Any]) -> str | None:
    values = [str(item) for item in candidates if item not in {None, ""}]
    unique = sorted(set(values))
    if len(unique) != 1:
        return None
    return unique[0]


def summarize_same_socket_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    first_publish_calls: list[int] = []
    first_activate_calls: list[int] = []
    activated_candidates: set[str] = set()
    wait_summary_total = 0
    summary_ready_total = 0
    observed_publish_total = 0
    sampled_completion_total = 0
    partial_completion_total = 0
    host_fallback_total = 0
    unavailable_total = 0
    contended_total = 0
    trimmed_runs: list[dict[str, Any]] = []

    for run in runs:
        coordinator = nested_get(run, "diagnostics", "coordinator") or {}
        completion = nested_get(run, "diagnostics", "completion") or {}
        activation_boundary = run.get("activation_boundary", {})
        if isinstance(activation_boundary.get("first_publish_effective_call"), int):
            first_publish_calls.append(int(activation_boundary["first_publish_effective_call"]))
        elif isinstance(nested_get(coordinator, "first_publish", "effective_call"), int):
            first_publish_calls.append(int(nested_get(coordinator, "first_publish", "effective_call")))
        if isinstance(activation_boundary.get("first_activate_call"), int):
            first_activate_calls.append(int(activation_boundary["first_activate_call"]))
        elif isinstance(nested_get(coordinator, "first_activate", "call"), int):
            first_activate_calls.append(int(nested_get(coordinator, "first_activate", "call")))
        activated_candidates.update(str(item) for item in coordinator.get("activated_candidates", []))
        wait_summary_total += int(coordinator.get("wait_summary_count", 0))
        summary_ready_total += int(coordinator.get("summary_ready_count", 0))
        observed_publish_total += int(coordinator.get("observed_publish_count", 0))
        sampled_completion_total += int(completion.get("sampled_record_count", 0))
        partial_completion_total += int(completion.get("partial_record_count", 0))
        host_fallback_total += int(completion.get("host_fallback_count", 0))
        unavailable_total += int(completion.get("unavailable_count", 0))
        contended_total += int(completion.get("contended_count", 0))
        trimmed_runs.append(
            {
                "replicate_id": run.get("replicate_id"),
                "run_order": run.get("run_order"),
                "run_avg_ms": run.get("run_avg_ms"),
                "diagnostic_phase_iteration_stats": run.get("diagnostic_phase_iteration_stats", {}),
                "diagnostic_phase_step_ranges": run.get("diagnostic_phase_step_ranges", {}),
                "activation_boundary": activation_boundary,
                "diagnostics": run.get("diagnostics", {}),
            }
        )

    return {
        "first_publish_effective_call": build_step_stats(first_publish_calls) if first_publish_calls else None,
        "first_activate_call": build_step_stats(first_activate_calls) if first_activate_calls else None,
        "activated_candidates": sorted(activated_candidates),
        "wait_summary_count_total": wait_summary_total,
        "summary_ready_count_total": summary_ready_total,
        "observed_publish_count_total": observed_publish_total,
        "sampled_completion_count_total": sampled_completion_total,
        "partial_completion_count_total": partial_completion_total,
        "host_fallback_count_total": host_fallback_total,
        "unavailable_count_total": unavailable_total,
        "contended_fallback_count_total": contended_total,
        "runs": trimmed_runs,
    }


def aggregate_same_socket_isolation(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    manifest = load_json(manifest_path)
    result_root = manifest_path.parent

    summary: dict[str, Any] = {
        "run_label": manifest.get("run_label"),
        "result_root": str(result_root),
        "expected_plugin_path": manifest.get("expected_plugin_path"),
        "container_image": manifest.get("container_image", {}),
        "parameters": manifest.get("parameters", {}),
        "groups": {},
    }

    for group_name, group_info in sorted(manifest.get("groups", {}).items()):
        mode_dir = resolve_path(result_root, group_info["mode_comparison_dir"])
        comparison = load_json(mode_dir / "comparison-summary.json")
        profiler = comparison.get("modes", {}).get("profiler-only", {})
        final_steady = comparison.get("modes", {}).get("final-steady", {})

        profiler_callback = avg_ms_from(profiler, "diagnostic_phase_avg_ms", "callback-only")
        final_overall = avg_ms_from(final_steady, "diagnostic_phase_avg_ms", "overall")
        final_pre = avg_ms_from(final_steady, "diagnostic_phase_avg_ms", "pre-activation")
        final_post = avg_ms_from(final_steady, "diagnostic_phase_avg_ms", "post-activation")

        summary["groups"][group_name] = {
            "placement": {
                "cuda_visible_devices": group_info.get("cuda_visible_devices"),
                "nproc_per_node": group_info.get("nproc_per_node"),
                "cpu_affinity": group_info.get("cpu_affinity"),
                "numa_nodes": group_info.get("numa_nodes"),
                "cross_socket": group_info.get("cross_socket"),
            },
            "modes": {
                "profiler-only": {
                    "run_avg_ms": profiler.get("run_avg_ms"),
                    "diagnostic_phase_avg_ms": profiler.get("diagnostic_phase_avg_ms", {}),
                    "plugin_paths": profiler.get("plugin_paths", {}),
                    "runs": profiler.get("runs", []),
                },
                "final-steady": {
                    "run_avg_ms": final_steady.get("run_avg_ms"),
                    "diagnostic_phase_avg_ms": final_steady.get("diagnostic_phase_avg_ms", {}),
                    "plugin_paths": final_steady.get("plugin_paths", {}),
                    **summarize_same_socket_runs(final_steady.get("runs", [])),
                },
            },
            "delta_vs_profiler_only_ms": {
                "overall": diff_ms(final_overall, profiler_callback),
                "pre_activation": diff_ms(final_pre, profiler_callback),
                "post_activation": diff_ms(final_post, profiler_callback),
                "pre_minus_post": diff_ms(final_pre, final_post),
            },
        }

    dump_json(Path(args.output), summary)


def aggregate_numa1_mechanism_decomposition(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    manifest = load_json(manifest_path)
    result_root = manifest_path.parent

    group_name = "numa1-4gpu"
    group_info = manifest.get("groups", {}).get(group_name)
    if not isinstance(group_info, dict):
        raise SystemExit(f"missing {group_name} group in {manifest_path}")

    mode_dir = resolve_path(result_root, group_info["mode_comparison_dir"])
    comparison = load_json(mode_dir / "comparison-summary.json")

    baseline = comparison.get("modes", {}).get("baseline", {})
    profiler = comparison.get("modes", {}).get("profiler-only", {})
    static_replay = comparison.get("modes", {}).get("static-replay", {})
    final_steady = comparison.get("modes", {}).get("final-steady", {})

    requested_static_replay_candidate = manifest.get("parameters", {}).get(
        "static_replay_candidate",
        comparison.get("static_replay_candidate"),
    )
    primary_static_replay_candidates = (
        static_replay.get("selected_path_observability", {})
        .get("allreduce-attached", {})
        .get("candidate_set", [])
    )
    final_steady_candidates = final_steady.get("activated_candidates", [])
    learned_candidate = single_candidate(final_steady_candidates)

    candidate_aligned_replay_info = manifest.get("candidate_aligned_replay", {})
    candidate_aligned_replay_dir = None
    candidate_aligned_replay_summary = None
    candidate_aligned_replay_mode: dict[str, Any] | None = None
    candidate_aligned_replay_candidate = None
    candidate_aligned_replay_observed_candidates: list[str] = []
    if isinstance(candidate_aligned_replay_info, dict):
        replay_dir_raw = candidate_aligned_replay_info.get("result_dir")
        if isinstance(replay_dir_raw, str) and replay_dir_raw:
            candidate_aligned_replay_dir = replay_dir_raw
            replay_dir = resolve_path(result_root, replay_dir_raw)
            summary_path = replay_dir / "comparison-summary.json"
            if summary_path.exists():
                candidate_aligned_replay_summary = load_json(summary_path)
                candidate_aligned_replay_candidate = candidate_aligned_replay_summary.get("static_replay_candidate")
                candidate_aligned_replay_mode = candidate_aligned_replay_summary.get("modes", {}).get("static-replay", {})
                candidate_aligned_replay_observed_candidates = (
                    candidate_aligned_replay_mode.get("selected_path_observability", {})
                    .get("allreduce-attached", {})
                    .get("candidate_set", [])
                )

    candidate_alignment_status = "unknown"
    dynamic_comparison_ready = False
    if learned_candidate is None:
        if final_steady_candidates:
            candidate_alignment_status = "drift"
    elif learned_candidate == requested_static_replay_candidate:
        candidate_alignment_status = "aligned"
        dynamic_comparison_ready = True
    elif candidate_aligned_replay_candidate == learned_candidate:
        candidate_alignment_status = "aligned-via-supplemental-replay"
        dynamic_comparison_ready = True
    else:
        candidate_alignment_status = "mismatch"

    profiler_avg = avg_ms_from(profiler, "diagnostic_phase_avg_ms", "callback-only") or avg_ms_from(
        profiler, "run_avg_ms"
    )
    baseline_avg = avg_ms_from(baseline, "run_avg_ms")
    static_replay_avg = avg_ms_from(static_replay, "run_avg_ms")
    final_post_activation_avg = avg_ms_from(final_steady, "diagnostic_phase_avg_ms", "post-activation")
    candidate_aligned_replay_avg = (
        avg_ms_from(candidate_aligned_replay_mode, "run_avg_ms") if candidate_aligned_replay_mode else None
    )

    dynamic_reference = {
        "mode": "static-replay",
        "candidate": requested_static_replay_candidate,
        "avg_ms": static_replay_avg,
        "delta_vs_final_steady_post_activation_ms": diff_ms(final_post_activation_avg, static_replay_avg),
    }
    if candidate_alignment_status == "aligned-via-supplemental-replay":
        dynamic_reference = {
            "mode": "candidate-aligned-replay",
            "candidate": candidate_aligned_replay_candidate,
            "avg_ms": candidate_aligned_replay_avg,
            "delta_vs_final_steady_post_activation_ms": diff_ms(
                final_post_activation_avg,
                candidate_aligned_replay_avg,
            ),
        }

    payload: dict[str, Any] = {
        "run_label": manifest.get("run_label"),
        "result_root": str(result_root),
        "expected_plugin_path": manifest.get("expected_plugin_path"),
        "container_image": manifest.get("container_image", {}),
        "parameters": manifest.get("parameters", {}),
        "group": {
            "name": group_name,
            "placement": {
                "cuda_visible_devices": group_info.get("cuda_visible_devices"),
                "nproc_per_node": group_info.get("nproc_per_node"),
                "cpu_affinity": group_info.get("cpu_affinity"),
                "numa_nodes": group_info.get("numa_nodes"),
                "cross_socket": group_info.get("cross_socket"),
            },
            "primary_mode_comparison_dir": group_info.get("mode_comparison_dir"),
            "modes": {
                "baseline": mode_summary_excerpt(baseline),
                "profiler-only": mode_summary_excerpt(profiler),
                "static-replay": mode_summary_excerpt(static_replay),
                "final-steady": mode_summary_excerpt(final_steady),
            },
            "candidate_alignment": {
                "status": candidate_alignment_status,
                "dynamic_comparison_ready": dynamic_comparison_ready,
                "requested_static_replay_candidate": requested_static_replay_candidate,
                "primary_static_replay_observed_candidates": primary_static_replay_candidates,
                "final_steady_activated_candidates": final_steady_candidates,
                "final_steady_learned_candidate": learned_candidate,
                "candidate_aligned_replay_candidate": candidate_aligned_replay_candidate,
                "candidate_aligned_replay_observed_candidates": candidate_aligned_replay_observed_candidates,
                "candidate_aligned_replay_dir": candidate_aligned_replay_dir,
            },
            "decomposition_ms": {
                "profiler_only_minus_baseline": diff_ms(profiler_avg, baseline_avg),
                "static_replay_minus_profiler_only": diff_ms(static_replay_avg, profiler_avg),
                "final_steady_post_activation_minus_static_replay": diff_ms(
                    final_post_activation_avg,
                    static_replay_avg,
                ),
                "final_steady_post_activation_minus_candidate_aligned_replay": diff_ms(
                    final_post_activation_avg,
                    candidate_aligned_replay_avg,
                ),
            },
            "dynamic_residual_reference": dynamic_reference,
        },
    }
    if candidate_aligned_replay_mode is not None:
        payload["group"]["candidate_aligned_replay"] = {
            "mode_comparison_dir": candidate_aligned_replay_dir,
            "static_replay_candidate": candidate_aligned_replay_candidate,
            "mode_summary": mode_summary_excerpt(candidate_aligned_replay_mode),
        }

    dump_json(Path(args.output), payload)


def analyze_switching_value_phase1_entry(
    result_root: Path,
    entry: dict[str, Any],
    expected_replicates: int,
    threshold_pct: float,
) -> dict[str, Any]:
    size_mb = entry.get("size_mb")
    size_label = entry.get("size_label")
    primary_dir_raw = entry.get("primary_dir")
    candidate_root_raw = entry.get("candidate_aligned_root")

    payload: dict[str, Any] = {
        "size_mb": size_mb,
        "size_label": size_label,
        "primary_dir": primary_dir_raw,
        "candidate_aligned_root": candidate_root_raw,
    }

    if not isinstance(primary_dir_raw, str) or not primary_dir_raw:
        payload.update({"status": "missing", "judgment": "not-run"})
        return payload

    primary_dir = resolve_path(result_root, primary_dir_raw)
    primary_summary_path = primary_dir / "comparison-summary.json"
    if not primary_summary_path.exists():
        payload.update({"status": "missing", "judgment": "not-run"})
        return payload

    primary_summary = load_json(primary_summary_path)
    candidate_root = (
        resolve_path(result_root, candidate_root_raw)
        if isinstance(candidate_root_raw, str) and candidate_root_raw
        else primary_dir.parent / "candidate-aligned-replay"
    )
    aligned_summary_path, aligned_summary = first_candidate_aligned_summary(candidate_root)

    baseline_mode = primary_summary.get("modes", {}).get("baseline", {})
    primary_static_mode = primary_summary.get("modes", {}).get("static-replay", {})
    final_steady_mode = primary_summary.get("modes", {}).get("final-steady", {})
    weak_online_mode = primary_summary.get("modes", {}).get("weak-online", {})

    requested_candidate = primary_summary.get("static_replay_candidate")
    final_candidates = final_steady_mode.get("activated_candidates", [])
    learned_candidate = single_candidate(final_candidates)
    aligned_candidate = aligned_summary.get("static_replay_candidate") if aligned_summary else None

    if learned_candidate is None:
        alignment_status = "drift" if final_candidates else "unknown"
    elif learned_candidate == requested_candidate:
        alignment_status = "aligned"
    elif learned_candidate == aligned_candidate:
        alignment_status = "aligned-via-supplemental-replay"
    else:
        alignment_status = "mismatch"

    best_static_mode = primary_static_mode
    best_static_candidate = requested_candidate
    best_static_source = "primary-static-replay"
    best_static_summary_artifact = primary_summary_path.relative_to(result_root).as_posix()
    if alignment_status == "aligned-via-supplemental-replay" and aligned_summary is not None:
        best_static_mode = aligned_summary.get("modes", {}).get("static-replay", {})
        best_static_candidate = aligned_candidate
        best_static_source = "candidate-aligned-replay"
        if aligned_summary_path is not None:
            best_static_summary_artifact = aligned_summary_path.relative_to(result_root).as_posix()

    baseline_avg = avg_ms_from(baseline_mode, "run_avg_ms")
    best_static_avg = avg_ms_from(best_static_mode, "run_avg_ms")
    final_steady_avg = avg_ms_from(final_steady_mode, "run_avg_ms")
    weak_online_avg = avg_ms_from(weak_online_mode, "run_avg_ms")
    static_delta_pct = pct_improvement(baseline_avg, best_static_avg)
    weak_online_delta_vs_best_static_pct = pct_improvement(best_static_avg, weak_online_avg)
    vote = build_improvement_vote(baseline_mode, best_static_mode, expected_replicates)

    if alignment_status in {"mismatch", "drift", "unknown"}:
        judgment = "candidate-alignment-unresolved"
    elif static_delta_pct is not None and static_delta_pct >= threshold_pct and vote["threshold_met"]:
        judgment = "headroom-positive"
    else:
        judgment = "no proven headroom"

    payload.update(
        {
            "status": "ready",
            "requested_static_replay_candidate": requested_candidate,
            "final_steady_activated_candidates": final_candidates,
            "final_steady_learned_candidate": learned_candidate,
            "candidate_alignment_status": alignment_status,
            "candidate_aligned_replay_needed": alignment_status in {"mismatch", "aligned-via-supplemental-replay"},
            "candidate_aligned_replay_used": alignment_status == "aligned-via-supplemental-replay",
            "best_static_source": best_static_source,
            "best_static_candidate": best_static_candidate,
            "baseline_avg_ms": baseline_avg,
            "best_static_avg_ms": best_static_avg,
            "final_steady_avg_ms": final_steady_avg,
            "weak_online_avg_ms": weak_online_avg,
            "best_static_delta_vs_baseline_pct": static_delta_pct,
            "weak_online_delta_vs_best_static_pct": weak_online_delta_vs_best_static_pct,
            "replicate_vote": vote,
            "judgment": judgment,
            "summary_artifact": best_static_summary_artifact,
        }
    )
    return payload


def write_switching_value_phase1_entry_artifacts(
    result_root: Path,
    batch_label: str,
    topology_group: str,
    entry: dict[str, Any],
) -> None:
    primary_dir_raw = entry.get("primary_dir")
    if not isinstance(primary_dir_raw, str) or not primary_dir_raw:
        return
    size_root = resolve_path(result_root, primary_dir_raw).parent
    dump_json(size_root / "summary.json", entry)

    lines = [
        f"# Phase 1 {batch_label} {entry.get('size_label', 'unknown')}",
        "",
        f"- Topology group: `{topology_group}`",
        f"- Judgment: `{entry.get('judgment', 'unknown')}`",
        f"- Candidate alignment: `{entry.get('candidate_alignment_status', 'missing')}`",
        f"- Requested static replay candidate: `{entry.get('requested_static_replay_candidate', 'unknown')}`",
        f"- Learned final-steady candidate: `{entry.get('final_steady_learned_candidate', 'unknown')}`",
        f"- Best static source: `{entry.get('best_static_source', 'unknown')}`",
        f"- Best static candidate: `{entry.get('best_static_candidate', 'unknown')}`",
        f"- Best static delta vs baseline: `{entry.get('best_static_delta_vs_baseline_pct', 'unknown')}`",
        f"- Weak-online delta vs best static: `{entry.get('weak_online_delta_vs_best_static_pct', 'unknown')}`",
        f"- Replicate vote: `{entry.get('replicate_vote', {}).get('improved_count', 0)}/{entry.get('replicate_vote', {}).get('expected_replicates', 0)}` improved",
        f"- Summary artifact: `{entry.get('summary_artifact', 'unknown')}`",
    ]
    dump_text(size_root / "judgment.md", "\n".join(lines) + "\n")


def render_switching_value_phase1_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 1 Headroom Map",
        "",
        "## Batch A",
        "",
    ]
    for entry in payload.get("batch_a", {}).get("sizes", []):
        lines.append(
            "- `{size}` `{judgment}` static={delta} vote={improved}/{expected} alignment={alignment}".format(
                size=entry.get("size_label", "unknown"),
                judgment=entry.get("judgment", "unknown"),
                delta=entry.get("best_static_delta_vs_baseline_pct", "unknown"),
                improved=entry.get("replicate_vote", {}).get("improved_count", 0),
                expected=entry.get("replicate_vote", {}).get("expected_replicates", 0),
                alignment=entry.get("candidate_alignment_status", "unknown"),
            )
        )
    lines.extend(
        [
            "",
            "Promoted sizes:",
        ]
    )
    promoted = payload.get("batch_a", {}).get("promoted_sizes", [])
    if promoted:
        lines.append(f"- `{', '.join(str(item) for item in promoted)}`")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Batch B",
            "",
        ]
    )
    for entry in payload.get("batch_b", {}).get("primary_sizes", []):
        lines.append(
            "- `{size}` on `{topology}` => `{judgment}`".format(
                size=entry.get("size_label", "unknown"),
                topology=payload.get("batch_b", {}).get("primary_topology_group", "unknown"),
                judgment=entry.get("judgment", "unknown"),
            )
        )
    for entry in payload.get("batch_b", {}).get("boundary_sizes", []):
        lines.append(
            "- `{size}` on `{topology}` => `{judgment}`".format(
                size=entry.get("size_label", "unknown"),
                topology=payload.get("batch_b", {}).get("boundary_topology_group", "unknown"),
                judgment=entry.get("judgment", "unknown"),
            )
        )

    lines.extend(
        [
            "",
            "## Conclusions",
            "",
            f"- Headroom-positive regimes: `{', '.join(payload.get('headroom_map', {}).get('headroom_positive_regimes', [])) or 'none'}`",
            f"- No-proven-headroom regimes: `{', '.join(payload.get('headroom_map', {}).get('no_proven_headroom_regimes', [])) or 'none'}`",
            f"- Clean-surface-only headroom: `{', '.join(payload.get('headroom_map', {}).get('clean_surface_only_regimes', [])) or 'none'}`",
            f"- Headroom that persists on cross-8gpu: `{', '.join(payload.get('headroom_map', {}).get('persists_on_cross_8gpu_regimes', [])) or 'none'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def aggregate_switching_value_phase1(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    manifest = load_json(manifest_path)
    result_root = manifest_path.parent

    parameters = manifest.get("parameters", {})
    expected_replicates = int(parameters.get("replicates", 3))
    threshold_pct = float(parameters.get("positive_evidence_threshold_pct", 2.0))

    batch_a = manifest.get("phase1", {}).get("batch_a", {})
    batch_b = manifest.get("phase1", {}).get("batch_b", {})
    batch_a_group = batch_a.get("topology_group")
    batch_b_primary_group = batch_b.get("primary_topology_group")
    batch_b_boundary_group = batch_b.get("boundary_topology_group")
    run_boundary_group = bool(batch_b.get("run_boundary_group"))

    batch_a_entries = [
        analyze_switching_value_phase1_entry(result_root, entry, expected_replicates, threshold_pct)
        for entry in batch_a.get("entries", [])
    ]
    for entry in batch_a_entries:
        write_switching_value_phase1_entry_artifacts(result_root, "Batch A", str(batch_a_group), entry)

    promoted_sizes = [
        int(entry["size_mb"])
        for entry in batch_a_entries
        if isinstance(entry.get("size_mb"), int) and entry.get("judgment") == "headroom-positive"
    ]

    primary_entry_map = {
        int(entry["size_mb"]): entry
        for entry in batch_b.get("primary_entries", [])
        if isinstance(entry.get("size_mb"), int)
    }
    boundary_entry_map = {
        int(entry["size_mb"]): entry
        for entry in batch_b.get("boundary_entries", [])
        if isinstance(entry.get("size_mb"), int)
    }

    batch_b_primary_entries = []
    for size_mb in promoted_sizes:
        if size_mb not in primary_entry_map:
            continue
        entry = analyze_switching_value_phase1_entry(
            result_root,
            primary_entry_map[size_mb],
            expected_replicates,
            threshold_pct,
        )
        batch_b_primary_entries.append(entry)
        write_switching_value_phase1_entry_artifacts(result_root, "Batch B", str(batch_b_primary_group), entry)

    batch_b_boundary_entries = []
    if run_boundary_group:
        for size_mb in promoted_sizes:
            if size_mb not in boundary_entry_map:
                continue
            entry = analyze_switching_value_phase1_entry(
                result_root,
                boundary_entry_map[size_mb],
                expected_replicates,
                threshold_pct,
            )
            batch_b_boundary_entries.append(entry)
            write_switching_value_phase1_entry_artifacts(
                result_root,
                "Batch B Boundary",
                str(batch_b_boundary_group),
                entry,
            )

    primary_by_size = {
        int(entry["size_mb"]): entry
        for entry in batch_b_primary_entries
        if isinstance(entry.get("size_mb"), int)
    }
    boundary_by_size = {
        int(entry["size_mb"]): entry
        for entry in batch_b_boundary_entries
        if isinstance(entry.get("size_mb"), int)
    }

    headroom_positive_regimes = [
        f"{batch_a_group}:{entry['size_label']}"
        for entry in batch_a_entries
        if entry.get("judgment") == "headroom-positive"
    ]
    no_proven_headroom_regimes = [
        f"{batch_a_group}:{entry['size_label']}"
        for entry in batch_a_entries
        if entry.get("judgment") == "no proven headroom"
    ]
    clean_surface_only_regimes = []
    persists_on_cross_8gpu_regimes = []
    for size_mb in promoted_sizes:
        primary_entry = primary_by_size.get(size_mb)
        if primary_entry is None:
            continue
        label = primary_entry.get("size_label", f"{size_mb}m")
        if primary_entry.get("judgment") == "headroom-positive":
            persists_on_cross_8gpu_regimes.append(f"{batch_b_primary_group}:{label}")
        elif primary_entry.get("judgment") in {"no proven headroom", "candidate-alignment-unresolved"}:
            clean_surface_only_regimes.append(f"{batch_a_group}:{label}")

    payload: dict[str, Any] = {
        "run_label": manifest.get("run_label"),
        "result_root": str(result_root),
        "expected_plugin_path": manifest.get("expected_plugin_path"),
        "container_image": manifest.get("container_image", {}),
        "parameters": parameters,
        "batch_a": {
            "topology_group": batch_a_group,
            "sizes": batch_a_entries,
            "promoted_sizes": promoted_sizes,
        },
        "batch_b": {
            "primary_topology_group": batch_b_primary_group,
            "boundary_topology_group": batch_b_boundary_group,
            "run_boundary_group": run_boundary_group,
            "primary_sizes": batch_b_primary_entries,
            "boundary_sizes": batch_b_boundary_entries,
        },
        "headroom_map": {
            "headroom_positive_regimes": headroom_positive_regimes,
            "no_proven_headroom_regimes": no_proven_headroom_regimes,
            "clean_surface_only_regimes": clean_surface_only_regimes,
            "persists_on_cross_8gpu_regimes": persists_on_cross_8gpu_regimes,
        },
    }

    dump_json(Path(args.output), payload)
    dump_text(Path(args.output).with_name("headroom-map.md"), render_switching_value_phase1_markdown(payload))


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

    topology_parser = subparsers.add_parser("aggregate-topology-matrix")
    topology_parser.add_argument("--manifest", required=True)
    topology_parser.add_argument("--output", required=True)
    topology_parser.set_defaults(func=aggregate_topology_matrix)

    same_socket_parser = subparsers.add_parser("aggregate-same-socket-isolation")
    same_socket_parser.add_argument("--manifest", required=True)
    same_socket_parser.add_argument("--output", required=True)
    same_socket_parser.set_defaults(func=aggregate_same_socket_isolation)

    numa1_parser = subparsers.add_parser("aggregate-numa1-mechanism-decomposition")
    numa1_parser.add_argument("--manifest", required=True)
    numa1_parser.add_argument("--output", required=True)
    numa1_parser.set_defaults(func=aggregate_numa1_mechanism_decomposition)

    switching_value_phase1_parser = subparsers.add_parser("aggregate-switching-value-phase1")
    switching_value_phase1_parser.add_argument("--manifest", required=True)
    switching_value_phase1_parser.add_argument("--output", required=True)
    switching_value_phase1_parser.set_defaults(func=aggregate_switching_value_phase1)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
