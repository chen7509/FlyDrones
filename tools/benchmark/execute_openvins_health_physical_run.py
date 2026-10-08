"""Execute one frozen OpenVINS health physical run exactly once."""

from __future__ import annotations

import argparse
import json
import os
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
    plan = {
        "schema": "owned-single-attempt-plan-v1",
        "profile": "openvins-health-physical",
        "study_manifest": file_record(manifest_path),
        "executor": file_record(__file__),
        "run_id": manifest["run_id"],
        "role": manifest["role"],
        "seed": manifest["seed"],
        "destination": manifest["future_destination"],
        "command": manifest["command"],
        "development_gate": gate_record,
        "outputs": {
            "capture": manifest["future_destination"],
            "dispatch": str(study / "physical-dispatch.json"),
            "completion": str(study / "physical-completion.json"),
            "output": str(study / "physical-output.txt"),
        },
        "dispatch_schema": "openvins-health-physical-dispatch-v1",
        "completion_schema": "openvins-health-physical-completion-v1",
        "fusion_eligible": False,
    }
    return _execute_once(plan, resources_fn=resources_fn, runner=runner)


def _absent_outputs(outputs):
    for path in outputs.values():
        if os.path.lexists(path):
            raise ValueError("study output already exists: " + str(path))


def prepare_live_wire_execution(manifest_path):
    """Read-only binding to this runner's record format, not an activation API.

    The public execute/main entries continue to reject live-wire manifests.
    The internal runner can be exercised with an explicitly fake runner in
    offline tests. A later separately reviewed activation entry is required.
    """
    from tools.benchmark.live_wire_study import _equal, validate_live_wire_study_files

    path = Path(manifest_path).resolve(strict=True)
    identity = file_record(path)
    manifest = validate_live_wire_study_files(path)["manifest"]
    _equal(file_record(path), identity, "manifest identity")
    outputs = {**manifest["outputs"], "output": str(path.parent / "physical-output.txt")}
    # The original study schema has no stdout role. Bind it here explicitly,
    # check resolved aliases, and refuse rather than overwrite prior evidence.
    resolved = [Path(p).resolve() for p in outputs.values()]
    for index, candidate in enumerate(resolved):
        if any(candidate == other or candidate in other.parents or other in candidate.parents
               for other in resolved[index + 1:]):
            raise ValueError("executor output paths overlap")
    _absent_outputs(outputs)
    return {
        "schema": "owned-single-attempt-plan-v1",
        "profile": "live-wire-study-offline-binding",
        "study_manifest": identity,
        "executor": file_record(__file__),
        "run_id": manifest["study_id"],
        "role": manifest["role"],
        "seed": manifest["simulation_seed"],
        "destination": manifest["outputs"]["capture"],
        "command": manifest["command"],
        "development_gate": None,
        "outputs": outputs,
        "dispatch_schema": "live-wire-study-dispatch-v1",
        "completion_schema": "live-wire-study-completion-v1",
        "live_activation_available": False,
        "fusion_eligible": False,
    }


def _execute_once(plan, *, resources_fn, runner):
    """Shared one-attempt mechanics; this private function is not authorization.

    Production health execution supplies a validated health plan. Wire tests
    supply the read-only prospective plan and a fake runner. There is no public
    wire activation entry in this package and no default subprocess runner here.
    """
    from tools.benchmark.capture_contract import _typed_equal

    _absent_outputs(plan["outputs"])
    for name in ("study_manifest", "executor"):
        if file_record(plan[name]["requested"]) != plan[name]:
            raise ValueError("executor plan input identity changed: " + name)
    if plan["profile"] == "live-wire-study-offline-binding":
        expected = prepare_live_wire_execution(plan["study_manifest"]["requested"])
        if not _typed_equal(plan, expected):
            raise ValueError("executor plan differs from validated declaration")
    resources_before = resources_fn()
    if resources_before:
        raise ValueError("competing resources present")
    _absent_outputs(plan["outputs"])
    dispatch = Path(plan["outputs"]["dispatch"])
    completion = Path(plan["outputs"]["completion"])
    output = Path(plan["outputs"]["output"])
    _write_x(
        dispatch,
        {
            "schema": plan["dispatch_schema"],
            "study_manifest": plan["study_manifest"],
            "executor": plan["executor"],
            "run_id": plan["run_id"],
            "role": plan["role"],
            "seed": plan["seed"],
            "destination": plan["destination"],
            "command": plan["command"],
            "development_gate": plan["development_gate"],
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
                plan["command"],
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
            "schema": plan["completion_schema"],
            "run_id": plan["run_id"],
            "command_returncode": command_returncode,
            "launcher_returncode": launcher_returncode,
            "launcher_error": launcher_error,
            "destination": plan["destination"],
            "destination_exists": Path(plan["destination"]).exists(),
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
