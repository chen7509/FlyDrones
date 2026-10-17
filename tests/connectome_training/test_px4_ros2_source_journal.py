"""Synthetic journal tests; no ROS 2 or PX4 process is started here."""

import hashlib
import json
from pathlib import Path

import pytest

from flydrones.connectome_training.px4_ros2_source_journal import audit_source_journal

TYPE_BLOB = "cf117ff82cdbf191bf576db91db900b7ce34f6a7"
SCHEMA = "flydrones.px4_ros2_odometry_cdr.v1"


def _row(sequence: int = 1, **changed) -> dict:
    cdr = bytes.fromhex("000100001234")
    row = {
        "schema": SCHEMA,
        "kind": "sample",
        "topic": "/fmu/out/vehicle_odometry",
        "ros_type": "px4_msgs/msg/VehicleOdometry",
        "message_blob_sha": TYPE_BLOB,
        "run_id": "synthetic-source-v1",
        "journal_sequence": sequence,
        "rmw_implementation": "rmw_cyclonedds_cpp",
        "publisher_gid_hex": "ab" * 24,
        "rmw_source_timestamp_ns": 1000 * sequence + 123,
        "rmw_received_timestamp_ns": 1000 * sequence + 124,
        "rmw_publication_sequence": sequence,
        "rmw_reception_sequence": sequence,
        "callback_steady_ns": 20_000_000 * sequence,
        "px4_publication_us": 10_010 * sequence,
        "px4_sample_us": 10_000 * sequence,
        "pose_frame": 1,
        "velocity_frame": 1,
        "reset_counter": 3,
        "quality": 0,
        "cdr_hex": cdr.hex(),
        "cdr_sha256": hashlib.sha256(cdr).hexdigest(),
    }
    row.update(changed)
    return row


def _finish(count: int, **changed) -> dict:
    row = {"schema": SCHEMA, "kind": "finish", "run_id": "synthetic-source-v1",
           "samples": count, "status": "complete", "reason": ""}
    row.update(changed)
    return row


def _fault(cdr: bytes = b"\x00\x01\x00\x00bad") -> dict:
    return {"schema": SCHEMA, "kind": "fault", "run_id": "synthetic-source-v1",
            "reason": "decode_error", "cdr_length": len(cdr), "cdr_hex": cdr.hex(),
            "cdr_sha256": hashlib.sha256(cdr).hexdigest()}


def _write(path: Path, *rows: dict) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_complete_journal_retains_bytes_and_metadata_but_never_grants_capture(tmp_path):
    path = _write(tmp_path / "source.jsonl", _row(), _row(2), _finish(2))
    result = audit_source_journal(path)
    assert result.samples == 2
    assert result.run_id == "synthetic-source-v1"
    assert result.first_cdr == bytes.fromhex("000100001234")
    assert result.publisher_gid_hex == "ab" * 24
    assert result.eligible_for_live_capture is False
    assert "cdr_decode_parity_not_verified" in result.missing_qualification
    assert "publisher_process_not_authenticated" in result.missing_qualification


def test_unsupported_rmw_sequences_are_unknown_not_invented(tmp_path):
    path = _write(tmp_path / "source.jsonl", _row(
        rmw_publication_sequence=None, rmw_reception_sequence=None,
        rmw_source_timestamp_ns=0, rmw_received_timestamp_ns=0), _finish(1))
    result = audit_source_journal(path)
    assert result.rmw_sequences_supported is False


def test_rmw_publication_gap_is_recorded_without_claiming_message_loss_cause(tmp_path):
    path = _write(tmp_path / "source.jsonl", _row(),
                  _row(2, rmw_publication_sequence=3), _finish(2))
    result = audit_source_journal(path)
    assert result.observed_sequence_gap is True
    assert result.eligible_for_live_capture is False


def test_no_message_timeout_is_a_retained_failed_journal(tmp_path):
    result = audit_source_journal(_write(
        tmp_path / "source.jsonl", _finish(0, status="failed", reason="no_messages")))
    assert result.samples == 0
    assert result.completed is False
    assert result.publisher_gid_hex == ""
    assert result.first_cdr == b""
    assert result.eligible_for_live_capture is False


def test_decode_fault_retains_serialized_bytes_without_a_valid_sample(tmp_path):
    result = audit_source_journal(_write(
        tmp_path / "source.jsonl", _fault(),
        _finish(0, status="failed", reason="decode_error")))
    assert result.samples == 0
    assert result.faults == 1
    assert result.completed is False


