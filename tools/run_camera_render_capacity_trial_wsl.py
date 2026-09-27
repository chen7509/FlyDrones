#!/usr/bin/env python3
"""Run one isolated no-worker camera render-capacity cell under WSL."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from flydrones.camera_phase import (  # noqa: E402
    CameraPhaseThresholds,
    CameraScheduleMode,
    camera_phase_offsets_ns,
    summarize_camera_phase,
)
from flydrones.camera_render_capacity import (  # noqa: E402
    CapacityRun,
    CapacityThresholds,
    capacity_schedule,
    score_capacity_run,
)
from flydrones.process_ownership import append_process_identity  # noqa: E402
from flydrones.px4_ulog_evidence import newest_vehicle_ulog  # noqa: E402

DEPTH_SUFFIX = "/link/camera_link/sensor/StereoOV7251/depth_image"


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _trial_hashes(native_executable: Path) -> dict[str, str]:
    paths = {
        "runner": Path(__file__),
        "launcher": ROOT / "tools" / "launch_px4_depth_swarm_wsl.sh",
        "runtime_probe": ROOT / "tools" / "probe_gazebo_runtime_wsl.py",
        "stopper": ROOT / "tools" / "stop_px4_swarm_wsl.sh",
        "camera_scheduler": ROOT / "tools" / "run_camera_phase_scheduler_wsl.py",
        "python_observer": ROOT / "tools" / "probe_camera_phase_wsl.py",
        "camera_phase": ROOT / "src" / "flydrones" / "camera_phase.py",
        "capacity_contract": ROOT / "src" / "flydrones" / "camera_render_capacity.py",
        "process_ownership": ROOT / "src" / "flydrones" / "process_ownership.py",
        "native_executable": native_executable,
    }
    return {name: _sha256(path) if path.is_file() else "missing" for name, path in paths.items()}


def _depth_topic(vehicle_id: int, world: str = "flydrones_forest") -> str:
    return (
        f"/world/{world}/model/x500_depth_fly_{vehicle_id}"
        f"{DEPTH_SUFFIX}"
    )


def _capacity_run_directory(run: CapacityRun, output: Path) -> Path:
    identity = hashlib.sha256(str(output.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path("/tmp") / f"flydrones-capacity-{run.name}-{identity}"


def capacity_auxiliary_commands(
    *,
    run: CapacityRun,
    output: Path,
    completion_marker: Path,
    native_executable: Path,
) -> list[list[str]]:
    scheduler_ready = output / "camera-scheduler-ready.json"
    scheduler = [
        sys.executable,
        str(ROOT / "tools" / "run_camera_phase_scheduler_wsl.py"),
        "--output", str(output / "camera-scheduler.jsonl"),
        "--ready-marker", str(scheduler_ready),
        "--completion-marker", str(completion_marker),
        "--vehicle-count", "5",
        "--duration-s", "300",
        "--poll-interval-s", "0.001",
        "--flush-interval-s", "0.25",
        "--dispatch-delay-ns", "4000000",
        "--formal",
    ]
    if run.cell.implementation == "python":
        observer = [
            sys.executable,
            str(ROOT / "tools" / "probe_camera_phase_wsl.py"),
            "--output", str(output / "camera-phase.jsonl"),
            "--ready-marker", str(output / "camera-phase-ready.json"),
            "--summary", str(output / "camera-phase-summary.json"),
            "--completion-marker", str(completion_marker),
            "--mode", "phased",
            "--vehicle-count", "5",
            "--duration-s", "300",
            "--warmup-image-count-min", "11",
            "--flush-interval-s", "0.25",
            "--scheduler-ready-marker", str(scheduler_ready),
        ]
    else:
        observer = [
            str(native_executable),
            "observe",
            "--vehicle-count", "5",
            "--subscriber-count", str(run.cell.subscriber_count),
            "--output", str(output / "camera-phase.jsonl"),
            "--ready-marker", str(output / "camera-phase-selected-ready.json"),
            "--completion-marker", str(completion_marker),
            "--duration-s", "300",
            "--poll-interval-ms", "1",
            "--flush-interval-ms", "250",
            "--completion-drain-ms", "1000",
        ]
    return [scheduler, observer]


def _renderer_witness_command(
    *, output: Path, native_executable: Path
) -> list[str]:
    return [
        str(native_executable),
        "observe",
        "--vehicle-count", "5",
        "--subscriber-count", "5",
        "--output", str(output / "renderer-phase.jsonl"),
        "--ready-marker", str(output / "renderer-phase-ready.json"),
        "--completion-marker", str(output / "renderer-phase-complete.marker"),
        "--duration-s", "300",
        "--warmup-image-count-min", "11",
        "--poll-interval-ms", "1",
        "--flush-interval-ms", "250",
        "--completion-drain-ms", "1000",
    ]


def _subscriber_count(text: str) -> int:
    if re.search(r"(?im)^\s*No subscribers on topic \[[^\]\r\n]+\]\s*$", text):
        return 0
    explicit = re.search(r"(?im)^\s*Subscribers\s*:\s*(\d+)\s*$", text)
    if explicit:
        return int(explicit.group(1))
    header = re.search(r"(?im)^\s*Subscribers\b[^:]*:\s*$", text)
    if header:
        tail = text[header.end():]
        tail = re.split(r"(?im)^\s*(?:Publishers|Subscribers)\b[^:]*:\s*$", tail, maxsplit=1)[0]
        endpoints = re.findall(r"(?im)^\s*(?:tcp|ipc)://\S+", tail)
        return len(endpoints)
    raise ValueError("subscriber count is missing from gz topic info")


def _renderer_witness_accepted(
    summary: Mapping[str, object], *, exit_code: int
) -> bool:
    if exit_code not in (0, 2):
        return False
    if (
        summary.get("schema") != "flydrones-camera-phase-summary-v1"
        or summary.get("vehicle_count") != 5
    ):
        return False
    reasons = summary.get("reasons")
    allowed_reasons = {"phase_error_p95_exceeded", "spacing_median_error_exceeded"}
    if (
        not isinstance(reasons, list)
        or not all(isinstance(reason, str) for reason in reasons)
        or not set(reasons).issubset(allowed_reasons)
    ):
        return False
    for field in (
        "missed_trigger_count",
        "queue_overflow_count",
        "duplicate_trigger_count",
        "duplicate_image_count",
        "unmatched_trigger_count",
        "unmatched_image_count",
        "cross_model_error_count",
    ):
        if summary.get(field) != 0:
            return False
    vehicles = summary.get("vehicles")
    if not isinstance(vehicles, Mapping) or set(vehicles) != {str(index) for index in range(5)}:
        return False
    return all(
        isinstance(vehicle, Mapping)
        and isinstance(vehicle.get("mean_frequency_hz"), (int, float))
        and not isinstance(vehicle.get("mean_frequency_hz"), bool)
        and 9.5 <= float(vehicle["mean_frequency_hz"]) <= 10.5
        for vehicle in vehicles.values()
    )


def _native_renderer_witness_summary(
    ready_marker: Mapping[str, object],
    events: Sequence[Mapping[str, object]],
    *,
    exit_code: int,
) -> dict[str, object]:
    reasons: list[str] = []
    if (
        ready_marker.get("schema") != "flydrones-camera-phase-ready-v1"
        or ready_marker.get("vehicle_count") != 5
    ):
        reasons.append("ready_marker_invalid")
    observations = ready_marker.get("depth_observations")
    vehicles: dict[str, dict[str, object]] = {}
    if not isinstance(observations, Mapping) or set(observations) != {
        _depth_topic(vehicle) for vehicle in range(5)
    }:
        reasons.append("depth_observations_invalid")
    else:
        for vehicle in range(5):
            raw = observations.get(_depth_topic(vehicle))
            if not isinstance(raw, Mapping):
                reasons.append("depth_observations_invalid")
                continue
            vehicles[str(vehicle)] = {
                "mean_frequency_hz": raw.get("frequency_hz"),
                "width": raw.get("width"),
                "height": raw.get("height"),
                "message_count": raw.get("message_count"),
            }
    stops = [event for event in events if event.get("event") == "stop"]
    failures = [event for event in events if event.get("event") == "failure"]
    overflows = [event for event in events if event.get("event") == "queue-overflow"]
    if exit_code != 0 or len(stops) != 1:
        reasons.append("native_witness_not_clean")
    if failures:
        reasons.append("native_witness_failure")
    if overflows or (stops and stops[0].get("dropped_count") != 0):
        reasons.append("queue_overflow")
    integrity = {
        "missed_trigger_count": 0,
        "queue_overflow_count": sum(
            int(event.get("dropped_count", 1)) for event in overflows
        ),
        "duplicate_trigger_count": 0,
        "duplicate_image_count": 0,
        "unmatched_trigger_count": 0,
        "unmatched_image_count": 0,
        "cross_model_error_count": 0,
    }
    return {
        "schema": "flydrones-camera-phase-summary-v1",
        "vehicle_count": 5,
        "accepted": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "vehicles": vehicles,
        **integrity,
    }


def validate_depth_topic_connections(
    topic_info: Mapping[int, str], *, subscriber_count: int
) -> dict[str, object]:
    if subscriber_count not in (0, 1, 5):
        raise ValueError("subscriber_count must be 0, 1, or 5")
    if set(topic_info) != set(range(5)):
        raise ValueError("subscriber count evidence must contain vehicles 0..4")
    expected = {vehicle: int(vehicle < subscriber_count) for vehicle in range(5)}
    actual = {vehicle: _subscriber_count(topic_info[vehicle]) for vehicle in range(5)}
    reasons: list[str] = []
    for vehicle in range(5):
        if actual[vehicle] != expected[vehicle]:
            reasons.append(
                f"vehicle_{vehicle}_subscriber_count_{actual[vehicle]}_expected_{expected[vehicle]}"
            )
    return {
        "schema": "flydrones-depth-topic-connections-v1",
        "subscriber_count": subscriber_count,
        "expected": {str(key): value for key, value in expected.items()},
        "actual": {str(key): value for key, value in actual.items()},
        "accepted": not reasons,
        "reasons": reasons,
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    if not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            events.append({"event": "malformed-native-jsonl"})
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _scored_resource_summary(
    output: Path, *, start_monotonic_s: float, end_monotonic_s: float
) -> dict[str, object]:
    def rows(name: str) -> list[dict[str, str]]:
        path = output / name
        if not path.is_file():
            return []
        return [
            row
            for row in csv.DictReader(path.read_text(encoding="utf-8").splitlines())
            if start_monotonic_s <= float(row["monotonic_s"]) <= end_monotonic_s
        ]

    resource_rows = rows("resource-probe.csv")
    gpu_rows = rows("gpu-probe.csv")
    if resource_rows:
        first = resource_rows[0]
        last = resource_rows[-1]
        gazebo = {
            "samples": len(resource_rows),
            "pid": int(first["pid"]),
            "cpu_seconds_delta": round(
                (float(last["cpu_user_s"]) + float(last["cpu_system_s"]))
                - (float(first["cpu_user_s"]) + float(first["cpu_system_s"])),
                6,
            ),
            "rss_peak_bytes": max(int(row["rss_bytes"]) for row in resource_rows),
            "threads_peak": max(int(row["threads"]) for row in resource_rows),
        }
    else:
        gazebo = {"samples": 0}
    numeric_gpu = []
    for row in gpu_rows:
        try:
            numeric_gpu.append(
                (float(row["gpu_utilization_percent"]), float(row["memory_used_mib"]))
            )
        except (KeyError, TypeError, ValueError):
            continue
    gpu: dict[str, object] = {"samples": len(gpu_rows), "numeric_samples": len(numeric_gpu)}
    if numeric_gpu:
        gpu.update({
            "utilization_peak_percent": max(item[0] for item in numeric_gpu),
            "memory_peak_mib": max(item[1] for item in numeric_gpu),
        })
    return {
        "accepted": len(resource_rows) >= 2,
        "gazebo": gazebo,
        "gpu": gpu,
    }


def _auxiliary_closed_cleanly(
    events: Sequence[Mapping[str, object]],
    *,
    exit_code: int | None,
    implementation: str,
) -> bool:
    stops = [event for event in events if event.get("event") == "stop"]
    if exit_code != 0 or len(stops) != 1:
        return False
    stop = stops[0]
    if implementation in {"native", "native-cpp"}:
        return True
    if implementation == "python":
        return stop.get("exit_code") == 0 and stop.get("completed") is True
    if implementation == "scheduler":
        return stop.get("exit_code") == 0
    raise ValueError(f"unknown auxiliary implementation: {implementation}")


def _capacity_phase_summary(
    events: Sequence[Mapping[str, object]],
    *,
    subscriber_count: int,
    scored_window: Mapping[str, object],
    scheduler_epoch_ns: int | None,
) -> dict[str, object]:
    start_sim_ns = scored_window.get("start_sim_ns")
    end_sim_ns = scored_window.get("end_sim_ns")
    window_valid = (
        isinstance(start_sim_ns, int)
        and not isinstance(start_sim_ns, bool)
        and isinstance(end_sim_ns, int)
        and not isinstance(end_sim_ns, bool)
        and end_sim_ns > start_sim_ns
        and isinstance(scheduler_epoch_ns, int)
        and not isinstance(scheduler_epoch_ns, bool)
        and scheduler_epoch_ns >= 0
    )
    if not window_valid:
        start_sim_ns = end_sim_ns = 0
        scheduler_epoch_ns = 0
    assert isinstance(start_sim_ns, int)
    assert isinstance(end_sim_ns, int)
    assert isinstance(scheduler_epoch_ns, int)

    period_ns = CameraPhaseThresholds().period_ns
    five_camera_offsets = camera_phase_offsets_ns(5)

    def inside_scored_window(event: Mapping[str, object]) -> bool:
        if event.get("event") in {"trigger", "missed"}:
            planned = event.get("planned_sim_ns")
            return (
                isinstance(planned, int)
                and not isinstance(planned, bool)
                and start_sim_ns <= planned < end_sim_ns
            )
        if event.get("event") == "image":
            vehicle_id = event.get("vehicle_id")
            sim_ns = event.get("sim_ns")
            if (
                not isinstance(vehicle_id, int)
                or isinstance(vehicle_id, bool)
                or vehicle_id not in range(5)
                or not isinstance(sim_ns, int)
                or isinstance(sim_ns, bool)
            ):
                return False
            cycle = round(
                (sim_ns - scheduler_epoch_ns - five_camera_offsets[vehicle_id])
                / period_ns
            )
            target = scheduler_epoch_ns + cycle * period_ns + five_camera_offsets[vehicle_id]
            return start_sim_ns <= target < end_sim_ns
        return True

    if subscriber_count == 0:
        scored_events = [event for event in events if inside_scored_window(event)]
        missed_count = sum(event.get("event") == "missed" for event in scored_events)
        overflow_count = sum(
            int(event.get("dropped_count", 1))
            for event in scored_events
            if event.get("event") == "queue-overflow"
        )
        reasons = [] if window_valid else ["scored_window_invalid"]
        return {
            "schema": "flydrones-camera-phase-summary-v1",
            "mode": "phased",
            "vehicle_count": 5,
            "accepted": window_valid and missed_count == 0 and overflow_count == 0,
            "reasons": reasons,
            "vehicles": {},
            "adjacent_spacing_median_error_ns": None,
            "depth_subscription_absent": True,
            "trigger_stream_count": 5,
            "missed_trigger_count": missed_count,
            "queue_overflow_count": overflow_count,
            "duplicate_trigger_count": 0,
            "duplicate_image_count": 0,
            "unmatched_trigger_count": 0,
            "unmatched_image_count": 0,
            "cross_model_error_count": 0,
        }
    selected = set(range(subscriber_count))
    filtered: list[Mapping[str, object]] = []
    for event in events:
        name = event.get("event")
        if name in {"start", "ready"}:
            filtered.append({**event, "epoch_ns": scheduler_epoch_ns})
        elif name == "topology":
            filtered.append({
                **event,
                "depth_topics": [
                    _depth_topic(vehicle) for vehicle in range(subscriber_count)
                ],
            })
        elif name in {"image", "trigger"}:
            if event.get("vehicle_id") in selected and inside_scored_window(event):
                filtered.append(event)
        elif name == "missed":
            if inside_scored_window(event):
                filtered.append(event)
        else:
            filtered.append(event)
    phase = summarize_camera_phase(
        filtered,
        mode=CameraScheduleMode.PHASED,
        vehicle_count=subscriber_count,
        thresholds=CameraPhaseThresholds(),
    )
    phase["trigger_stream_count"] = 5
    phase["depth_subscription_absent"] = False
    spacing_by_pair = phase.get("adjacent_spacing_median_error_ns")
    if isinstance(spacing_by_pair, Mapping):
        phase["adjacent_spacing_median_error_by_pair_ns"] = dict(spacing_by_pair)
        phase["adjacent_spacing_median_error_ns"] = max(
            (int(value) for value in spacing_by_pair.values()), default=0
        )
    metadata_reasons: list[str] = []
    for vehicle_id in range(subscriber_count):
        vehicle_images = [
            event
            for event in filtered
            if event.get("event") == "image" and event.get("vehicle_id") == vehicle_id
        ]
        width = {event.get("width") for event in vehicle_images}
        height = {event.get("height") for event in vehicle_images}
        pixel_format = {event.get("format") for event in vehicle_images}
        vehicle = phase["vehicles"][str(vehicle_id)]
        vehicle["frequency_hz"] = vehicle["mean_frequency_hz"]
        if len(width) == len(height) == len(pixel_format) == 1:
            vehicle["width"] = next(iter(width))
            vehicle["height"] = next(iter(height))
            vehicle["format"] = next(iter(pixel_format))
        else:
            metadata_reasons.append("image_metadata_invalid")
    if not window_valid:
        metadata_reasons.append("scored_window_invalid")
    if metadata_reasons:
        phase["reasons"] = list(dict.fromkeys([*phase["reasons"], *metadata_reasons]))
        phase["accepted"] = False
    return phase


class SubprocessCapacityBackend:
    def __init__(self) -> None:
        self.processes: dict[str, subprocess.Popen] = {}
        self.logs: list[object] = []
        self.environment: dict[str, str] = {}
        self.output = Path()
        self.run_dir = Path()
        self.completion_marker = Path()

    def occupied_resources(self) -> list[str]:
        processes = subprocess.check_output(["ps", "-eo", "args="], text=True)
        needles = (
            "/build/px4_sitl_default/bin/px4 -i ",
            "gz sim ",
            "probe_camera_phase_wsl.py",
            "run_camera_phase_scheduler_wsl.py",
            "flydrones_camera_phase_native observe",
        )
        return [line for line in processes.splitlines() if any(item in line for item in needles)]

    def start(self, *, commands, output, run_dir, environment, completion_marker, **_kwargs):
        self.output = output
        self.run_dir = run_dir
        self.environment = environment
        self.completion_marker = completion_marker
        probe_log = (output / "runtime-probe.log").open("w", encoding="utf-8")
        self.logs.append(probe_log)
        self.processes["runtime-probe"] = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tools" / "probe_gazebo_runtime_wsl.py"),
                "--run-dir", str(run_dir),
                "--output-dir", str(output),
                "--completion-marker", str(completion_marker),
                "--duration-s", "300",
                "--ready-marker", str(output / "runtime-probe-ready.json"),
            ],
            env=environment,
            stdout=probe_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        launch_log = (output / "launch.log").open("w", encoding="utf-8")
        self.logs.append(launch_log)
        launcher = subprocess.Popen(
            ["bash", str(ROOT / "tools" / "launch_px4_depth_swarm_wsl.sh")],
            env=environment,
            stdout=launch_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes["launcher"] = launcher
        self._wait_marker(run_dir / "gazebo-base-ready.json", launcher, 60.0)
        run = _kwargs["run"]
        startup_commands = [
            ("scheduler", commands[0]),
            (
                "renderer-witness",
                _renderer_witness_command(
                    output=output,
                    native_executable=Path(_kwargs["native_executable"]),
                ),
            ),
        ]
        for role, command in startup_commands:
            handle = (output / f"{role}.log").open("w", encoding="utf-8")
            self.logs.append(handle)
            process = subprocess.Popen(
                command,
                env=environment,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.processes[role] = process
            append_process_identity(run_dir / "owned-processes.json", process.pid, role)
        _atomic_json(
            run_dir / "camera-aux-started.marker",
            {
                "schema": "flydrones-camera-aux-started-v1",
                "processes": [
                    {"role": role, "pid": self.processes[role].pid}
                    for role, _command in startup_commands
                ],
            },
        )
        attestation = self._wait_marker(
            run_dir / "renderer-attestation.json",
            launcher,
            float(_kwargs["readiness_timeout_s"]),
        )
        if attestation.get("accepted") is not True:
            raise RuntimeError("temporary renderer witness attestation rejected")
        (output / "renderer-phase-complete.marker").touch()
        witness_code = self.processes["renderer-witness"].wait(timeout=20)
        try:
            witness_ready = json.loads(
                (output / "renderer-phase-ready.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("renderer witness ready marker is missing or invalid") from exc
        witness_summary = _native_renderer_witness_summary(
            witness_ready,
            _read_jsonl(output / "renderer-phase.jsonl"),
            exit_code=witness_code,
        )
        _atomic_json(output / "renderer-phase-summary.json", witness_summary)
        if not _renderer_witness_accepted(witness_summary, exit_code=witness_code):
            raise RuntimeError(f"renderer witness exited {witness_code}")
        role = "observer"
        handle = (output / f"{role}.log").open("w", encoding="utf-8")
        self.logs.append(handle)
        process = subprocess.Popen(
            commands[1],
            env=environment,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes[role] = process
        append_process_identity(run_dir / "owned-processes.json", process.pid, role)
        selected_ready = (
            output / "camera-phase-ready.json"
            if run.cell.implementation == "python"
            else output / "camera-phase-selected-ready.json"
        )
        self._wait_marker(
            selected_ready,
            process,
            min(float(_kwargs["readiness_timeout_s"]), 90.0),
        )
        _atomic_text(
            Path(environment["FLYDRONES_CAPACITY_OBSERVER_PID_FILE"]),
            f"{process.pid}\n",
        )

    @staticmethod
    def _wait_marker(path: Path, process, timeout_s: float) -> dict[str, object]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"process exited before readiness with code {code}")
            time.sleep(0.05)
        raise TimeoutError(f"capacity readiness timed out after {timeout_s:.1f}s")

    def wait_ready(self, *, timeout_s: float, **_kwargs) -> dict[str, object]:
        run = _kwargs["run"]
        payload = self._wait_marker(
            self.run_dir / "camera-capacity-ready.json",
            self.processes["launcher"],
            timeout_s,
        )
        code = self.processes["launcher"].wait(timeout=10)
        if code != 0:
            raise RuntimeError(f"launcher exited {code}")
        self._wait_marker(
            self.output / "runtime-probe-ready.json",
            self.processes["runtime-probe"],
            min(timeout_s, 20.0),
        )
        self._wait_marker(
            self.output / "camera-scheduler-ready.json",
            self.processes["scheduler"],
            min(timeout_s, 20.0),
        )
        self._wait_marker(
            self.output
            / (
                "camera-phase-ready.json"
                if run.cell.implementation == "python"
                else "camera-phase-selected-ready.json"
            ),
            self.processes["observer"],
            min(timeout_s, 20.0),
        )
        return payload

    def capture_connections(self, *, stage: str, subscriber_count: int):
        raw: dict[int, str] = {}
        for vehicle in range(5):
            result = subprocess.run(
                ["gz", "topic", "-i", "-t", _depth_topic(vehicle)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(f"gz topic introspection failed for vehicle {vehicle}")
            raw[vehicle] = result.stdout
        evidence = validate_depth_topic_connections(raw, subscriber_count=subscriber_count)
        evidence["stage"] = stage
        evidence["raw"] = {str(key): value for key, value in raw.items()}
        _atomic_json(self.output / f"depth-topic-connections-{stage}.json", evidence)
        return raw

    def run_scored_window(self, *, duration_s: float, wall_timeout_s: float, output: Path, **_kwargs):
        clock_path = output / "clock-probe.csv"
        deadline = time.monotonic() + wall_timeout_s
        start_wall = time.monotonic()
        start_sim = None
        latest_sim = None
        while time.monotonic() < deadline:
            for role in ("observer", "scheduler", "runtime-probe"):
                code = self.processes[role].poll()
                if code is not None:
                    raise RuntimeError(f"{role} exited during scored window with code {code}")
            if clock_path.is_file():
                try:
                    rows = list(csv.DictReader(clock_path.read_text(encoding="utf-8").splitlines()))
                    if rows:
                        latest_sim = int(rows[-1]["sim_ns"])
                        if start_sim is None:
                            start_sim = latest_sim
                            start_wall = time.monotonic()
                            _atomic_json(
                                output / "scored-epoch.json",
                                {
                                    "schema": "flydrones-camera-capacity-scored-epoch-v1",
                                    "start_sim_ns": start_sim,
                                    "start_monotonic_s": start_wall,
                                    "target_sim_duration_s": duration_s,
                                    "wall_timeout_s": wall_timeout_s,
                                },
                            )
                        if latest_sim - start_sim >= int(duration_s * 1_000_000_000):
                            end_wall = time.monotonic()
                            return {
                                "start_sim_ns": start_sim,
                                "end_sim_ns": latest_sim,
                                "start_monotonic_s": start_wall,
                                "end_monotonic_s": end_wall,
                                "rtf": (latest_sim - start_sim) / 1e9 / (end_wall - start_wall),
                            }
                except (OSError, ValueError, KeyError):
                    pass
            time.sleep(0.05)
        raise TimeoutError(f"{wall_timeout_s:g} second wall timeout")

    def collect(self, **_kwargs) -> dict[str, object]:
        self.completion_marker.touch()
        exit_codes: dict[str, int | None] = {}
        for role in ("observer", "scheduler", "runtime-probe"):
            process = self.processes.get(role)
            if process is None:
                exit_codes[role] = None
                continue
            try:
                exit_codes[role] = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.terminate()
                exit_codes[role] = process.wait(timeout=5)
        launcher = self.processes.get("launcher")
        if launcher is None:
            exit_codes["launcher"] = None
        elif launcher.poll() is not None:
            exit_codes["launcher"] = launcher.returncode
        else:
            try:
                os.killpg(launcher.pid, signal.SIGTERM)
                exit_codes["launcher"] = launcher.wait(timeout=20)
            except ProcessLookupError:
                exit_codes["launcher"] = launcher.poll()
            except subprocess.TimeoutExpired:
                os.killpg(launcher.pid, signal.SIGKILL)
                exit_codes["launcher"] = launcher.wait(timeout=5)
        observer_events = _read_jsonl(self.output / "camera-phase.jsonl")
        scheduler_events = _read_jsonl(self.output / "camera-scheduler.jsonl")
        scheduler_ready_path = self.output / "camera-scheduler-ready.json"
        scheduler_epoch_ns = None
        if scheduler_ready_path.is_file():
            try:
                scheduler_epoch_ns = json.loads(
                    scheduler_ready_path.read_text(encoding="utf-8")
                ).get("epoch_ns")
            except (OSError, json.JSONDecodeError):
                scheduler_epoch_ns = None
        events = [
            event for event in observer_events if event.get("event") != "trigger-received"
        ]
        events.extend(event for event in scheduler_events if event.get("event") in {"trigger", "missed"})
        stops = [event for event in observer_events if event.get("event") == "stop"]
        native_metrics = dict(stops[0]) if len(stops) == 1 else {}
        if native_metrics.get("implementation") == "native-cpp":
            native_metrics["image_payload_bytes_seen"] = sum(
                int(event.get("image_payload_bytes_seen", 0))
                for event in observer_events
                if event.get("event") == "image"
            )
        return {
            "phase_events": events,
            "scheduler_epoch_ns": scheduler_epoch_ns,
            "observer_exit_code": exit_codes["observer"],
            "scheduler_exit_code": exit_codes["scheduler"],
            "runtime_probe_exit_code": exit_codes["runtime-probe"],
            "launcher_exit_code": exit_codes["launcher"],
            "observer_closed_cleanly": _auxiliary_closed_cleanly(
                observer_events,
                exit_code=exit_codes["observer"],
                implementation=_kwargs["run"].cell.implementation,
            ),
            "scheduler_closed_cleanly": _auxiliary_closed_cleanly(
                scheduler_events,
                exit_code=exit_codes["scheduler"],
                implementation="scheduler",
            ),
            "native_metrics": native_metrics,
            "resource_metrics": _scored_resource_summary(
                self.output,
                start_monotonic_s=float(_kwargs["scored_window"].get("start_monotonic_s", 0.0)),
                end_monotonic_s=float(_kwargs["scored_window"].get("end_monotonic_s", 0.0)),
            ),
        }

    def stop(self, **_kwargs) -> int:
        result = subprocess.run(
            ["bash", str(ROOT / "tools" / "stop_px4_swarm_wsl.sh")],
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
        (self.output / "stop.log").write_text(result.stdout, encoding="utf-8")
        for handle in self.logs:
            handle.close()
        return result.returncode

    def shared_files_restored(self, **_kwargs) -> bool:
        evidence = self.run_dir / "restoration-evidence.json"
        if not evidence.is_file():
            return False
        try:
            return json.loads(evidence.read_text(encoding="utf-8")).get("restored") is True
        except (OSError, json.JSONDecodeError):
            return False

    def cleanup_verified(self, **_kwargs) -> bool:
        evidence = self.run_dir / "cleanup-evidence.json"
        if not evidence.is_file():
            return False
        try:
            payload = json.loads(evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return not payload.get("failed_to_stop") and not payload.get("ownership_mismatch")

    def preserve_artifacts(self, **_kwargs) -> dict[str, object]:
        copied_evidence: list[str] = []
        artifact_errors: list[str] = []
        for name in (
            "renderer-attestation.json",
            "camera-capacity-ready.json",
            "cleanup-evidence.json",
            "restoration-evidence.json",
            "gazebo-base-ready.json",
            "camera-model-evidence.json",
            "camera-model-configured.sdf",
            "depth-topic-connections-launcher.json",
        ):
            source = self.run_dir / name
            if not source.is_file():
                artifact_errors.append(f"required run evidence is missing: {name}")
                continue
            shutil.copy2(source, self.output / name)
            copied_evidence.append(name)
        for name in (
            "renderer-phase.jsonl",
            "renderer-phase-ready.json",
            "renderer-phase-summary.json",
            "renderer-phase.stdout.log",
            "renderer-phase.stderr.log",
        ):
            source = self.run_dir / name
            if source.is_file():
                shutil.copy2(source, self.output / name)
                copied_evidence.append(name)
        world_source = ROOT / "results" / "px4-sitl-five-depth" / "flydrones_forest.sdf"
        if world_source.is_file():
            shutil.copy2(world_source, self.output / "world-configured.sdf")
            copied_evidence.append("world-configured.sdf")
        else:
            artifact_errors.append("configured Gazebo world is missing")
        ulog_artifacts: list[dict[str, object]] = []
        for vehicle_id in range(5):
            try:
                source = newest_vehicle_ulog(self.run_dir, vehicle_id)
                target = self.output / "px4-ulogs" / f"agent-{vehicle_id}.ulg"
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(source, target)
                ulog_artifacts.append({
                    "vehicle_id": vehicle_id,
                    "path": target.relative_to(self.output).as_posix(),
                    "bytes": target.stat().st_size,
                    "sha256": _sha256(target),
                })
            except Exception as exc:
                artifact_errors.append(f"ULog vehicle {vehicle_id}: {exc}")
        return {
            "ulog_artifacts": ulog_artifacts,
            "copied_evidence": copied_evidence,
            "artifact_errors": artifact_errors,
        }


def _validate_run(run: CapacityRun) -> None:
    expected = {item.name: item for item in capacity_schedule()}.get(run.name)
    if expected != run:
        raise ValueError("run does not belong to the frozen capacity schedule")


def run_capacity_trial(
    *,
    run: CapacityRun,
    config: Mapping[str, object],
    output_root: Path,
    native_executable: Path,
    _backend=None,
) -> dict[str, object]:
    _validate_run(run)
    duration_s = float(config.get("scored_duration_s", 0.0))
    wall_timeout_s = float(config.get("wall_timeout_s", 0.0))
    readiness_timeout_s = float(config.get("readiness_timeout_s", 45.0))
    thresholds = CapacityThresholds.from_mapping(config.get("thresholds", {}))
    if duration_s != 30.0 or wall_timeout_s != 120.0:
        raise ValueError("capacity trial requires frozen 30/120 second durations")
    if config.get("vehicle_count") != 5:
        raise ValueError("capacity trial requires five vehicles")
    backend = _backend or SubprocessCapacityBackend()
    occupied = backend.occupied_resources()
    if occupied:
        raise RuntimeError(f"PX4/Gazebo/observer resources are in use: {occupied}")
    output = output_root / run.name
    run_dir = _capacity_run_directory(run, output)
    if output.exists() or run_dir.exists():
        raise FileExistsError(f"capacity output or run directory already exists: {run.name}")
    output.mkdir(parents=True)
    _atomic_json(output / "trial-config.json", dict(config))
    completion_marker = output / "trial-complete.marker"
    commands = capacity_auxiliary_commands(
        run=run,
        output=output,
        completion_marker=completion_marker,
        native_executable=native_executable,
    )
    frozen_hashes = _trial_hashes(native_executable)
    expected_hashes = config.get("expected_hashes")
    if isinstance(expected_hashes, Mapping):
        source_hashes_match = all(
            name == "native_executable" or frozen_hashes.get(name) == value
            for name, value in expected_hashes.items()
        )
        native_executable_hash_match = (
            expected_hashes.get("native_executable") == frozen_hashes["native_executable"]
        )
    else:
        source_hashes_match = True
        native_executable_hash_match = frozen_hashes["native_executable"] != "missing"
    manifest: dict[str, object] = {
        "schema": "flydrones-camera-render-capacity-manifest-v1",
        "name": run.name,
        "cell": run.cell.name,
        "repetition": run.repetition,
        "sequence": run.sequence,
        "subscriber_count": run.cell.subscriber_count,
        "observer_implementation": run.cell.implementation,
        "worker_command_constructed": False,
        "renderer_attestation_accepted": False,
        "px4_vehicle_count": 0,
        "px4_all_healthy": False,
        "px4_all_disarmed": False,
        "px4_all_landed": False,
        "scored_duration_sim_s": 0.0,
        "scored_wall_timeout_s": wall_timeout_s,
        "depth_subscription_count_start": None,
        "depth_subscription_count_end": None,
        "trigger_stream_count": 5,
        "frozen_hashes": frozen_hashes,
        "source_hashes_match": source_hashes_match,
        "native_executable_hash_match": native_executable_hash_match,
        "observer_closed_cleanly": False,
        "scheduler_closed_cleanly": False,
        "stop_exit_code": None,
        "shared_px4_files_restored": False,
        "trial_cleanup_verified": False,
        "ulog_artifacts": [],
        "copied_evidence": [],
        "artifact_errors": [],
        "config_artifact": "trial-config.json",
        "evidence_accepted": False,
        "errors": [],
        "commands": commands,
    }
    summary: dict[str, object] = {
        "schema": "flydrones-camera-render-capacity-summary-v1",
        "runtime": {"rtf": {"scored_window": None}},
        "camera_phase": {},
        "native_metrics": {},
    }
    environment = os.environ.copy()
    environment.update({
        "FLYDRONES_PX4_RUN_DIR": str(run_dir),
        "FLYDRONES_VEHICLE_COUNT": "5",
        "FLYDRONES_GZ_RENDER_PROFILE": str(config.get("renderer_profile")),
        "FLYDRONES_CAMERA_SCHEDULE_MODE": "phased",
        "FLYDRONES_CAMERA_PHASE_READY_MARKER": str(output / "renderer-phase-ready.json"),
        "FLYDRONES_CAPACITY_MODE": "1",
        "FLYDRONES_CAPACITY_READY_MARKER": str(run_dir / "camera-capacity-ready.json"),
        "FLYDRONES_CAPACITY_OBSERVER_PID_FILE": str(output / "observer.pid"),
        "FLYDRONES_CAPACITY_SUBSCRIBER_COUNT": str(run.cell.subscriber_count),
        "FLYDRONES_CAPACITY_SCHEDULER_READY_MARKER": str(
            output / "camera-scheduler-ready.json"
        ),
        "PYTHONPATH": str(ROOT / "src"),
    })
    collected: Mapping[str, object] = {}
    readiness: Mapping[str, object] = {}
    window: Mapping[str, object] = {}
    try:
        backend.start(
            commands=commands,
            output=output,
            run_dir=run_dir,
            environment=environment,
            completion_marker=completion_marker,
            run=run,
            readiness_timeout_s=readiness_timeout_s,
            native_executable=native_executable,
        )
        observer = getattr(backend, "processes", {}).get("observer")
        if observer is not None:
            _atomic_text(output / "observer.pid", f"{observer.pid}\n")
        readiness = backend.wait_ready(timeout_s=readiness_timeout_s, run=run, output=output)
        if readiness.get("schema") != "flydrones-camera-capacity-ready-v1":
            raise RuntimeError("capacity readiness schema mismatch")
        for key in (
            "renderer_attestation_accepted",
            "px4_vehicle_count",
            "px4_all_healthy",
            "px4_all_disarmed",
            "px4_all_landed",
        ):
            manifest[key] = readiness.get(key)
        if readiness.get("renderer_attestation_accepted") is not True:
            manifest["errors"].append("renderer attestation rejected")
        if not (
            readiness.get("px4_vehicle_count") == 5
            and readiness.get("px4_all_healthy") is True
            and readiness.get("px4_all_disarmed") is True
            and readiness.get("px4_all_landed") is True
        ):
            manifest["errors"].append("PX4 health/disarmed/landed gate failed")
        start_raw = backend.capture_connections(
            stage="start", subscriber_count=run.cell.subscriber_count
        )
        start_connections = validate_depth_topic_connections(
            start_raw, subscriber_count=run.cell.subscriber_count
        )
        _atomic_json(output / "depth-topic-connections-start.json", start_connections)
        manifest["depth_subscription_count_start"] = sum(
            start_connections["actual"].values()
        )
        if not start_connections["accepted"]:
            manifest["errors"].append("depth subscriber topology rejected at start")
        if manifest["errors"]:
            raise RuntimeError("capacity readiness gates rejected")
        window = backend.run_scored_window(
            duration_s=duration_s,
            wall_timeout_s=wall_timeout_s,
            output=output,
            run=run,
        )
        if not (output / "scored-epoch.json").is_file():
            _atomic_json(
                output / "scored-epoch.json",
                {
                    "schema": "flydrones-camera-capacity-scored-epoch-v1",
                    "start_sim_ns": window["start_sim_ns"],
                    "start_monotonic_s": window["start_monotonic_s"],
                    "target_sim_duration_s": duration_s,
                    "wall_timeout_s": wall_timeout_s,
                },
            )
        manifest["scored_duration_sim_s"] = (
            int(window["end_sim_ns"]) - int(window["start_sim_ns"])
        ) / 1e9
        summary["runtime"] = {"rtf": {"scored_window": float(window["rtf"])}}
        end_raw = backend.capture_connections(
            stage="end", subscriber_count=run.cell.subscriber_count
        )
        end_connections = validate_depth_topic_connections(
            end_raw, subscriber_count=run.cell.subscriber_count
        )
        _atomic_json(output / "depth-topic-connections-end.json", end_connections)
        _atomic_json(
            output / "depth-topic-connections.json",
            {
                "schema": "flydrones-depth-topic-connection-pair-v1",
                "start": start_connections,
                "end": end_connections,
                "accepted": bool(
                    start_connections["accepted"] and end_connections["accepted"]
                ),
            },
        )
        manifest["depth_subscription_count_end"] = sum(end_connections["actual"].values())
        if not end_connections["accepted"]:
            manifest["errors"].append("depth subscriber topology rejected at end")
    except Exception as exc:
        text = str(exc)
        if text and not any(text in item for item in manifest["errors"]):
            manifest["errors"].append(f"execution: {text}")
    finally:
        completion_marker.touch()
        try:
            collected = backend.collect(run=run, output=output, scored_window=window)
        except Exception as exc:
            manifest["errors"].append(f"collection: {exc}")
            collected = {}
        manifest["observer_closed_cleanly"] = collected.get("observer_closed_cleanly") is True
        manifest["scheduler_closed_cleanly"] = collected.get("scheduler_closed_cleanly") is True
        manifest["observer_exit_code"] = collected.get("observer_exit_code")
        manifest["scheduler_exit_code"] = collected.get("scheduler_exit_code")
        manifest["runtime_probe_exit_code"] = collected.get("runtime_probe_exit_code")
        manifest["launcher_exit_code"] = collected.get("launcher_exit_code")
        summary["native_metrics"] = dict(collected.get("native_metrics") or {})
        resource_metrics = dict(collected.get("resource_metrics") or {})
        summary["runtime"]["resources"] = resource_metrics
        if resource_metrics.get("accepted") is not True:
            manifest["errors"].append("scored Gazebo resource evidence is incomplete")
        if not manifest["observer_closed_cleanly"]:
            manifest["errors"].append(
                "camera observer log lacks one complete successful stop record"
            )
        if not manifest["scheduler_closed_cleanly"]:
            manifest["errors"].append(
                "camera scheduler log lacks one complete successful stop record"
            )
        try:
            manifest["stop_exit_code"] = backend.stop(run=run, output=output, run_dir=run_dir)
            if manifest["stop_exit_code"] != 0:
                manifest["errors"].append(f"stopper exited {manifest['stop_exit_code']}")
        except Exception as exc:
            manifest["errors"].append(f"stopper failed: {exc}")
        try:
            manifest["shared_px4_files_restored"] = backend.shared_files_restored(
                run=run, run_dir=run_dir
            )
        except Exception:
            manifest["shared_px4_files_restored"] = False
        if not manifest["shared_px4_files_restored"]:
            manifest["errors"].append("shared PX4 files were not restored")
        try:
            manifest["trial_cleanup_verified"] = backend.cleanup_verified(
                run=run, run_dir=run_dir
            )
        except Exception:
            manifest["trial_cleanup_verified"] = False
        if not manifest["trial_cleanup_verified"]:
            manifest["errors"].append("owned process cleanup was not verified")
        try:
            artifacts = backend.preserve_artifacts(run=run, output=output, run_dir=run_dir)
            manifest["ulog_artifacts"] = list(artifacts.get("ulog_artifacts") or [])
            manifest["copied_evidence"] = list(artifacts.get("copied_evidence") or [])
            manifest["artifact_errors"] = list(artifacts.get("artifact_errors") or [])
            manifest["errors"].extend(manifest["artifact_errors"])
        except Exception as exc:
            manifest["errors"].append(f"artifact preservation: {exc}")
        if len(manifest["ulog_artifacts"]) != 5:
            manifest["errors"].append(
                f"PX4 ULogs incomplete: expected 5, found {len(manifest['ulog_artifacts'])}"
            )

    phase_events = collected.get("phase_events") or []
    summary["camera_phase"] = _capacity_phase_summary(
        phase_events,
        subscriber_count=run.cell.subscriber_count,
        scored_window=window,
        scheduler_epoch_ns=collected.get("scheduler_epoch_ns"),
    )
    manifest["evidence_accepted"] = not manifest["errors"]
    score = score_capacity_run(manifest, summary, thresholds)
    _atomic_json(output / "manifest.json", manifest)
    _atomic_json(output / "summary.json", summary)
    _atomic_json(output / "score.json", score)
    return {
        "manifest": manifest,
        "summary": summary,
        "score": score,
        "output": str(output),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--native-executable", type=Path, required=True)
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    run = {item.name: item for item in capacity_schedule()}.get(args.run_name)
    if run is None:
        parser.error("--run-name is not in the frozen capacity schedule")
    result = run_capacity_trial(
        run=run,
        config=config,
        output_root=args.output_root,
        native_executable=args.native_executable,
    )
    return 0 if result["score"]["performance_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
