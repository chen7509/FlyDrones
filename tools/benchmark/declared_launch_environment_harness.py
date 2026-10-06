#!/usr/bin/env python3
"""Bounded non-physical harness for exact supervisor-to-worker environment transport."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools.benchmark.audit_declared_launch_environment import audit_environment  # noqa: E402
from tools.benchmark.capture_contract import validate_launch_environment  # noqa: E402
from tools.benchmark.capture_disarmed_sensors import record_worker_environment  # noqa: E402
from tools.benchmark.declared_runtime_snapshot import write_manifest  # noqa: E402
from tools.benchmark.disarmed_sensor_provenance import supervise_worker  # noqa: E402


def harness_contract(home):
    environment = validate_launch_environment({
        "HOME": str(home),
        "HTTP_PROXY": None,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "LD_PRELOAD": None,
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": None,
        "SDF_PATH": "",
    })
    return {
        "schema": "capture-execution-v2",
        "launch_environment": environment,
        "harness": "absolute-python-child-v1",
        "wall_budget_s": 20,
        "environment_transport_verified": False,
        "physical_environment_qualified": False,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def child_command(output, contract, python):
    script = Path(__file__).resolve(strict=True)
    python = Path(python)
    if not python.is_absolute() or not python.is_file():
        raise ValueError("absolute harness Python executable required")
    return [str(python), str(script), "--child", "--output", str(Path(output).resolve()),
            "--contract", str(Path(contract).resolve())]


def run_child(output, contract_path, *, reader=None):
    contract_path = Path(contract_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    record_worker_environment(output, contract, contract_path, reader=reader)
    result = {
        "status": "capture_completed",
        "errors": [],
        "estimator_run": False,
        "environment_transport_verified": False,
        "physical_environment_qualified": False,
        "runtime_mapping_coverage_verified": False,
        "runtime_closure_qualified": False,
        "vio_accuracy_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    write_manifest(Path(output) / "result.json", result)
    return 0


def run_parent(study_root, python):
    study_root = Path(study_root)
    study_root.mkdir(parents=True, exist_ok=False)
    contract_path = study_root / "execution-contract.json"
    contract = harness_contract(Path.home())
    write_manifest(contract_path, contract)
    hostile = {"PYTHONPATH": "hostile-parent", "HTTP_PROXY": "hostile-proxy",
               "LD_PRELOAD": "/not/a/real/library.so"}
    os.environ.update(hostile)
    write_manifest(study_root / "parent-hostile-environment.json", {
        "schema": "hostile-parent-environment-v1",
        "values": hostile,
        "inherited_by_worker": False,
        "physical_environment_qualified": False,
    })
    capture = study_root / "capture-v1"
    command = child_command(capture, contract_path, python)
    summary = supervise_worker(
        command, capture, timeout_s=contract["wall_budget_s"],
        launch_environment=contract["launch_environment"], execution_contract=contract_path,
    )
    audit = audit_environment(
        contract_path,
        capture.with_name(capture.name + ".supervisor-environment.json"),
        capture / "execution-environment-worker.json",
        capture / "supervisor.json",
    )
    write_manifest(study_root / "audit.json", audit)
    print(json.dumps({"command": command, "supervisor": summary, "audit": audit}, indent=2))
    return 0 if audit["environment_transport_verified"] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--python", default="/usr/bin/python3")
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        if args.contract is None:
            parser.error("child requires --contract")
        return run_child(args.output, args.contract)
    if args.contract is not None:
        parser.error("parent creates its own prospective contract")
    return run_parent(args.output, args.python)


if __name__ == "__main__":
    raise SystemExit(main())
