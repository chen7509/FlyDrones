"""File adapter negatives use a retained real startup-only result, never a run."""

import hashlib
import json
import socket
import subprocess
from pathlib import Path

import pytest

from tests.benchmark.test_live_wire_study import fixture, write
from tools.benchmark import audit_live_wire_study as audit


def api():
    assert hasattr(audit, "audit_live_wire_study"), "whole-study entry missing"
    return audit.audit_live_wire_study


def test_actual_completed_startup_cannot_qualify(tmp_path, monkeypatch):
    manifest, _, path = fixture(tmp_path)
    capture = Path(manifest["outputs"]["capture"])
    capture.mkdir()
    raw = (Path(__file__).parent / "fixtures/live_wire/installed-startup-result.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "bea9ffb42b6a412ab757f1ad1d036e8db17c4871d63e17fec2441dcaeb6d930c"
    original = json.loads(raw)
    assert original["status"] == "capture_completed" and original["startup_preflight_only"] is True
    (capture / "result.json").write_bytes(raw)

    def forbidden(*args, **kwargs):
        raise AssertionError("offline audit created a process or socket")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    out = api()(path)
    assert out["checks"]["documents"]["document_validated"] is True
    assert out["checks"]["documents"]["files_verified"] is False
    assert out["refusals"][0]["stage"] == "capture"
    assert "startup-only" in out["refusals"][0]["reason"]
    assert out["live_qualified"] is out["fusion_qualified"] is False
    assert out["consumed_files"][str(capture / "result.json")]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert not Path(manifest["outputs"]["audit"]).exists()


@pytest.mark.parametrize(
    "fault", ["missing_manifest", "duplicate_json", "input_drift", "missing_result", "failed_result", "missing_dispatch"]
)
def test_structured_refusal_preserves_stage(tmp_path, fault):
    manifest, _, path = fixture(tmp_path)
    expected = "documents"
    if fault == "missing_manifest":
        path.unlink()
    elif fault == "duplicate_json":
        path.write_text('{"schema":1,"schema":2}')
    elif fault == "input_drift":
        Path(manifest["files"]["execution"]["requested"]).write_text("{}")
    else:
        expected = "capture"
        capture = Path(manifest["outputs"]["capture"])
        capture.mkdir()
        if fault != "missing_result":
            row = dict(
                status="capture_completed",
                errors=[],
                estimator_run=True,
                end_sim_ns=25_000_000_000,
                eligible_for_px4_fusion=False,
                px4_exit_code=0,
            )
            if fault == "failed_result":
                row["status"] = "capture_failed"
            else:
                expected = "dispatch"
            write(capture / "result.json", row)
    out = api()(path)
    assert out["refusals"][0]["stage"] == expected
    assert out["live_qualified"] is out["fusion_qualified"] is out["record_chain_qualified"] is False


def test_capture_member_path_escape_is_rejected(tmp_path):
    assert hasattr(audit, "StudyEvidenceReader"), "bounded study reader missing"
    reader = audit.StudyEvidenceReader()
    with pytest.raises(ValueError):
        reader.member(tmp_path, "../foreign.json")


def test_final_member_drift_is_rejected(tmp_path):
    assert hasattr(audit, "StudyEvidenceReader"), "bounded study reader missing"
    path = tmp_path / "member.json"
    path.write_text("{}")
    reader = audit.StudyEvidenceReader()
    reader.document(path)
    path.write_text('{"changed":true}')
    with pytest.raises(ValueError):
        reader.finish()


def test_declared_file_hash_is_checked_before_use(tmp_path):
    from tools.benchmark.declared_runtime_snapshot import file_record

    path = tmp_path / "binary"
    path.write_bytes(b"never executed")
    record = file_record(path)
    reader = audit.StudyEvidenceReader()
    assert hasattr(reader, "declared_file"), "declared identity reader missing"
    assert reader.declared_file(record) == b"never executed"
    record["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        reader.declared_file(record)


def test_malformed_file_index_is_structured_refusal(tmp_path):
    manifest, _, path = fixture(tmp_path)
    manifest["files"] = []
    write(path, manifest)
    out = api()(path)
    assert out["refusals"][0]["stage"] == "documents"


def routed_fixture(tmp_path, monkeypatch):
    """Test file routing with explicit leaf doubles, NOT complete chain evidence."""
    from tools.benchmark import (
        audit_live_wire_runtime,
        audit_live_wire_ulog,
        audit_live_wire_workload,
        native_supervisor_integration,
    )
    from tools.benchmark.declared_runtime_snapshot import file_record

    manifest, docs, path = fixture(tmp_path)
    capture = Path(manifest["outputs"]["capture"])
    capture.mkdir()

    def put(name, obj):
        member = capture / name
        member.parent.mkdir(parents=True, exist_ok=True)
        write(member, obj)

    def lines(name, rows):
        member = capture / name
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_text("".join(json.dumps(row) + "\n" for row in rows))

    dispatch = dict(
        schema="live-wire-study-dispatch-v1",
        study_manifest=file_record(path),
        run_id=manifest["study_id"],
        role="development",
        seed=27601,
        destination=str(capture),
        command=manifest["command"],
        resources_before=[],
        single_actual_attempt=True,
        physical_run=True,
        fusion_eligible=False,
        started_wall_ns=100,
    )
    completion = dict(
        schema="live-wire-study-completion-v1",
        run_id=manifest["study_id"],
        destination=str(capture),
        destination_exists=True,
        command_returncode=0,
        launcher_returncode=0,
        launcher_error=None,
        resources_after=[],
        physical_run=True,
        fusion_eligible=False,
        ended_wall_ns=200,
    )
    write(Path(manifest["outputs"]["dispatch"]), dispatch)
    write(Path(manifest["outputs"]["completion"]), completion)
    put(
        "result.json",
        dict(
            status="capture_completed",
            errors=[],
            estimator_run=True,
            end_sim_ns=25_000_000_000,
            eligible_for_px4_fusion=False,
            px4_exit_code=0,
            runtime_binding={},
            px4_ulogs=[dict(path="px4-ulog/log/test.ulg", bytes=3, sha256=hashlib.sha256(b"log").hexdigest(), valid_header=True)],
        ),
    )
    for name in ("runtime-binding-pre", "runtime-binding-post", "supervisor", "process", "wire-owner"):
        put(name + ".json", {})
    for phase in ["postgraph", "bootstrap", *docs["binding"]["runtime_maps"]["self_phases"]]:
        put("runtime-maps-" + phase + ".json", {})
        (capture / ("runtime-maps-" + phase + ".txt")).write_text("synthetic mapping")
    for role, phases in docs["binding"]["runtime_maps"]["owned_roles"].items():
        put("runtime-owner-" + role + ".json", {})
        for phase in phases:
            put(f"runtime-maps-{role}-{phase}.json", {})
            (capture / f"runtime-maps-{role}-{phase}.txt").write_text("synthetic mapping")
    (capture.parent / (capture.name + ".supervisor-events.jsonl")).write_text("{}\n")
    put("wire-lifecycle.json", dict(session=dict(retention={}, clock={})))
    lines("wire-clock.jsonl", [{}])
    lines("events.jsonl", [dict(kind="heartbeat")])
    for name in ("source-fanout", "shadow/native-requests", "shadow/native-acks", "shadow/states"):
        lines(name + ".jsonl", [{}])
    put(
        "shadow/native-session.json",
        dict(
            pid=322,
            command=[
                docs["execution"]["inputs"]["shadow_binary"],
                docs["execution"]["inputs"]["shadow_config"],
                str(capture / "shadow/states.jsonl"),
                str(capture / "shadow/fast.jsonl"),
            ],
        ),
    )
    put("shadow/shadow-input-result.json", {})
    entry = json.loads((capture / "result.json").read_text())["px4_ulogs"][0]
    put("px4-ulog-manifest.json", dict(schema="flydrones-px4-ulog-capture-v1", logs=[entry]))
    log = capture / entry["path"]
    log.parent.mkdir(parents=True)
    log.write_bytes(b"log")
    monkeypatch.setattr(
        audit_live_wire_runtime, "audit_runtime_mapping_records", lambda **kw: dict(owners=dict(openvins=dict(pid=322)))
    )
    monkeypatch.setattr(native_supervisor_integration, "audit_supervisor", lambda *args, **kw: dict(qualified=True))
    monkeypatch.setattr(audit, "audit_wire_capture_identity", lambda **kw: dict(context={}))
    monkeypatch.setattr(
        audit, "read_segmented_wire_records", lambda *args: dict(records=[], members=[], channels={}, integrity_verified=True)
    )
    monkeypatch.setattr(audit, "audit_wire_protocol_records", lambda **kw: dict(synthetic_double=True))
    monkeypatch.setattr(audit, "audit_wire_interval_records", lambda *args: dict(synthetic_double=True))
    monkeypatch.setattr(audit, "audit_owned_listener_records", lambda **kw: dict(synthetic_double=True))
    monkeypatch.setattr(audit_live_wire_workload, "audit_source_native_records", lambda **kw: dict(synthetic_double=True))

    def ulog(raw, value):
        assert raw == b"log" and value == entry
        return dict(synthetic_double=True)

    monkeypatch.setattr(audit_live_wire_ulog, "audit_unarmed_ulog", ulog)
    return manifest, path, capture


def test_routes_original_ulog_manifest_shape_without_qualification(tmp_path, monkeypatch):
    _, path, _ = routed_fixture(tmp_path, monkeypatch)
    out = api()(path)
    assert out["refusals"] == []
    assert out["checks"]["ulog"] == dict(synthetic_double=True)
    assert out["unverified"]
    assert out["record_chain_qualified"] is out["live_qualified"] is False


def test_wrong_native_configuration_cannot_be_hidden_by_matching_binary(tmp_path, monkeypatch):
    _, path, capture = routed_fixture(tmp_path, monkeypatch)
    p = capture / "shadow/native-session.json"
    data = json.loads(p.read_text())
    data["command"][1] = "/unfrozen/config.yaml"
    write(p, data)
    out = api()(path)
    assert out["refusals"] and out["refusals"][0]["stage"] == "source_native"


@pytest.mark.parametrize(
    "fault",
    [
        "dispatch_identity",
        "dispatch_command",
        "dispatch_seed",
        "dispatch_physical",
        "completion_run",
        "completion_time",
        "completion_error",
        "native_pid",
        "native_command",
        "ulog_missing",
    ],
)
def test_routing_does_not_hide_cross_file_refusals(tmp_path, monkeypatch, fault):
    manifest, path, capture = routed_fixture(tmp_path, monkeypatch)
    if fault.startswith("dispatch"):
        p = Path(manifest["outputs"]["dispatch"])
        data = json.loads(p.read_text())
        if fault == "dispatch_identity":
            data["study_manifest"]["sha256"] = "0" * 64
        elif fault == "dispatch_command":
            data["command"].append("--omit-estimator")
        elif fault == "dispatch_seed":
            data["seed"] = 27602
        else:
            data["physical_run"] = False
        write(p, data)
    elif fault.startswith("completion"):
        p = Path(manifest["outputs"]["completion"])
        data = json.loads(p.read_text())
        if fault == "completion_run":
            data["run_id"] = "other"
        elif fault == "completion_time":
            data["ended_wall_ns"] = 1
        else:
            data["launcher_error"] = "timeout"
        write(p, data)
    elif fault.startswith("native"):
        p = capture / "shadow/native-session.json"
        data = json.loads(p.read_text())
        if fault == "native_pid":
            data["pid"] = 999
        else:
            data["command"][0] = "/other/native"
        write(p, data)
    else:
        (capture / "px4-ulog/log/test.ulg").unlink()
    out = api()(path)
    expected = (
        "dispatch" if fault.startswith(("dispatch", "completion")) else "source_native" if fault.startswith("native") else "ulog"
    )
    assert out["refusals"][0]["stage"] == expected
    assert out["live_qualified"] is False
