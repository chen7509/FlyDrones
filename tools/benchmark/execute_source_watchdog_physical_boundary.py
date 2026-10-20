"""Execute one already-qualified source-watchdog physical boundary exactly once."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from tools.benchmark.audit_source_watchdog_physical_boundary import audit_boundary
from tools.benchmark.capture_contract import read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record


def _write_x(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def execute(boundary, *, resources_fn, runner=subprocess.run):
    boundary = Path(boundary).resolve(strict=True)
    value = read_declaration(boundary)
    resources_before = resources_fn()
    audit = audit_boundary(boundary, resources=resources_before)
    if audit.get("boundary_qualified") is not True or audit.get("failures") != []:
        raise ValueError("physical boundary is not qualified")
    dispatch = Path(value["dispatch"])
    completion = Path(value["completion"])
    output = Path(value["output"])
    _write_x(
        dispatch,
        {
            "schema": "source-watchdog-physical-dispatch-v1",
            "boundary": file_record(boundary),
            "boundary_audit": audit,
            "study": value["study"],
            "destination": value["destination"],
            "command": value["command"],
            "head": value["head"],
            "resources_before": resources_before,
            "single_actual_attempt": True,
            "physical_run": True,
            "started_wall_ns": time.time_ns(),
        },
    )
    command_returncode = 125
    launcher_error = None
    try:
        with output.open("xb") as stream:
            completed = runner(
                value["command"],
                cwd=Path(__file__).resolve().parents[2],
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        command_returncode = completed.returncode
    except Exception as exc:
        launcher_error = repr(exc)
    resources_after = resources_fn()
    launcher_returncode = command_returncode
    if launcher_error is not None:
        launcher_returncode = 125
    elif command_returncode == 0 and resources_after:
        launcher_returncode = 2
    _write_x(
        completion,
        {
            "schema": "source-watchdog-physical-completion-v1",
            "command_returncode": command_returncode,
            "launcher_returncode": launcher_returncode,
            "launcher_error": launcher_error,
            "destination": value["destination"],
            "destination_exists": Path(value["destination"]).exists(),
            "resources_after": resources_after,
            "physical_run": True,
            "ended_wall_ns": time.time_ns(),
        },
    )
    return launcher_returncode


def main(argv=None):
    import argparse

    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", required=True, type=Path)
    args = parser.parse_args(argv)
    return execute(args.boundary, resources_fn=active_resources)


if __name__ == "__main__":
    raise SystemExit(main())
