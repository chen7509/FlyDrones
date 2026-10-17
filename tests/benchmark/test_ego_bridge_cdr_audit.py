"""Independent validation of the bridge's raw-byte journal format."""

import json
from copy import deepcopy

import pytest

from tools.benchmark.ego_bridge_cdr_audit import audit_bridge_cdr_journal
from tools.benchmark.ego_bridge_cdr_journal import BridgeCDRJournal


def complete_rows(tmp_path):
    path = tmp_path / "bridge.jsonl"
    writer = BridgeCDRJournal.open_new(
        path, run_id="run-1", session_id="session-1", serializer=lambda message: message)
    writer.start_reset(1)
    writer.publish("clock", b"\x00\x01clock", 100, lambda _: None)
    writer.publish("odometry", b"\x00\x01odom", 100, lambda _: None)
    seq = writer.receive_command(b"\x00\x01command")
    writer.command_decoded(seq, stamp_ns=100, trajectory_id=7, ready=True)
    writer.close()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_complete_bytes_and_return_pairs_remain_unattested(tmp_path):
    result = audit_bridge_cdr_journal(complete_rows(tmp_path))
    assert result["publication_count"] == 2
    assert result["received_command_count"] == 1
    assert result["source_attested"] is False
    assert result["teacher_qualified"] is False


@pytest.mark.parametrize("change", [
    lambda rows: rows.pop(-1),  # no final close
    lambda rows: rows.pop(3),  # intent without return
    lambda rows: rows.__setitem__(2, {**rows[2], "message_sha256": "0" * 64}),
    lambda rows: rows.__setitem__(2, {**rows[2], "message_cdr_b64": "%%%"}),
    lambda rows: rows.__setitem__(2, {**rows[2], "source": "px4_ekf2"}),
    lambda rows: rows.__setitem__(2, {**rows[2], "truth_used": False}),
    lambda rows: rows.__setitem__(2, {**rows[2], "sequence": 50}),
    lambda rows: rows.__setitem__(2, {**rows[2], "event_steady_ns": 0}),
    lambda rows: rows.__setitem__(3, {**rows[3], "message_sequence": 77}),
])
def test_incomplete_or_mutated_journal_is_rejected(tmp_path, change):
    original = complete_rows(tmp_path)
    rows = deepcopy(original)
    change(rows)
    with pytest.raises(ValueError):
        audit_bridge_cdr_journal(rows)
    assert audit_bridge_cdr_journal(original)["teacher_qualified"] is False


def test_audit_rejects_recorded_publish_failure(tmp_path):
    path = tmp_path / "failed.jsonl"
    writer = BridgeCDRJournal.open_new(
        path, run_id="run-1", session_id="session-1", serializer=lambda message: message)
    writer.start_reset(1)
    with pytest.raises(RuntimeError):
        writer.publish("depth", b"\x00\x01bad", 100,
                       lambda _: (_ for _ in ()).throw(RuntimeError("publish")))
    writer.close()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    with pytest.raises(ValueError, match="failure|incomplete"):
        audit_bridge_cdr_journal(rows)


def test_nonobject_header_and_bool_pid_are_refused_as_bad_evidence(tmp_path):
    original = complete_rows(tmp_path)
    rows = deepcopy(original)
    rows[0] = []
    with pytest.raises(ValueError):
        audit_bridge_cdr_journal(rows)
    rows = deepcopy(original)
    rows[1]["pid"] = True
    with pytest.raises(ValueError):
        audit_bridge_cdr_journal(rows)
