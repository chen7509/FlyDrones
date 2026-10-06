"""Audit exact supervisor-to-worker launch-environment transport."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.benchmark.capture_contract import (
    _typed_equal,
    materialize_launch_environment,
    read_declaration,
    validate_launch_environment,
)


def _read(path: Path, failures: list[str], label: str) -> dict[str, Any] | None:
    try:
        value = read_declaration(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        failures.append(f"{label}:unreadable:{type(exc).__name__}")
        return None
    if type(value) is not dict:
        failures.append(f"{label}:not_object")
        return None
    return value


def _require(value: bool, failures: list[str], code: str) -> None:
    if not value:
        failures.append(code)


def _contract_record(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    payload = path.read_bytes()
    return {"path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def audit_environment(contract_path: Path, supervisor_environment_path: Path,
                      worker_environment_path: Path, supervisor_path: Path) -> dict[str, Any]:
    paths = [Path(value) for value in (
        contract_path, supervisor_environment_path, worker_environment_path, supervisor_path,
    )]
    failures: list[str] = []
    contract = _read(paths[0], failures, "contract")
    declared = materialized = None
    record = None
    if contract is not None:
        _require(contract.get("schema") == "capture-execution-v2", failures, "contract:schema")
        try:
            declared = validate_launch_environment(contract.get("launch_environment"))
            materialized = materialize_launch_environment(declared)
            record = _contract_record(paths[0])
        except (OSError, UnicodeError, ValueError) as exc:
            failures.append(f"contract:environment:{type(exc).__name__}")

    supervisor_environment = _read(paths[1], failures, "supervisor_environment")
    if supervisor_environment is not None and declared is not None:
        _require(supervisor_environment.get("schema") == "supervisor-launch-environment-v1", failures,
                 "supervisor_environment:schema")
        _require(_typed_equal(supervisor_environment.get("declared"), declared), failures,
                 "supervisor_environment:declared")
        _require(_typed_equal(supervisor_environment.get("materialized"), materialized), failures,
                 "supervisor_environment:materialized")
        _require(_typed_equal(supervisor_environment.get("execution_contract"), record), failures,
                 "supervisor_environment:contract")
        _require(supervisor_environment.get("ambient_inherited") is False, failures,
                 "supervisor_environment:ambient")
        for key in ("runtime_environment_qualified", "physics_qualified", "fusion_eligible"):
            _require(supervisor_environment.get(key) is False, failures,
                     f"supervisor_environment:{key}")

    worker_environment = _read(paths[2], failures, "worker_environment")
    if worker_environment is not None and declared is not None:
        _require(worker_environment.get("schema") == "worker-launch-environment-v1", failures,
                 "worker_environment:schema")
        _require(_typed_equal(worker_environment.get("declared"), declared), failures,
                 "worker_environment:declared")
        _require(_typed_equal(worker_environment.get("materialized"), materialized), failures,
                 "worker_environment:materialized")
        _require(_typed_equal(worker_environment.get("observed"), materialized), failures,
                 "worker_environment:observed")
        _require(worker_environment.get("matches") is True, failures, "worker_environment:matches")
        _require(_typed_equal(worker_environment.get("execution_contract"), record), failures,
                 "worker_environment:contract")
        for key in ("runtime_environment_qualified", "physics_qualified", "fusion_eligible"):
            _require(worker_environment.get(key) is False, failures, f"worker_environment:{key}")

    supervisor = _read(paths[3], failures, "supervisor")
    if supervisor is not None:
        _require(supervisor.get("status") == "worker_exited", failures, "supervisor:status")
        _require(supervisor.get("worker_exit") == 0, failures, "supervisor:worker_exit")
        _require(supervisor.get("capture_status") == "capture_completed", failures,
                 "supervisor:capture_status")
        _require(supervisor.get("errors") == [], failures, "supervisor:errors")
        cleanup = supervisor.get("cleanup")
        if type(cleanup) is not dict:
            failures.append("supervisor:cleanup")
        else:
            for key in ("graceful_group_cleanup_verified", "no_executing_members", "group_absent"):
                _require(cleanup.get(key) is True, failures, f"supervisor:cleanup:{key}")
            _require(cleanup.get("sigkill_dispatched") is False, failures, "supervisor:cleanup:sigkill")

    failures = list(dict.fromkeys(failures))
    return {
        "schema": "declared-launch-environment-audit-v1",
        "contract": str(paths[0]),
        "supervisor_environment": str(paths[1]),
        "worker_environment": str(paths[2]),
        "supervisor": str(paths[3]),
        "failures": failures,
        "environment_transport_verified": not failures,
        "physical_environment_qualified": False,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("supervisor_environment", type=Path)
    parser.add_argument("worker_environment", type=Path)
    parser.add_argument("supervisor", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    audit = audit_environment(
        args.contract, args.supervisor_environment, args.worker_environment, args.supervisor,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        payload = json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if stream.write(payload) != len(payload):
            raise OSError("short launch environment audit write")
        stream.flush()
    return 0 if audit["environment_transport_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
