"""Execute one predeclared physical OpenVINS health fault exactly once."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from tools.benchmark.capture_contract import read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record

EXPECTED = {
    "source_loss": ("imu-source-loss-after-8s-v1", "capture_failed", 2),
    "native_restart": ("native-restart-after-8s-v1", "capture_completed", 0),
}


def _write_x(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _validate(study):
    study = Path(study).resolve(strict=True)
    manifest_path = study / "study-manifest.json"
    manifest = read_declaration(manifest_path)
    role = manifest.get("role")
    expected = EXPECTED.get(role)
    if (
        manifest.get("schema") != "openvins-health-physical-fault-preflight-v1"
        or expected is None
        or manifest.get("prepare_only") is not True
        or manifest.get("health_fault_profile") != expected[0]
        or manifest.get("expected_capture_status") != expected[1]
        or manifest.get("expected_command_returncode") != expected[2]
        or manifest.get("fault_result_viewed") is not False
        or manifest.get("test_set_tuning_allowed") is not False
        or manifest.get("fusion_eligible") is not False
        or type(manifest.get("command")) is not list
        or not manifest["command"]
        or Path(manifest.get("future_destination", "")).exists()
    ):
        raise ValueError("invalid physical fault preflight")
    return study, manifest_path, manifest


def execute(study, *, resources_fn, runner=subprocess.run):
    study, manifest_path, manifest = _validate(study)
    resources_before = resources_fn()
    if resources_before:
        raise ValueError("competing resources present")
    dispatch = study / "physical-dispatch.json"
    completion = study / "physical-completion.json"
    output = study / "physical-output.txt"
    _write_x(
        dispatch,
        {
            "schema": "openvins-health-physical-fault-dispatch-v1",
            "study_manifest": file_record(manifest_path),
            "executor": file_record(__file__),
            "run_id": manifest["run_id"],
            "role": manifest["role"],
            "seed": manifest["seed"],
            "health_fault_profile": manifest["health_fault_profile"],
            "expected_capture_status": manifest["expected_capture_status"],
            "expected_command_returncode": manifest["expected_command_returncode"],
            "destination": manifest["future_destination"],
            "command": manifest["command"],
            "resources_before": resources_before,
            "single_actual_attempt": True,
            "physical_run": True,
            "started_wall_ns": time.time_ns(),
            "fusion_eligible": False,
        },
    )
    command_returncode = 125
    launcher_error = None
    try:
        with output.open("xb") as stream:
            completed = runner(
                manifest["command"],
                cwd=Path(__file__).resolve().parents[2],
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        command_returncode = completed.returncode
    except Exception as exc:
        launcher_error = repr(exc)
    resources_after = resources_fn()
    destination = Path(manifest["future_destination"])
    capture_status = None
    try:
        capture_status = read_declaration(destination / "result.json").get("status")
    except Exception:
        pass
    matched = bool(
        launcher_error is None
        and not resources_after
        and command_returncode == manifest["expected_command_returncode"]
        and capture_status == manifest["expected_capture_status"]
    )
    _write_x(
        completion,
        {
            "schema": "openvins-health-physical-fault-completion-v1",
            "run_id": manifest["run_id"],
            "command_returncode": command_returncode,
            "launcher_error": launcher_error,
            "capture_status": capture_status,
            "expected_capture_status": manifest["expected_capture_status"],
            "expected_command_returncode": manifest["expected_command_returncode"],
            "outcome_matches_expectation": matched,
            "destination": manifest["future_destination"],
            "destination_exists": destination.exists(),
            "resources_after": resources_after,
            "physical_run": True,
            "ended_wall_ns": time.time_ns(),
            "fusion_eligible": False,
        },
    )
    return 0 if matched else 2


def main(argv=None):
    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args(argv)
    return execute(args.study, resources_fn=active_resources)


if __name__ == "__main__":
    raise SystemExit(main())
