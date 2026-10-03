"""One fixed single-aircraft PX4/Gazebo magnetic-heading development probe."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.clock import require_offboard  # noqa: E402
from flydrones.benchmark.gateway import NativeGazeboPx4Backend  # noqa: E402
from flydrones.benchmark.ulog_capture import (  # noqa: E402
    collect_ulogs,
    ulog_evidence_failures,
    verify_episode_ulog_evidence,
)
from tools.benchmark.audit_ekf2_shadow import (  # noqa: E402
    ARCHIVE_SHA256,
    _digest,
    _digest_file,
    _read_index,
    _verified_members,
    write_report_once,
)

PX4_COMMIT = "d6f12ad1c4f70ad3230afd7d86e971421e02fef4"
PX4_BINARY_SHA256 = "e8af7cbcac255ec3c79bb5fa278459fd0b130b4b189de9269e3689cb9789f4cb"
VEHICLE_IMU_SHA256 = "a73997eaf14a5c1b224dcb4f13648874a02863d63608c60b73d8d3dc01a983a1"
PX4_BASE_MODEL_SHA256 = "e807dca3406f7cd5cb3d545898601c3ec17e0e5242e25cf467a69df1812cf436"
PX4_X500_MODEL_SHA256 = "cfe92f98360967faa895b77aa8a6fff3fc9b290286e94e45297c4bdd7b62fbf9"
CAMERA_MODEL_SHA256 = "806c532bd2a22e9caa85d79bf5fd974d7ce02b1eb660df7802c1fc557f4ae5fe"
BENCHMARK_MODEL_SHA256 = "ff8eaa1dbb73b77d693e1d29908bc0ebee6ffa64311951e133db38fda82e7ee9"
MODEL_TREE_SHA256 = {
    "px4_x500": "d19a9008f8b79868334dd82ae90126a685dcd500f1fc77632cd488cc2b0db30d",
    "px4_x500_base": "b28b948a881f9a8ef57e8aaaa0c6f33ca5eb0ffe8fcc7e7b0d027ce8840e0c8e",
    "benchmark": "28a5e56e48b2d86dfd33621650b15ef4c5092484d0142f5610c8b7a100d95aa1",
    "camera": "5f261ae971e92aa06a3bdf7c1808c31a02e427d824cad3e1e877d00b75e2de34",
}
EXPECTED_PX4_DIRTY_STATUS = {
    " M Tools/simulation/flightgear/flightgear_bridge",
    " M Tools/simulation/gz",
    " M src/modules/sensors/vehicle_imu/VehicleIMU.cpp",
}
TAKEOFF_ALT_M = 2.1
TAKEOFF_TIMEOUT_S = 90.
DT_S = .05
HOVER_STEPS = 80
MAX_WALL_S = 900
INPUT_NAMES = ("world.json", "world.sdf", "ground_albedo.png", "obstacle_albedo.png")


def _validate_paired_altitude(takeoff_alt_m: float) -> None:
    if type(takeoff_alt_m) is not float or takeoff_alt_m not in (1.26, 2.1):
        raise ValueError("paired altitude must be 1.26 or 2.1 m")


def prepare_probe_inputs(archive: Path, index_path: Path, output: Path,
                         *, takeoff_alt_m: float = TAKEOFF_ALT_M) -> dict:
    """Copy only byte-verified historical development world inputs once."""
    _validate_paired_altitude(takeoff_alt_m)
    archive, index_path, output = Path(archive), Path(index_path), Path(output)
    if output.exists():
        raise FileExistsError(output)
    archive_sha = _digest_file(archive)
    if archive_sha != ARCHIVE_SHA256:
        raise ValueError("archive SHA mismatch")
    index = _read_index(index_path, archive_sha)
    members = _verified_members(archive, index)
    inputs = {}
    for name in INPUT_NAMES:
        raw = members.get("episode-v1/" + name)
        if raw is None:
            raise ValueError(f"missing historical fixture {name}")
        inputs[name] = raw
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in inputs.items():
        (output / name).write_bytes(raw)
    manifest = {
        "schema": "flydrones-ekf2-heading-probe-input-v1",
        "archive_sha256": archive_sha,
        "index_sha256": _digest_file(index_path),
        "inputs": {name: {"sha256": _digest(raw), "bytes": len(raw)}
                   for name, raw in inputs.items()},
        "takeoff_alt_m": takeoff_alt_m,
        "takeoff_timeout_s": TAKEOFF_TIMEOUT_S,
        "hover_steps": HOVER_STEPS,
        "step_s": DT_S,
        "formal_benchmark": False,
    }
    write_report_once(output / "probe-input-manifest.json", manifest)
    return manifest


def _sample_record(sample) -> dict:
    clearance = float(sample.clearance_m)
    return {
        "sim_ns": int(sample.sim_ns),
        "position_gazebo_truth_for_scoring_only_m": list(sample.position),
        "clearance_m": clearance if math.isfinite(clearance) else None,
        "contact": bool(sample.contact),
        "in_bounds": bool(sample.in_bounds),
    }


def _append_progress(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _tree_digest(directory: Path) -> str:
    """Hash names and bytes of all files, including included model meshes."""
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"model directory unavailable: {directory}")
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"model tree contains symlink: {path}")
        if path.is_file():
            files.append((path.relative_to(directory).as_posix(), _digest_file(path)))
    if not files:
        raise ValueError(f"model directory empty: {directory}")
    return _digest(json.dumps(files, separators=(",", ":")).encode("utf-8"))


def _owned_pid_matches(record: dict) -> bool:
    """Require the recorded command, process group and launch time to agree."""
    try:
        pid = record["pid"]
        if type(pid) is not int or pid <= 1 or os.getpgid(pid) != pid:
            return False
        args = [part.decode() for part in (Path(f"/proc/{pid}/cmdline").read_bytes()
                                          .rstrip(b"\0").split(b"\0"))]
        if args != record["args"]:
            return False
        stat = Path(f"/proc/{pid}/stat").read_text()
        start_ticks = int(stat[stat.rfind(")") + 2:].split()[19])
        boot_time = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                         if line.startswith("btime "))
        started_wall_s = boot_time + start_ticks / os.sysconf("SC_CLK_TCK")
        return abs(started_wall_s - float(record["started_wall_s"])) <= 10.
    except (OSError, KeyError, ValueError, IndexError, TypeError, UnicodeDecodeError):
        return False


def _cleanup_owned_processes(output: Path) -> dict:
    """Stop only PX4 processes whose /proc identity matches our PID manifest."""
    manifest = Path(output) / "processes.json"
    if not manifest.is_file():
        return {"terminated": [], "still_running": [], "unverified": []}
    try:
        records = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"terminated": [], "still_running": [], "unverified": [repr(exc)]}
    if not isinstance(records, list):
        return {"terminated": [], "still_running": [], "unverified": ["manifest_not_list"]}
    terminated, unverified = [], []
    for record in records:
        if not isinstance(record, dict) or type(record.get("pid")) is not int:
            unverified.append("invalid_process_record")
            continue
        if not _owned_pid_matches(record):
            if Path(f"/proc/{record['pid']}").exists():
                unverified.append(f"{record['pid']}: live PID identity differs from manifest")
            continue
        pid = record["pid"]
        try:
            os.killpg(pid, signal.SIGTERM)
            terminated.append(pid)
        except ProcessLookupError:
            pass
        except OSError as exc:
            unverified.append(f"{pid}: {exc!r}")
    deadline = time.monotonic() + 5.
    while time.monotonic() < deadline:
        if not any(_owned_pid_matches(record) for record in records if isinstance(record, dict)):
            break
        time.sleep(.1)
    still_running = []
    for record in records:
        if isinstance(record, dict) and _owned_pid_matches(record):
            pid = record["pid"]
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError as exc:
                unverified.append(f"{pid}: {exc!r}")
            if _owned_pid_matches(record):
                still_running.append(pid)
    return {"terminated": terminated, "still_running": still_running,
            "unverified": unverified}


def _recover_ulog(output: Path) -> dict:
    """After process release, retain a raw ULog left before normal close."""
    output = Path(output)
    manifest = output / "px4-ulog-manifest.json"
    manifest_error = None
    if manifest.is_file():
        try:
            return {"status": "already_captured",
                    "logs": json.loads(manifest.read_text(encoding="utf-8"))["logs"]}
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            manifest_error = repr(exc)
    runtime_manifest = output / "px4-runtime.json"
    if not runtime_manifest.is_file():
        return {"status": "runtime_missing"}
    try:
        runtime = Path(json.loads(runtime_manifest.read_text(encoding="utf-8"))["runtime"]).resolve()
        allowed = (Path.home() / "fly-ego-benchmark/runtime").resolve()
        if not runtime.is_relative_to(allowed) or runtime == allowed:
            raise ValueError("PX4 runtime outside development root")
        if manifest_error is None:
            try:
                logs = collect_ulogs(runtime, output)
                return {"status": "recovered" if logs else "raw_ulog_missing",
                        "runtime": str(runtime), "logs": logs}
            except FileExistsError as exc:
                manifest_error = repr(exc)
        # An interrupted copy or manifest write may already occupy the normal
        # destination. Preserve those bytes and copy the flushed runtime log
        # under a separate, non-overwriting failure-evidence directory.
        recovery_output = output / "ulog-recovery"
        if recovery_output.exists():
            raise FileExistsError(recovery_output)
        logs = collect_ulogs(runtime, recovery_output)
        return {"status": "recovered_separately" if logs else "raw_ulog_missing",
                "runtime": str(runtime), "recovery_output": str(recovery_output),
                "original_error": manifest_error, "logs": logs}
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"status": "recovery_error", "error": repr(exc),
                "runtime_manifest": str(runtime_manifest)}


def run_probe(output: Path, *, backend_factory=NativeGazeboPx4Backend,
              px4_provenance: dict | None = None,
              takeoff_alt_m: float = TAKEOFF_ALT_M) -> dict:
    """Run only neutral PX4 velocity targets, retaining failures and ULog."""
    _validate_paired_altitude(takeoff_alt_m)
    output = Path(output)
    result_path = output / "probe-result.json"
    if result_path.exists():
        raise FileExistsError(result_path)
    progress_path = output / "probe-progress.ndjson"
    if progress_path.exists():
        raise FileExistsError(progress_path)
    with progress_path.open("x", encoding="utf-8"):
        pass
    world = json.loads((output / "world.json").read_text(encoding="utf-8"))
    result = {
        "schema": "flydrones-ekf2-heading-probe-v1",
        "status": "infrastructure_error",
        "failure": None,
        "steps_requested": HOVER_STEPS,
        "steps_completed": 0,
        "takeoff_alt_m": takeoff_alt_m,
        "takeoff_timeout_s": TAKEOFF_TIMEOUT_S,
        "step_s": DT_S,
        "samples": [],
        "command_attempts": [],
        "control_records": [],
        "offboard_evidence": [],
        "ulog_evidence": [],
        "ulog_capture_error": None,
        "px4_runtime": None,
        "cleanup": None,
        "ulog_recovery": None,
        "log_files": [],
        "progress_sha256": None,
        "progress_line_count": 0,
        "px4_provenance": px4_provenance,
        "formal_benchmark": False,
        "eligible_for_live_capture": False,
    }
    backend = None
    try:
        working_world = output / "working-world.sdf"
        if working_world.exists():
            raise FileExistsError(working_world)
        working_world.write_bytes((output / "world.sdf").read_bytes())
        backend = backend_factory(ROOT, output, world, takeoff_alt_m=takeoff_alt_m,
                                  takeoff_timeout_s=TAKEOFF_TIMEOUT_S)
        backend.start(working_world)
        for step in range(HOVER_STEPS):
            attempt = {"step": step + 1, "local_ned": [0., 0., 0., 0.],
                       "dt_s": DT_S, "completed": False}
            result["command_attempts"].append(attempt)
            _append_progress(progress_path, {"kind": "command_attempt", **attempt})
            backend.advance((0., 0., 0., 0.), DT_S)
            attempt["completed"] = True
            sample = _sample_record(backend.score_sample())
            _append_progress(progress_path, {"kind": "sample", "step": step + 1, **sample})
            result["samples"].append(sample)
            result["steps_completed"] += 1
            if sample["contact"] or (sample["clearance_m"] is not None
                                     and sample["clearance_m"] <= 0):
                result["status"] = "collision"
                break
            if not sample["in_bounds"]:
                result["status"] = "out_of_bounds"
                break
        else:
            result["status"] = "diagnostic_complete"
    except Exception as exc:
        result["failure"] = repr(exc)
        result["status"] = "infrastructure_error"
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception as exc:
                result["failure"] = (result["failure"] or "") + f" close: {exc!r}"
                result["status"] = "infrastructure_error"
            result["cleanup"] = _cleanup_owned_processes(output)
            if result["cleanup"]["still_running"] or result["cleanup"]["unverified"]:
                result["status"] = "infrastructure_error"
                result["failure"] = (result["failure"] or "") + " process cleanup incomplete"
            if (not backend.ulog_evidence and not result["cleanup"]["still_running"]
                    and not result["cleanup"]["unverified"]):
                result["ulog_recovery"] = _recover_ulog(output)
                if result["ulog_recovery"].get("status") == "recovered":
                    backend.ulog_evidence = result["ulog_recovery"]["logs"]
            result["ulog_evidence"] = backend.ulog_evidence
            result["ulog_capture_error"] = backend.ulog_capture_error
            result["control_records"] = backend.control_records
            result["offboard_evidence"] = backend.offboard_evidence
            runtime = getattr(backend, "runtime_path", None)
            result["px4_runtime"] = str(runtime) if runtime is not None else None
            result["log_files"] = [
                {"path": name, "sha256": _digest_file(output / name)}
                for name in ("px4.log", "processes.json") if (output / name).is_file()
            ]
            ulog_failures = ulog_evidence_failures(
                backend.ulog_evidence, backend.ulog_capture_error)
            if ulog_failures:
                result["status"] = "infrastructure_error"
                result["failure"] = (result["failure"] or "") + " ULog " + ",".join(ulog_failures)
            if result["status"] == "diagnostic_complete" and not backend.offboard_evidence:
                result["status"] = "infrastructure_error"
                result["failure"] = (result["failure"] or "") + " OFFBOARD evidence missing"
        result["progress_sha256"] = _digest_file(progress_path)
        result["progress_line_count"] = progress_path.read_bytes().count(b"\n")
        write_report_once(result_path, result)
    return result


def _px4_provenance() -> dict:
    checkout = Path.home() / "PX4-Autopilot"
    commit = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if commit != PX4_COMMIT:
        raise ValueError(f"PX4 checkout changed: {commit}")
    binary = checkout / "build/px4_sitl_default/bin/px4"
    imu_source = checkout / "src/modules/sensors/vehicle_imu/VehicleIMU.cpp"
    status = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    if set(status) != EXPECTED_PX4_DIRTY_STATUS:
        raise ValueError("PX4 working tree differs from pinned development variant")
    inputs = {
        "binary_sha256": (binary, PX4_BINARY_SHA256),
        "vehicle_imu_source_sha256": (imu_source, VEHICLE_IMU_SHA256),
        "px4_base_model_sha256": (
            checkout / "Tools/simulation/gz/models/x500_base/model.sdf", PX4_BASE_MODEL_SHA256),
        "px4_x500_model_sha256": (
            checkout / "Tools/simulation/gz/models/x500/model.sdf", PX4_X500_MODEL_SHA256),
        "camera_model_sha256": (
            ROOT / "assets/gazebo/models/OakD-Benchmark/model.sdf", CAMERA_MODEL_SHA256),
        "benchmark_model_sha256": (
            ROOT / "assets/gazebo/models/x500_benchmark/model.sdf", BENCHMARK_MODEL_SHA256),
    }
    actual = {name: _digest_file(path) for name, (path, _) in inputs.items()}
    for name, (_, expected) in inputs.items():
        if actual[name] != expected:
            raise ValueError(f"PX4 {name} changed from pinned development variant")
    model_roots = {
        "px4_x500": checkout / "Tools/simulation/gz/models/x500",
        "px4_x500_base": checkout / "Tools/simulation/gz/models/x500_base",
        "benchmark": ROOT / "assets/gazebo/models/x500_benchmark",
        "camera": ROOT / "assets/gazebo/models/OakD-Benchmark",
    }
    model_trees = {name: _tree_digest(path) for name, path in model_roots.items()}
    if model_trees != MODEL_TREE_SHA256:
        raise ValueError("PX4 included model tree changed from pinned development variant")
    return {"commit": commit, **actual, "model_tree_sha256": model_trees,
            "working_tree_status": status,
            "historical_binary_identity_unproven": True}


def _stop_worker(worker) -> list[str]:
    errors = []
    if worker.returncode is not None:
        return errors
    try:
        os.killpg(worker.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        errors.append(repr(exc))
    try:
        worker.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            errors.append(repr(exc))
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            errors.append("worker still running after SIGKILL")
    return errors


def validate_probe_progress(output: Path, worker_result: dict | None) -> dict:
    """Require a complete, durable OFFBOARD trajectory before declaring success."""
    path = Path(output) / "probe-progress.ndjson"
    try:
        if not isinstance(worker_result, dict) or not path.is_file():
            raise ValueError("worker result or durable progress missing")
        raw = path.read_bytes()
        events = [json.loads(line) for line in raw.splitlines()]
        if (not raw.endswith(b"\n") or len(events) != 2 * HOVER_STEPS
                or worker_result.get("progress_sha256") != _digest(raw)
                or worker_result.get("progress_line_count") != len(events)
                or worker_result.get("steps_completed") != HOVER_STEPS):
            raise ValueError("durable progress count or hash differs from worker result")
        attempts = worker_result.get("command_attempts")
        samples = worker_result.get("samples")
        controls = worker_result.get("control_records")
        if (not isinstance(attempts, list) or len(attempts) != HOVER_STEPS
                or not isinstance(samples, list) or len(samples) != HOVER_STEPS
                or not isinstance(controls, list) or len(controls) != HOVER_STEPS + 1):
            raise ValueError("incomplete command, sample or physics record")
        previous_sim_ns = None
        for index, (attempt, sample, control) in enumerate(
                zip(attempts, samples, controls[1:], strict=True), 1):
            if (not isinstance(attempt, dict) or attempt.get("step") != index
                    or attempt.get("local_ned") != [0., 0., 0., 0.]
                    or attempt.get("dt_s") != DT_S
                    or attempt.get("completed") is not True
                    or events[2 * index - 2] != {
                        "kind": "command_attempt", **{**attempt, "completed": False}}):
                raise ValueError(f"command {index} missing or changed")
            if (not isinstance(sample, dict) or events[2 * index - 1] != {
                    "kind": "sample", "step": index, **sample}
                    or type(sample.get("sim_ns")) is not int
                    or sample.get("contact") is not False
                    or sample.get("in_bounds") is not True
                    or type(sample.get("clearance_m")) not in (int, float)
                    or not math.isfinite(sample["clearance_m"])
                    or sample["clearance_m"] <= 0):
                raise ValueError(f"sample {index} missing, unsafe or changed")
            sim_ns = sample["sim_ns"]
            if (not isinstance(control, dict)
                    or control.get("method") != "gz.sim8.Server.run"
                    or control.get("return_value") is not True
                    or control.get("steps") != round(DT_S / .001)
                    or control.get("sim_ns_after_run") != sim_ns
                    or control.get("sim_ns_before") != sim_ns - round(DT_S * 1e9)
                    or (previous_sim_ns is not None and
                        sim_ns != previous_sim_ns + round(DT_S * 1e9))):
                raise ValueError(f"physics step {index} missing or changed")
            previous_sim_ns = sim_ns
        offboard = worker_result.get("offboard_evidence")
        if not isinstance(offboard, list) or not offboard:
            raise ValueError("OFFBOARD evidence missing")
        last_heartbeat_ns = -1
        for record in offboard:
            if (not isinstance(record, dict) or type(record.get("sim_ns")) is not int
                    or type(record.get("custom_mode")) is not int
                    or type(record.get("base_mode")) is not int):
                raise ValueError("OFFBOARD heartbeat invalid")
            require_offboard(record["custom_mode"], record["base_mode"])
            last_heartbeat_ns = max(last_heartbeat_ns, record["sim_ns"])
        if not previous_sim_ns - 1_000_000_000 <= last_heartbeat_ns <= previous_sim_ns:
            raise ValueError("OFFBOARD heartbeat stale or in the future")
        return {"status": "verified", "steps": HOVER_STEPS}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError,
            json.JSONDecodeError) as exc:
        return {"status": "invalid", "reason": repr(exc)}


def supervise_probe(archive: Path, index_path: Path, output: Path,
                    *, timeout_s: int = MAX_WALL_S,
                    takeoff_alt_m: float = TAKEOFF_ALT_M) -> dict:
    """Bound blocking Gazebo calls; verify evidence and release owned processes."""
    _validate_paired_altitude(takeoff_alt_m)
    archive, index_path, output = Path(archive), Path(index_path), Path(output)
    if output.exists():
        raise FileExistsError(output)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker",
               "--archive", str(archive), "--index", str(index_path),
               "--output", str(output), "--takeoff-alt-m", str(takeoff_alt_m)]
    worker = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    timed_out = False
    interrupted = None
    stdout = stderr = ""
    try:
        stdout, stderr = worker.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
    except BaseException as exc:
        interrupted = repr(exc)
    finally:
        stop_errors = _stop_worker(worker)
        try:
            cleanup = _cleanup_owned_processes(output)
        except Exception as exc:
            cleanup = {"terminated": [], "still_running": [],
                       "unverified": [f"cleanup exception: {exc!r}"]}

    recovery = (_recover_ulog(output) if not cleanup["still_running"]
                and not cleanup["unverified"] else {"status": "process_release_unverified"})
    worker_result_path = output / "probe-result.json"
    try:
        worker_result = (json.loads(worker_result_path.read_text(encoding="utf-8"))
                         if worker_result_path.is_file() else None)
    except (OSError, json.JSONDecodeError):
        worker_result = None
    records = (worker_result.get("ulog_evidence") if isinstance(worker_result, dict)
               else recovery.get("logs"))
    try:
        verify_episode_ulog_evidence(
            output, {"px4_ulogs": records, "px4_ulog_capture_accepted": True})
        ulog_validation = {"status": "verified"}
    except (OSError, KeyError, ValueError, TypeError) as exc:
        ulog_validation = {"status": "invalid", "reason": repr(exc)}
    progress_validation = validate_probe_progress(output, worker_result)

    if timed_out:
        status = "supervisor_timeout"
    elif interrupted is not None:
        status = "supervisor_interrupted"
    elif stop_errors or cleanup["still_running"] or cleanup["unverified"] or cleanup["terminated"]:
        status = "supervisor_cleanup_failed"
    elif worker.returncode != 0 or not isinstance(worker_result, dict) or (
            worker_result.get("status") != "diagnostic_complete"):
        status = "worker_failed"
    elif (recovery["status"] != "already_captured"
          or ulog_validation["status"] != "verified"
          or progress_validation["status"] != "verified"):
        status = "evidence_invalid"
    else:
        status = "diagnostic_complete"

    progress_path = output / "probe-progress.ndjson"
    progress_bytes = progress_path.read_bytes() if progress_path.is_file() else b""
    durable_samples = 0
    for line in progress_bytes.splitlines():
        try:
            durable_samples += json.loads(line).get("kind") == "sample"
        except (ValueError, AttributeError):
            pass
    completed_steps = (worker_result.get("steps_completed")
                       if isinstance(worker_result, dict)
                       and type(worker_result.get("steps_completed")) is int
                       else durable_samples)
    result = {
        "schema": "flydrones-ekf2-heading-probe-supervisor-v1",
        "status": status,
        "timeout_s": timeout_s,
        "worker_exit_code": worker.returncode,
        "worker_stdout_tail": stdout[-4000:],
        "worker_stderr_tail": stderr[-4000:],
        "interrupted": interrupted,
        "stop_errors": stop_errors,
        "cleanup": cleanup,
        "ulog_recovery": recovery,
        "ulog_validation": ulog_validation,
        "progress_validation": progress_validation,
        "probe_result_status": worker_result.get("status") if isinstance(worker_result, dict) else None,
        "progress_sha256": _digest(progress_bytes) if progress_path.is_file() else None,
        "progress_line_count": progress_bytes.count(b"\n"),
        "durable_sample_count": durable_samples,
        "completed_steps": completed_steps,
        "trajectory_incomplete": completed_steps < HOVER_STEPS,
        "eligible_for_live_capture": False,
    }
    write_report_once(output / "supervisor-result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--takeoff-alt-m", type=float, choices=(1.26, 2.1),
                        default=TAKEOFF_ALT_M)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.worker:
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def interrupt_on_sigterm(signum, frame):
            raise KeyboardInterrupt(f"signal {signum}")

        signal.signal(signal.SIGTERM, interrupt_on_sigterm)
        try:
            result = supervise_probe(args.archive, args.index, args.output,
                                     takeoff_alt_m=args.takeoff_alt_m)
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
        print(json.dumps({"status": result["status"],
                          "output": str(args.output)}, sort_keys=True))
        return 0 if result["status"] == "diagnostic_complete" else 1
    provenance = _px4_provenance()
    prepare_probe_inputs(args.archive, args.index, args.output,
                         takeoff_alt_m=args.takeoff_alt_m)
    result = run_probe(args.output, px4_provenance=provenance,
                       takeoff_alt_m=args.takeoff_alt_m)
    print(json.dumps({"status": result["status"],
                      "steps_completed": result["steps_completed"],
                      "output": str(args.output)}, sort_keys=True))
    return 0 if result["status"] == "diagnostic_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
