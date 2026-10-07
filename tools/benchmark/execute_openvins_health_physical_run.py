"""Execute one frozen OpenVINS health physical run exactly once."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from tools.benchmark.capture_contract import read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record


def _write_x(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _validate(study, development_gate):
    study = Path(study).resolve(strict=True)
    manifest_path = study / "study-manifest.json"
    manifest = read_declaration(manifest_path)
    required = {
        "schema", "prepare_only", "run_id", "role", "seed", "future_destination", "command",
        "held_out_results_viewed", "test_set_tuning_allowed", "fusion_eligible",
    }
    if (
        manifest.get("schema") != "openvins-health-physical-run-preflight-v1"
        or not required <= set(manifest)
        or manifest["prepare_only"] is not True
        or manifest["role"] not in {"development", "held_out"}
        or manifest["held_out_results_viewed"] is not False
        or manifest["test_set_tuning_allowed"] is not False
        or manifest["fusion_eligible"] is not False
        or type(manifest["command"]) is not list
        or not manifest["command"]
        or Path(manifest["future_destination"]).exists()
    ):
        raise ValueError("invalid physical run preflight")
    gate_record = None
    if manifest["role"] == "held_out":
        if development_gate is None:
            raise ValueError("held-out run requires qualified development gate")
        gate_path = Path(development_gate).resolve(strict=True)
        gate = read_declaration(gate_path)
        if (
            gate.get("schema") != "openvins-health-development-gate-v1"
            or gate.get("development_qualified") is not True
            or gate.get("profile_frozen_before_held_out") is not True
            or gate.get("fusion_eligible") is not False
        ):
            raise ValueError("held-out run requires qualified development gate")
        gate_record = file_record(gate_path)
    elif development_gate is not None:
        raise ValueError("development run must precede development gate")
    return study, manifest_path, manifest, gate_record


def execute(study, *, resources_fn, runner=subprocess.run, development_gate=None):
    study, manifest_path, manifest, gate_record = _validate(study, development_gate)
    resources_before = resources_fn()
    if resources_before:
        raise ValueError("competing resources present")
    dispatch = study / "physical-dispatch.json"
    completion = study / "physical-completion.json"
    output = study / "physical-output.txt"
    _write_x(
        dispatch,
        {
            "schema": "openvins-health-physical-dispatch-v1",
            "study_manifest": file_record(manifest_path),
            "executor": file_record(__file__),
            "run_id": manifest["run_id"],
            "role": manifest["role"],
            "seed": manifest["seed"],
            "destination": manifest["future_destination"],
            "command": manifest["command"],
            "development_gate": gate_record,
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
    launcher_returncode = 125 if launcher_error is not None else command_returncode
    if launcher_error is None and command_returncode == 0 and resources_after:
        launcher_returncode = 2
    _write_x(
        completion,
        {
            "schema": "openvins-health-physical-completion-v1",
            "run_id": manifest["run_id"],
            "command_returncode": command_returncode,
            "launcher_returncode": launcher_returncode,
            "launcher_error": launcher_error,
            "destination": manifest["future_destination"],
            "destination_exists": Path(manifest["future_destination"]).exists(),
            "resources_after": resources_after,
            "physical_run": True,
            "ended_wall_ns": time.time_ns(),
            "fusion_eligible": False,
        },
    )
    return launcher_returncode


def main(argv=None):
    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--development-gate", type=Path)
    args = parser.parse_args(argv)
    return execute(args.study, resources_fn=active_resources, development_gate=args.development_gate)


if __name__ == "__main__":
    raise SystemExit(main())
