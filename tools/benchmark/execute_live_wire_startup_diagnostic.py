"""Bind a read-only PX4 startup observer to one separately selected wire study.

The diagnostic declaration is not an authorization or qualification record.
The existing wire executor still owns resource checks, capture and completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath

from tools.benchmark.execute_openvins_health_physical_run import (
    execute_live_wire,
    prepare_live_wire_execution,
)
from tools.benchmark.live_wire_startup_runner import run_observed_capture

_SCHEMA = "flydrones-live-wire-startup-diagnostic-declaration-v1"
_DEADLINE_NS = 60_000_000_000
_READY_TIMEOUT_S = 5
_FIELDS = {
    "schema", "study_id", "study_manifest_sha256", "observer_source_sha256",
    "runner_source_sha256", "observer_deadline_ns", "ready_timeout_s",
    "log_path", "observation_path", "summary_path", "qualification_granted",
}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_selected_declaration(path: Path, selected_sha256: str) -> dict:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 16_384:
        raise ValueError("startup diagnostic declaration file invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        raw = source.read(16_385)
    after = path.lstat()
    if (len(raw) > 16_384 or len(raw) != opened.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)):
        raise ValueError("startup diagnostic declaration file changed")
    if hashlib.sha256(raw).hexdigest() != selected_sha256:
        raise ValueError("startup diagnostic declaration drift")
    return json.loads(raw, object_pairs_hook=_unique_object)


def validate_diagnostic(declaration: dict, plan: dict, observer_sha: str, runner_sha: str) -> dict:
    """Validate an exact diagnostic companion; no filesystem or process I/O."""
    if type(declaration) is not dict or set(declaration) != _FIELDS:
        raise ValueError("startup diagnostic schema invalid")
    if (declaration["schema"] != _SCHEMA
            or declaration["study_id"] != plan["run_id"]
            or declaration["study_manifest_sha256"] != plan["study_manifest"]["sha256"]
            or declaration["observer_source_sha256"] != observer_sha
            or declaration["runner_source_sha256"] != runner_sha
            or any(type(value) is not str or _SHA.fullmatch(value) is None for value in (
                declaration["study_manifest_sha256"], observer_sha, runner_sha))
            or type(declaration["observer_deadline_ns"]) is not int
            or declaration["observer_deadline_ns"] != _DEADLINE_NS
            or type(declaration["ready_timeout_s"]) is not int
            or declaration["ready_timeout_s"] != _READY_TIMEOUT_S
            or declaration["qualification_granted"] is not False):
        raise ValueError("startup diagnostic identity or limit invalid")
    destination = PurePosixPath(plan["destination"])
    if not destination.is_absolute() or ".." in destination.parts:
        raise ValueError("startup diagnostic capture path invalid")
    expected = {
        "log_path": str(destination / "px4.log"),
        "observation_path": str(destination.parent / "startup-observation.json"),
        "summary_path": str(destination.parent / "startup-summary.json"),
    }
    if any(declaration[key] != value for key, value in expected.items()):
        raise ValueError("startup diagnostic output path invalid")
    return declaration


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("startup diagnostic duplicate JSON key")
        result[key] = value
    return result


def execute_diagnostic(
    study_manifest: Path,
    diagnostic_path: Path,
    *,
    selected_study_sha256: str,
    selected_diagnostic_sha256: str,
    resources_fn,
    runner=subprocess.run,
) -> int:
    """Execute one owned study while retaining an independent startup timeline."""
    diagnostic_path = Path(diagnostic_path)
    if type(selected_diagnostic_sha256) is not str or _SHA.fullmatch(selected_diagnostic_sha256) is None:
        raise ValueError("startup diagnostic selected digest invalid")
    declaration = _read_selected_declaration(diagnostic_path, selected_diagnostic_sha256)
    plan = prepare_live_wire_execution(study_manifest)
    observer_source = Path(__file__).with_name("observe_px4_startup.py")
    runner_source = Path(__file__).with_name("live_wire_startup_runner.py")
    validate_diagnostic(declaration, plan, _sha(observer_source), _sha(runner_source))
    if selected_study_sha256 != plan["study_manifest"]["sha256"]:
        raise ValueError("startup diagnostic selected study differs")
    for key in ("observation_path", "summary_path"):
        if os.path.lexists(declaration[key]):
            raise ValueError("startup diagnostic output already exists: " + key)

    def observed_runner(command, **kwargs):
        return run_observed_capture(
            command,
            log_path=Path(declaration["log_path"]),
            observation_path=Path(declaration["observation_path"]),
            summary_path=Path(declaration["summary_path"]),
            observer_deadline_ns=_DEADLINE_NS,
            ready_timeout_s=_READY_TIMEOUT_S,
            runner=runner,
            study_manifest_sha256=selected_study_sha256,
            diagnostic_declaration_sha256=selected_diagnostic_sha256,
            **kwargs,
        )

    return execute_live_wire(
        study_manifest,
        approved_manifest_sha256=selected_study_sha256,
        resources_fn=resources_fn,
        runner=observed_runner,
    )


def main(argv=None) -> int:
    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--selected-study-sha256", required=True)
    parser.add_argument("--selected-diagnostic-sha256", required=True)
    args = parser.parse_args(argv)
    return execute_diagnostic(
        args.study, args.diagnostic,
        selected_study_sha256=args.selected_study_sha256,
        selected_diagnostic_sha256=args.selected_diagnostic_sha256,
        resources_fn=active_resources,
    )


if __name__ == "__main__":
    raise SystemExit(main())