def test_changed_source_fault_retains_bytes_in_failed_journal(tmp_path):
    fault = _fault()
    fault["reason"] = "source_invariant"
    result = audit_source_journal(_write(
        tmp_path / "source.jsonl", _row(), fault,
        _finish(1, status="failed", reason="source_invariant")))
    assert result.samples == 1
    assert result.faults == 1
    assert result.completed is False


def test_oversized_fault_retains_length_and_digest_without_unbounded_hex(tmp_path):
    payload = b"x" * 4097
    fault = _fault(payload)
    fault.update(reason="cdr_oversize", cdr_hex="")
    result = audit_source_journal(_write(
        tmp_path / "source.jsonl", fault,
        _finish(0, status="failed", reason="cdr_oversize")))
    assert result.faults == 1
    assert result.completed is False


def test_oversized_fault_cannot_claim_shorter_input(tmp_path):
    payload = b"x" * 4097
    fault = _fault(payload)
    fault.update(reason="cdr_oversize", cdr_hex="", cdr_length=4096)
    with pytest.raises(ValueError):
        audit_source_journal(_write(
            tmp_path / "source.jsonl", fault,
            _finish(0, status="failed", reason="cdr_oversize")))


def test_oversized_line_is_rejected_before_unbounded_read(tmp_path, monkeypatch):
    path = tmp_path / "source.jsonl"
    path.write_bytes(b"x" * 100_000 + b"\n")
    original_open = Path.open

    class BoundedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def readline(self, limit=-1):
            assert 0 < limit <= 32_769
            return self.stream.readline(limit)

    def bounded_open(self, *args, **kwargs):
        return BoundedReader(original_open(self, *args, **kwargs))

    monkeypatch.setattr(Path, "open", bounded_open)
    with pytest.raises(ValueError, match="oversized"):
        audit_source_journal(path)


def test_fault_followed_by_sample_or_complete_terminal_is_refused(tmp_path):
    with pytest.raises(ValueError):
        audit_source_journal(_write(tmp_path / "a.jsonl", _fault(), _row(),
                                    _finish(1, status="failed", reason="decode_error")))
    with pytest.raises(ValueError):
        audit_source_journal(_write(tmp_path / "b.jsonl", _fault(), _finish(0)))


@pytest.mark.parametrize("changed", [
    {"cdr_hex": "000100001235"},
    {"cdr_hex": "00" * 4097},
    {"cdr_hex": "0"},
    {"publisher_gid_hex": "abc"},
    {"message_blob_sha": "0" * 40},
    {"topic": "/fmu/out/vehicle_local_position"},
    {"ros_type": "px4_msgs/msg/VehicleLocalPosition"},
    {"pose_frame": 2},
    {"velocity_frame": 2},
    {"quality": 1},
    {"px4_sample_us": 10_011},
    {"rmw_publication_sequence": -1},
    {"callback_steady_ns": 0},
])
def test_malformed_or_mismatched_source_refused(tmp_path, changed):
    with pytest.raises(ValueError):
        audit_source_journal(_write(tmp_path / "source.jsonl", _row(**changed), _finish(1)))


@pytest.mark.parametrize("second", [
    {"journal_sequence": 1},
    {"publisher_gid_hex": "cd" * 24},
    {"reset_counter": 4},
    {"reset_counter": 0},
    {"px4_sample_us": 9_000},
    {"px4_publication_us": 9_010},
    {"callback_steady_ns": 19_000_000},
    {"rmw_publication_sequence": 1},
    {"rmw_reception_sequence": 1},
    {"run_id": "other-run"},
])
def test_changed_source_or_time_refused(tmp_path, second):
    first = _row(reset_counter=255) if second.get("reset_counter") == 0 else _row()
    later = _row(2)
    later.update(second)
    with pytest.raises(ValueError):
        audit_source_journal(_write(tmp_path / "source.jsonl", first, later, _finish(2)))


@pytest.mark.parametrize("rows", [
    (_row(),),
    (_row(), _finish(2)),
    (_row(), _finish(1), _row(2)),
    (_row(), _finish(1, status="failed", reason="source lost")),
])
def test_incomplete_mismatched_or_failed_journal_never_qualifies(tmp_path, rows):
    path = _write(tmp_path / "source.jsonl", *rows)
    if len(rows) == 2 and rows[-1]["status"] == "failed":
        result = audit_source_journal(path)
        assert result.completed is False
        assert result.eligible_for_live_capture is False
    else:
        with pytest.raises(ValueError):
            audit_source_journal(path)
