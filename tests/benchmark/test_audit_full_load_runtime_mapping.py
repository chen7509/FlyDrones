import json

import pytest

from tools.benchmark.audit_full_load_runtime_mapping import audit_capture

SELF_PHASES = ["postimports", "postfinalize", "postfirststep"]
OWNED = {"px4": ["ready", "prestop"], "openvins": ["ready", "prestop"]}


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def capture_fixture(tmp_path):
    capture = tmp_path / "capture-v1"
    capture.mkdir()
    result = dict(
        status="capture_completed", errors=[], end_sim_ns=25_000_000_000, px4_exit_code=0,
        runtime_binding=dict(pre_recorded=True, declared_files_stable=True,
                             local_file_graph_verified=True, phases=["postgraph", "bootstrap", *SELF_PHASES],
                             owned_phases=OWNED, runtime_mapping_coverage_verified=True,
                             errors=[], runtime_closure_qualified=False),
        eligible_for_px4_fusion=False,
    )
    write(capture / "result.json", result)
    write(tmp_path / "capture-v1.supervisor.json", dict(
        status="worker_exited", worker_exit=0, capture_status="capture_completed", errors=[],
        cleanup=dict(graceful_group_cleanup_verified=True, no_executing_members=True,
                     group_absent=True, sigkill_dispatched=False)))
    files = [dict(path="px4-ulog/log.ulg", bytes=4, sha256="", valid_header=True)]
    (capture / "px4-ulog").mkdir()
    log = capture / "px4-ulog/log.ulg"
    log.write_bytes(b"ULog")
    import hashlib
    files[0]["sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
    write(capture / "px4-ulog-manifest.json", {"schema": "flydrones-px4-ulog-capture-v1", "logs": files})
    write(capture / "runtime-binding-pre.json", {"files": [{"sha256": "a"}]})
    write(capture / "runtime-binding-post.json", {"files": [{"sha256": "a"}]})
    for phase in SELF_PHASES:
        write(capture / f"runtime-maps-{phase}.json", dict(
            phase=phase, unknown=[], mismatched=[], parse_error=None, observed_files_covered=True))
    for role, phases in OWNED.items():
        for phase in phases:
            write(capture / f"runtime-maps-{role}-{phase}.json", dict(
                role=role, phase=phase, unknown=[], mismatched=[], error=None, observed_files_covered=True))
    return capture


def test_complete_mapping_capture_qualifies_only_mapping(tmp_path):
    capture = capture_fixture(tmp_path)
    result = audit_capture(capture, tmp_path / "capture-v1.supervisor.json")
    assert result["runtime_mapping_coverage_verified"] is True
    assert result["runtime_closure_qualified"] is False
    assert result["vio_accuracy_qualified"] is False
    assert result["fusion_eligible"] is False


@pytest.mark.parametrize("failure", [
    "status", "duration", "phase", "phase_order", "unknown", "ulog", "cleanup", "drift",
    "binding", "supervisor",
])
def test_incomplete_or_unsafe_evidence_refuses_mapping_qualification(tmp_path, failure):
    capture = capture_fixture(tmp_path)
    result_path = capture / "result.json"
    result = json.loads(result_path.read_text())
    supervisor_path = tmp_path / "capture-v1.supervisor.json"
    if failure == "status":
        result["status"] = "capture_failed"
    elif failure == "duration":
        result["end_sim_ns"] -= 1
    elif failure == "phase":
        (capture / "runtime-maps-postfirststep.json").unlink()
    elif failure == "phase_order":
        result["runtime_binding"]["phases"] = [
            "postgraph", "bootstrap", "postfinalize", "postimports", "postfirststep",
        ]
    elif failure == "unknown":
        path = capture / "runtime-maps-px4-ready.json"
        row = json.loads(path.read_text())
        row["unknown"] = [{"path": "/unknown.so"}]
        row["observed_files_covered"] = False
        write(path, row)
    elif failure == "ulog":
        (capture / "px4-ulog/log.ulg").unlink()
    elif failure == "cleanup":
        supervisor = json.loads(supervisor_path.read_text())
        supervisor["cleanup"]["group_absent"] = False
        write(supervisor_path, supervisor)
    elif failure == "drift":
        write(capture / "runtime-binding-post.json", {"files": [{"sha256": "b"}]})
    elif failure == "binding":
        result["runtime_binding"]["runtime_mapping_coverage_verified"] = False
    else:
        supervisor = json.loads(supervisor_path.read_text())
        supervisor["worker_exit"] = 2
        write(supervisor_path, supervisor)
    write(result_path, result)
    audit = audit_capture(capture, supervisor_path)
    assert audit["runtime_mapping_coverage_verified"] is False
    assert audit["failures"]
