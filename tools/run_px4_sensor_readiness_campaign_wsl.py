#!/usr/bin/env python3
"""Run isolated PX4/Gazebo sensor-readiness campaigns without camera subscribers."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from flydrones.drones.mavlink import MavlinkDrone  # noqa: E402
from flydrones.px4_sensor_readiness import (  # noqa: E402
    ReadinessRun,
    ReadinessThresholds,
    classify_readiness_campaign,
    readiness_schedule,
    score_readiness_run,
)
from flydrones.px4_ulog_evidence import newest_vehicle_ulog  # noqa: E402
from tools.run_camera_render_capacity_trial_wsl import (  # noqa: E402
    capacity_telemetry_ready,
    wait_for_capacity_telemetry,
)

DEFAULT_CONFIG = ROOT / "configs" / "px4_sensor_readiness.json"
DEFAULT_OUTPUT = ROOT / "results" / "px4-sensor-readiness"
SENSOR_TIMEOUT = re.compile(
    r"(?:Accel|Gyro|BARO|MAG|IMU|sensor)[^\n]*(?:fail|timeout)[^\n]*",
    re.IGNORECASE,
)


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_config(config: Mapping[str, object], phase: str) -> None:
    if config.get("schema") != "flydrones-px4-sensor-readiness-config-v1":
        raise ValueError("sensor-readiness config schema mismatch")
    if config.get("camera_mode") != "no-sustained-subscribers":
        raise ValueError("sensor-readiness campaign must disable sustained camera subscribers")
    if config.get("px4_build_name") != "px4_sitl_nolockstep":
        raise ValueError("sensor-readiness campaign requires px4_sitl_nolockstep")
    ReadinessThresholds.from_mapping(config.get("thresholds", {}))
    schedules = config.get("schedules")
    if not isinstance(schedules, Mapping) or schedules.get(phase) != [
        run.as_dict() for run in readiness_schedule(phase)
    ]:
        raise ValueError(f"configured readiness {phase} schedule differs from frozen schedule")


def _occupied_resources() -> list[str]:
    result = subprocess.run(
        ["ps", "-eo", "args="], text=True, stdout=subprocess.PIPE, check=True
    )
    needles = ("/build/px4_sitl_", "gz sim ", "probe_gazebo_runtime_wsl.py")
    return [line for line in result.stdout.splitlines() if any(item in line for item in needles)]


def _wait_marker(path: Path, process: subprocess.Popen, timeout_s: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.is_file():
            return _load_json(path)
        code = process.poll()
        if code is not None:
            raise RuntimeError(f"launcher exited before {path.name} with code {code}")
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {path.name}")


def _run_scored_window(
    clock_path: Path,
    probe: subprocess.Popen,
    *,
    duration_s: float,
    wall_timeout_s: float,
) -> dict[str, float | int]:
    deadline = time.monotonic() + wall_timeout_s
    start_wall = time.monotonic()
    start_sim: int | None = None
    latest_sim: int | None = None
    while time.monotonic() < deadline:
        code = probe.poll()
        if code is not None:
            raise RuntimeError(f"runtime probe exited during scored window with code {code}")
        if clock_path.is_file():
            try:
                rows = list(csv.DictReader(clock_path.read_text(encoding="utf-8").splitlines()))
                if rows:
                    latest_sim = int(rows[-1]["sim_ns"])
                    if start_sim is None:
                        start_sim = latest_sim
                        start_wall = time.monotonic()
                    if latest_sim - start_sim >= int(duration_s * 1e9):
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


def _sample_vehicle(vehicle_id: int, timeout_s: float) -> dict[str, object]:
    drone = MavlinkDrone(
        connection=f"udpin:0.0.0.0:{14540 + vehicle_id}", autopilot="px4"
    )
    try:
        drone.connect()
        telemetry = wait_for_capacity_telemetry(drone, timeout_s=timeout_s)
    finally:
        if drone.m is not None:
            drone.m.close()
    return {
        "vehicle_id": vehicle_id,
        "healthy": capacity_telemetry_ready(telemetry),
        "estimator_healthy": telemetry.estimator_healthy,
        "armed": telemetry.armed,
        "landed": telemetry.landed,
    }


def _post_window_health(vehicle_count: int, timeout_s: float) -> list[dict[str, object]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=vehicle_count) as executor:
        return list(executor.map(lambda vehicle_id: _sample_vehicle(vehicle_id, timeout_s), range(vehicle_count)))


def _resource_summary(path: Path, start: float, end: float) -> dict[str, object]:
    if not path.is_file():
        return {"accepted": False, "reason": "resource_probe_missing"}
    rows = [
        row
        for row in csv.DictReader(path.read_text(encoding="utf-8").splitlines())
        if start <= float(row["monotonic_s"]) <= end
    ]
    if not rows:
        return {"accepted": False, "reason": "resource_window_empty"}
    cpu = [float(row["cpu_user_s"]) + float(row["cpu_system_s"]) for row in rows]
    return {
        "accepted": True,
        "sample_count": len(rows),
        "gazebo_cpu_seconds_delta": max(cpu) - min(cpu),
        "gazebo_rss_bytes_max": max(int(row["rss_bytes"]) for row in rows),
        "gazebo_threads_max": max(int(row["threads"]) for row in rows),
    }


def _copy_artifacts(run_dir: Path, output: Path, vehicle_count: int) -> tuple[list[dict[str, object]], int, list[str]]:
    errors: list[str] = []
    timeout_count = 0
    evidence_names = (
        "gazebo-base-ready.json",
        "px4-capacity-platform-ready.json",
        "px4-sensor-source-warmup.json",
        "px4-sensor-topic-connections.json",
        "px4-build-evidence.json",
        "cleanup-evidence.json",
        "restoration-evidence.json",
        "gazebo.stdout.log",
        "gazebo.stderr.log",
    )
    for name in evidence_names:
        source = run_dir / name
        if source.is_file():
            shutil.copy2(source, output / name)
        else:
            errors.append(f"missing artifact: {name}")
    ulogs: list[dict[str, object]] = []
    for vehicle_id in range(vehicle_count):
        console = output / "px4-console"
        console.mkdir(exist_ok=True)
        for name in ("startup-health.json", "out.log", "err.log"):
            source = run_dir / f"instance_{vehicle_id}" / name
            target = console / f"agent-{vehicle_id}-{name}"
            if source.is_file():
                shutil.copy2(source, target)
                if name.endswith(".log"):
                    timeout_count += len(SENSOR_TIMEOUT.findall(source.read_text(encoding="utf-8", errors="replace")))
            else:
                errors.append(f"missing artifact: instance_{vehicle_id}/{name}")
        try:
            source = newest_vehicle_ulog(run_dir, vehicle_id)
            target = output / "px4-ulogs" / f"agent-{vehicle_id}.ulg"
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(source, target)
            ulogs.append({
                "vehicle_id": vehicle_id,
                "path": target.relative_to(output).as_posix(),
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            })
        except Exception as exc:
            errors.append(f"ULog vehicle {vehicle_id}: {exc}")
    return ulogs, timeout_count, errors


def _evidence_boolean(run_dir: Path, name: str, field: str) -> bool:
    path = run_dir / name
    try:
        return _load_json(path).get(field) is True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def run_trial(
    run: ReadinessRun,
    config: Mapping[str, object],
    output_root: Path,
    campaign_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    output = output_root / campaign_id / run.name
    identity = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:12]
    run_dir = Path("/tmp") / f"flydrones-readiness-{run.name}-{identity}"
    if output.exists() or run_dir.exists():
        raise FileExistsError(f"trial output already exists: {run.name}")
    output.mkdir(parents=True)
    duration_s = float(config["scored_duration_s"])
    wall_timeout_s = float(config["wall_timeout_s"])
    readiness_timeout_s = float(config["readiness_timeout_s"])
    manifest: dict[str, object] = {
        "schema": "flydrones-px4-sensor-readiness-manifest-v1",
        **run.as_dict(),
        "launcher_exit_code": None,
        "platform_ready": False,
        "initial_all_healthy": False,
        "post_window_all_healthy": False,
        "scored_duration_sim_s": 0.0,
        "scored_wall_timeout_s": wall_timeout_s,
        "sensor_timeout_count": 0,
        "trial_cleanup_verified": False,
        "shared_px4_files_restored": False,
        "ulog_artifacts": [],
        "errors": [],
    }
    summary: dict[str, object] = {
        "schema": "flydrones-px4-sensor-readiness-summary-v1",
        "runtime": {"rtf": None},
        "vehicles": {},
    }
    environment = os.environ.copy()
    environment.update({
        "FLYDRONES_PX4_RUN_DIR": str(run_dir),
        "FLYDRONES_VEHICLE_COUNT": str(run.vehicle_count),
        "FLYDRONES_GZ_RENDER_PROFILE": str(config["renderer_profile"]),
        "FLYDRONES_CAMERA_SCHEDULE_MODE": "phased",
        "FLYDRONES_CAPACITY_MODE": "1",
        "FLYDRONES_PLATFORM_READINESS_ONLY": "1",
        "FLYDRONES_CAPACITY_SUBSCRIBER_COUNT": "0",
        "PX4_BUILD_NAME": str(config["px4_build_name"]),
        "FLYDRONES_EXPECTED_PX4_REVISION": str(config["px4_revision"]),
        "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}",
    })
    completion = output / "probe-complete.marker"
    probe_log = (output / "runtime-probe.log").open("w", encoding="utf-8")
    launch_log = (output / "launch.log").open("w", encoding="utf-8")
    probe: subprocess.Popen | None = None
    launcher: subprocess.Popen | None = None
    window: dict[str, float | int] = {}
    try:
        if _occupied_resources():
            raise RuntimeError("PX4/Gazebo resources are already in use")
        probe = subprocess.Popen(
            [sys.executable, str(ROOT / "tools/probe_gazebo_runtime_wsl.py"),
             "--run-dir", str(run_dir), "--output-dir", str(output),
             "--completion-marker", str(completion), "--duration-s", "300"],
            env=environment, stdout=probe_log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        launcher = subprocess.Popen(
            ["bash", str(ROOT / "tools/launch_px4_depth_swarm_wsl.sh")],
            env=environment, stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        platform = _wait_marker(
            run_dir / "px4-capacity-platform-ready.json", launcher, readiness_timeout_s
        )
        manifest["platform_ready"] = (
            platform.get("schema") == "flydrones-px4-capacity-platform-ready-v1"
            and platform.get("vehicle_count") == run.vehicle_count
            and platform.get("px4_all_healthy") is True
        )
        code = launcher.wait(timeout=15)
        manifest["launcher_exit_code"] = code
        initial: dict[str, dict[str, object]] = {}
        for vehicle_id in range(run.vehicle_count):
            payload = _load_json(run_dir / f"instance_{vehicle_id}" / "startup-health.json")
            initial[str(vehicle_id)] = payload
        manifest["initial_all_healthy"] = all(
            item.get("estimator_healthy") is True
            and item.get("armed") is False
            and item.get("landed") is True
            for item in initial.values()
        )
        window = _run_scored_window(
            output / "clock-probe.csv", probe,
            duration_s=duration_s, wall_timeout_s=wall_timeout_s,
        )
        manifest["scored_duration_sim_s"] = (
            int(window["end_sim_ns"]) - int(window["start_sim_ns"])
        ) / 1e9
        summary["runtime"] = {
            "rtf": float(window["rtf"]),
            "resources": _resource_summary(
                output / "resource-probe.csv",
                float(window["start_monotonic_s"]),
                float(window["end_monotonic_s"]),
            ),
        }
        post = _post_window_health(run.vehicle_count, timeout_s=30.0)
        manifest["post_window_all_healthy"] = all(item["healthy"] is True for item in post)
        summary["vehicles"] = {
            str(vehicle_id): {
                "initial_healthy": (
                    initial[str(vehicle_id)].get("estimator_healthy") is True
                    and initial[str(vehicle_id)].get("armed") is False
                    and initial[str(vehicle_id)].get("landed") is True
                ),
                "post_window_healthy": post[vehicle_id]["healthy"],
                "initial": initial[str(vehicle_id)],
                "post_window": post[vehicle_id],
            }
            for vehicle_id in range(run.vehicle_count)
        }
    except Exception as exc:
        manifest["errors"].append(f"execution: {exc}")
        if launcher is not None and manifest["launcher_exit_code"] is None:
            try:
                manifest["launcher_exit_code"] = launcher.wait(timeout=1)
            except subprocess.TimeoutExpired:
                manifest["launcher_exit_code"] = None
    finally:
        completion.touch()
        if probe is not None:
            try:
                probe.wait(timeout=15)
            except subprocess.TimeoutExpired:
                probe.terminate()
                probe.wait(timeout=5)
        stop = subprocess.run(
            ["bash", str(ROOT / "tools/stop_px4_swarm_wsl.sh")],
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=45, check=False,
        )
        (output / "stop.log").write_text(stop.stdout, encoding="utf-8")
        manifest["trial_cleanup_verified"] = _evidence_boolean(
            run_dir, "cleanup-evidence.json", "accepted"
        ) or (
            _evidence_boolean(run_dir, "cleanup-evidence.json", "failed_to_stop") is False
            and (run_dir / "cleanup-evidence.json").is_file()
            and not _load_json(run_dir / "cleanup-evidence.json").get("failed_to_stop")
            and not _load_json(run_dir / "cleanup-evidence.json").get("ownership_mismatch")
        )
        manifest["shared_px4_files_restored"] = _evidence_boolean(
            run_dir, "restoration-evidence.json", "restored"
        )
        ulogs, timeout_count, errors = _copy_artifacts(
            run_dir, output, run.vehicle_count
        )
        manifest["ulog_artifacts"] = ulogs
        manifest["sensor_timeout_count"] = timeout_count
        manifest["errors"].extend(errors)
        probe_log.close()
        launch_log.close()
    thresholds = ReadinessThresholds.from_mapping(config["thresholds"])
    score = score_readiness_run(manifest, summary, thresholds)
    _atomic_json(output / "manifest.json", manifest)
    _atomic_json(output / "summary.json", summary)
    _atomic_json(output / "score.json", score)
    return manifest, summary


def execute_campaign(
    *, config_path: Path, output_root: Path, campaign_id: str, phase: str
) -> dict[str, object]:
    if not campaign_id or not campaign_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("campaign_id contains invalid characters")
    config = _load_json(config_path)
    _validate_config(config, phase)
    revision = subprocess.check_output(
        ["git", "-C", str(Path.home() / "PX4-Autopilot"), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != config["px4_revision"]:
        raise RuntimeError("current PX4 revision differs from frozen config")
    campaign_dir = output_root / campaign_id
    if campaign_dir.exists():
        raise FileExistsError(f"campaign output already exists: {campaign_dir}")
    campaign_dir.mkdir(parents=True)
    _atomic_json(campaign_dir / "campaign-config.json", config)
    pairs: list[tuple[dict[str, object], dict[str, object]]] = []
    for run in readiness_schedule(phase):
        manifest, summary = run_trial(run, config, output_root, campaign_id)
        pairs.append((manifest, summary))
        if _occupied_resources():
            raise RuntimeError(f"owned resources remain after {run.name}")
    result = classify_readiness_campaign(pairs, config, phase=phase)
    _atomic_json(campaign_dir / "campaign-summary.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--phase", choices=("development", "formal"), required=True)
    args = parser.parse_args()
    result = execute_campaign(
        config_path=args.config,
        output_root=args.output_root,
        campaign_id=args.campaign_id,
        phase=args.phase,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["classification"] in {"development_pass", "stable_sensor_readiness"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
