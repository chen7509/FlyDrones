"""Conservative terminal audit for a full-load runtime-mapping capture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SELF_PHASES = ("postimports", "postfinalize", "postfirststep")
OWNED_PHASES = {"px4": ("ready", "prestop"), "openvins": ("ready", "prestop")}


def _read_object(path: Path, failures: list[str], label: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        failures.append(f"{label}:unreadable:{type(exc).__name__}")
        return None
    if not isinstance(value, dict):
        failures.append(f"{label}:not_object")
        return None
    return value


def _require(condition: bool, failures: list[str], code: str) -> None:
    if not condition:
        failures.append(code)


def _audit_map(path: Path, failures: list[str], *, role: str | None, phase: str) -> None:
    row = _read_object(path, failures, f"runtime_map:{path.name}")
    if row is None:
        return
    if role is not None:
        _require(row.get("role") == role, failures, f"runtime_map:{role}:{phase}:role")
    _require(row.get("phase") == phase, failures, f"runtime_map:{role or 'self'}:{phase}:phase")
    _require(row.get("observed_files_covered") is True, failures,
             f"runtime_map:{role or 'self'}:{phase}:coverage")
    for key in ("unknown", "mismatched"):
        _require(row.get(key) == [], failures, f"runtime_map:{role or 'self'}:{phase}:{key}")
    error_key = "error" if role is not None else "parse_error"
    _require(row.get(error_key) is None, failures,
             f"runtime_map:{role or 'self'}:{phase}:{error_key}")


def _audit_ulog(capture: Path, failures: list[str]) -> None:
    manifest = _read_object(capture / "px4-ulog-manifest.json", failures, "ulog_manifest")
    if manifest is None:
        return
    _require(manifest.get("schema") == "flydrones-px4-ulog-capture-v1", failures,
             "ulog_manifest:schema")
    logs = manifest.get("logs")
    if not isinstance(logs, list) or not logs:
        failures.append("ulog_manifest:logs")
        return
    for index, entry in enumerate(logs):
        if not isinstance(entry, dict):
            failures.append(f"ulog:{index}:not_object")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            failures.append(f"ulog:{index}:path")
            continue
        log_path = capture / relative
        try:
            data = log_path.read_bytes()
        except OSError as exc:
            failures.append(f"ulog:{index}:unreadable:{type(exc).__name__}")
            continue
        _require(entry.get("valid_header") is True, failures, f"ulog:{index}:header")
        _require(entry.get("bytes") == len(data), failures, f"ulog:{index}:bytes")
        _require(entry.get("sha256") == hashlib.sha256(data).hexdigest(), failures,
                 f"ulog:{index}:sha256")


def audit_capture(capture: Path, supervisor_path: Path) -> dict[str, Any]:
    """Audit terminal evidence without promoting it to VIO or fusion qualification."""
    capture = Path(capture)
    supervisor_path = Path(supervisor_path)
    failures: list[str] = []

    result = _read_object(capture / "result.json", failures, "result")
    binding: dict[str, Any] = {}
    if result is not None:
        _require(result.get("status") == "capture_completed", failures, "result:status")
        _require(result.get("errors") == [], failures, "result:errors")
        end_sim_ns = result.get("end_sim_ns")
        _require(isinstance(end_sim_ns, int) and not isinstance(end_sim_ns, bool)
                 and end_sim_ns >= 25_000_000_000, failures, "result:duration")
        _require(result.get("px4_exit_code") == 0, failures, "result:px4_exit")
        candidate = result.get("runtime_binding")
        if isinstance(candidate, dict):
            binding = candidate
        else:
            failures.append("result:runtime_binding")

    if binding:
        for key in ("pre_recorded", "declared_files_stable", "local_file_graph_verified",
                    "runtime_mapping_coverage_verified"):
            _require(binding.get(key) is True, failures, f"binding:{key}")
        _require(binding.get("errors") == [], failures, "binding:errors")
        _require(binding.get("runtime_closure_qualified") is False, failures,
                 "binding:runtime_closure_must_remain_false")
        phases = binding.get("phases")
        phase_order_valid = False
        if isinstance(phases, list):
            try:
                positions = [phases.index(phase) for phase in SELF_PHASES]
            except ValueError:
                positions = []
            phase_order_valid = len(positions) == len(SELF_PHASES) and positions == sorted(positions)
        _require(phase_order_valid, failures, "binding:self_phases")
        _require(binding.get("owned_phases") == {key: list(value) for key, value in OWNED_PHASES.items()},
                 failures, "binding:owned_phases")

    for phase in SELF_PHASES:
        _audit_map(capture / f"runtime-maps-{phase}.json", failures, role=None, phase=phase)
    for role, phases in OWNED_PHASES.items():
        for phase in phases:
            _audit_map(capture / f"runtime-maps-{role}-{phase}.json", failures,
                       role=role, phase=phase)

    pre = _read_object(capture / "runtime-binding-pre.json", failures, "binding_pre")
    post = _read_object(capture / "runtime-binding-post.json", failures, "binding_post")
    if pre is not None and post is not None:
        _require(pre.get("files") == post.get("files"), failures, "binding:files_drift")

    supervisor = _read_object(supervisor_path, failures, "supervisor")
    if supervisor is not None:
        _require(supervisor.get("status") == "worker_exited", failures, "supervisor:status")
        _require(supervisor.get("worker_exit") == 0, failures, "supervisor:worker_exit")
        _require(supervisor.get("capture_status") == "capture_completed", failures,
                 "supervisor:capture_status")
        _require(supervisor.get("errors") == [], failures, "supervisor:errors")
        cleanup = supervisor.get("cleanup")
        if not isinstance(cleanup, dict):
            failures.append("supervisor:cleanup")
        else:
            for key in ("graceful_group_cleanup_verified", "no_executing_members", "group_absent"):
                _require(cleanup.get(key) is True, failures, f"supervisor:cleanup:{key}")
            _require(cleanup.get("sigkill_dispatched") is False, failures,
                     "supervisor:cleanup:sigkill")

    _audit_ulog(capture, failures)
    failures = list(dict.fromkeys(failures))
    return {
        "schema": "full-load-runtime-mapping-audit-v1",
        "capture": str(capture),
        "supervisor": str(supervisor_path),
        "failures": failures,
        "runtime_mapping_coverage_verified": not failures,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("supervisor", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    audit = audit_capture(args.capture, args.supervisor)
    output = args.output or args.capture / "full-load-runtime-mapping-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return 0 if audit["runtime_mapping_coverage_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
