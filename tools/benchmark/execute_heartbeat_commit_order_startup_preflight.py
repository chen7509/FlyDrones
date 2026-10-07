"""Execute one exact-head startup-only preflight for a qualified study-v20."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from tools.benchmark.audit_heartbeat_commit_order_retry_preflight import audit as audit_package
from tools.benchmark.capture_contract import _typed_equal, read_declaration
from tools.benchmark.capture_disarmed_sensors import active_resources


def _exclusive_json(path, value):
    encoded = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with Path(path).open("x", encoding="utf-8") as stream:
        if stream.write(encoded) != len(encoded):
            raise OSError("short exclusive write")
        stream.flush()


def execute(
    *,
    study,
    prepare_audit,
    expected_head,
    observed_head,
    dispatch,
    completion,
    output,
    resources_fn=active_resources,
    runner=subprocess.run,
):
    study = Path(study).resolve(strict=True)
    destination = study / "startup-preflight-v1"
    dispatch = Path(dispatch).resolve()
    completion = Path(completion).resolve()
    output = Path(output).resolve()
    expected_head = str(expected_head).strip().lower()
    observed_head = str(observed_head).strip().lower()
    if len(expected_head) != 40 or any(char not in "0123456789abcdef" for char in expected_head):
        raise ValueError("invalid expected head")
    if observed_head != expected_head:
        raise ValueError("committed head")
    existing = [
        path
        for path in (
            destination,
            destination.with_name(destination.name + ".supervisor-environment.json"),
            destination.with_name(destination.name + ".supervisor-events.jsonl"),
            dispatch,
            completion,
            output,
        )
        if path.exists()
    ]
    if existing:
        raise FileExistsError("one-shot output exists: " + ", ".join(map(str, existing)))
    saved_audit = read_declaration(prepare_audit)
    live_audit = audit_package(study)
    if (
        saved_audit.get("schema") != "heartbeat-commit-order-retry-audit-v1"
        or saved_audit.get("failures") != []
        or saved_audit.get("prepare_qualified") is not True
        or not _typed_equal(saved_audit, live_audit)
    ):
        raise ValueError("prepare-only audit")
    manifest = read_declaration(study / "study-manifest.json")
    command = manifest.get("command")
    if (
        manifest.get("schema") != "heartbeat-commit-order-retry-preflight-v1"
        or manifest.get("prepare_only") is not True
        or not isinstance(command, list)
        or "--output" not in command
        or "--startup-preflight" in command
        or manifest.get("future_destination") != str((study / "capture-v1").resolve())
    ):
        raise ValueError("prepare-only manifest")
    resources_before = resources_fn()
    if resources_before:
        raise ValueError("competing resources")
    startup_command = list(command)
    startup_command[startup_command.index("--output") + 1] = str(destination)
    startup_command.append("--startup-preflight")
    _exclusive_json(
        dispatch,
        {
            "schema": "capture-startup-preflight-dispatch-v1",
            "command": startup_command,
            "destination": str(destination),
            "head": expected_head,
            "prepare_audit": str(Path(prepare_audit).resolve(strict=True)),
            "resources_before": resources_before,
            "physical_run": False,
            "started_wall_ns": time.time_ns(),
        },
    )
    returncode = None
    launcher_error = None
    try:
        with output.open("xb") as stream:
            finished = runner(startup_command, cwd=study.parents[3], stdout=stream, stderr=subprocess.STDOUT, check=False)
        returncode = finished.returncode
    except Exception as exc:
        launcher_error = repr(exc)
    resources_after = resources_fn()
    _exclusive_json(
        completion,
        {
            "schema": "capture-startup-preflight-completion-v1",
            "returncode": returncode,
            "launcher_error": launcher_error,
            "destination": str(destination),
            "destination_exists": destination.exists(),
            "resources_after": resources_after,
            "physical_run": False,
            "ended_wall_ns": time.time_ns(),
        },
    )
    return returncode if launcher_error is None and returncode is not None else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--prepare-audit", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--observed-head", required=True)
    parser.add_argument("--dispatch", required=True, type=Path)
    parser.add_argument("--completion", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    return execute(**vars(args))


if __name__ == "__main__":
    raise SystemExit(main())
