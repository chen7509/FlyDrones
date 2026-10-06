import hashlib
import json

import pytest

from tools.benchmark.audit_declared_launch_environment import audit_environment


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(tmp_path):
    environment = {"HOME": "/home/test", "PYTHONPATH": None, "SDF_PATH": ""}
    materialized = {"HOME": "/home/test", "SDF_PATH": ""}
    contract = tmp_path / "execution.json"
    write(contract, {"schema": "capture-execution-v2", "launch_environment": environment})
    digest = hashlib.sha256(contract.read_bytes()).hexdigest()
    contract_record = {"path": str(contract.resolve()), "bytes": contract.stat().st_size, "sha256": digest}
    supervisor_environment = tmp_path / "capture.supervisor-environment.json"
    write(supervisor_environment, {
        "schema": "supervisor-launch-environment-v1", "declared": environment,
        "materialized": materialized, "execution_contract": contract_record,
        "ambient_inherited": False, "runtime_environment_qualified": False,
        "physics_qualified": False, "fusion_eligible": False,
    })
    capture = tmp_path / "capture"
    capture.mkdir()
    worker_environment = capture / "execution-environment-worker.json"
    write(worker_environment, {
        "schema": "worker-launch-environment-v1", "declared": environment,
        "materialized": materialized, "observed": materialized, "matches": True,
        "execution_contract": contract_record, "runtime_environment_qualified": False,
        "physics_qualified": False, "fusion_eligible": False,
    })
    supervisor = capture / "supervisor.json"
    write(supervisor, {
        "status": "worker_exited", "worker_exit": 0, "capture_status": "capture_completed", "errors": [],
        "cleanup": {"graceful_group_cleanup_verified": True, "no_executing_members": True,
                    "group_absent": True, "sigkill_dispatched": False},
    })
    return contract, supervisor_environment, worker_environment, supervisor


def test_exact_transport_qualifies_only_environment_mechanism(tmp_path):
    paths = fixture(tmp_path)
    audit = audit_environment(*paths)
    assert audit["environment_transport_verified"] is True
    assert audit["physical_environment_qualified"] is False
    assert audit["vio_accuracy_qualified"] is False
    assert audit["fusion_eligible"] is False


@pytest.mark.parametrize("failure", [
    "contract", "supervisor-declared", "supervisor-materialized", "worker-observed", "worker-match",
    "hash", "worker-exit", "cleanup", "sigkill", "missing",
])
def test_any_missing_or_changed_evidence_refuses(tmp_path, failure):
    contract, supervisor_environment, worker_environment, supervisor = fixture(tmp_path)
    if failure == "contract":
        row = json.loads(contract.read_text())
        row["schema"] = "capture-execution-v1"
        write(contract, row)
    elif failure.startswith("supervisor-"):
        row = json.loads(supervisor_environment.read_text())
        key = failure.split("-", 1)[1]
        row[key]["HOME"] = "/changed"
        write(supervisor_environment, row)
    elif failure == "worker-observed":
        row = json.loads(worker_environment.read_text())
        row["observed"]["PYTHONPATH"] = "hostile"
        write(worker_environment, row)
    elif failure == "worker-match":
        row = json.loads(worker_environment.read_text())
        row["matches"] = False
        write(worker_environment, row)
    elif failure == "hash":
        row = json.loads(worker_environment.read_text())
        row["execution_contract"]["sha256"] = "0" * 64
        write(worker_environment, row)
    elif failure == "worker-exit":
        row = json.loads(supervisor.read_text())
        row["worker_exit"] = 2
        write(supervisor, row)
    elif failure == "cleanup":
        row = json.loads(supervisor.read_text())
        row["cleanup"]["group_absent"] = False
        write(supervisor, row)
    elif failure == "sigkill":
        row = json.loads(supervisor.read_text())
        row["cleanup"]["sigkill_dispatched"] = True
        write(supervisor, row)
    else:
        worker_environment.unlink()
    audit = audit_environment(contract, supervisor_environment, worker_environment, supervisor)
    assert audit["environment_transport_verified"] is False
    assert audit["failures"]
