"""Synthetic EstimatorStatus journal contract; no ROS/PX4 process is started."""

import hashlib
import json
from pathlib import Path

import pytest

from flydrones.connectome_training.px4_status_source_journal import (
    audit_status_source_journal,
)

SCHEMA = "flydrones.px4_estimator_status_cdr.v1"
MSG_SHA = "44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5"
RATIOS = (
    "hdg_test_ratio", "vel_test_ratio", "pos_test_ratio", "hgt_test_ratio",
    "tas_test_ratio", "hagl_test_ratio", "beta_test_ratio",
)
RESETS = (
    "reset_count_vel_ne", "reset_count_vel_d", "reset_count_pos_ne",
    "reset_count_pod_d", "reset_count_quat",
)


def row(seq=1, **changes):
    cdr = bytes.fromhex("00010000aabbccdd")
    value = {
        "schema": SCHEMA, "kind": "sample", "topic": "/fmu/out/estimator_status",
        "ros_type": "px4_msgs/msg/EstimatorStatus", "message_sha256": MSG_SHA,
        "run_id": "synthetic-status-v1", "journal_sequence": seq,
        "rmw_implementation": "rmw_cyclonedds_cpp", "publisher_gid_hex": "ab" * 24,
        "rmw_source_timestamp_ns": 1000 * seq + 1,
        "rmw_received_timestamp_ns": 1000 * seq + 2,
        "rmw_source_timestamp_available": True,
        "rmw_received_timestamp_available": True,
        "rmw_publication_sequence": seq, "rmw_reception_sequence": seq,
        "callback_steady_ns": 20_000_000 * seq,
        "px4_publication_us": 10_010 * seq, "px4_sample_us": 10_000 * seq,
        "control_mode_flags": 3, "filter_fault_flags": 0,
        "gps_check_fail_flags": 0, "solution_status_flags": 7,
        "pos_horiz_accuracy": 0.2, "pos_vert_accuracy": 0.3,
        "innovation_test_ratios": {name: 0.5 for name in RATIOS},
        "innovation_ratio_available": {name: True for name in RATIOS},
        "reset_counters": {name: 0 for name in RESETS},
        "cdr_hex": cdr.hex(), "cdr_sha256": hashlib.sha256(cdr).hexdigest(),
    }
    value.update(changes)
    return value


def finish(count, *, status="complete", reason=""):
    return {"schema": SCHEMA, "kind": "finish", "run_id": "synthetic-status-v1",
            "samples": count, "status": status, "reason": reason}


def fault(cdr=b"\0\1\0\0bad", reason="decode_error"):
    return {"schema": SCHEMA, "kind": "fault", "run_id": "synthetic-status-v1",
            "reason": reason, "cdr_length": len(cdr), "cdr_hex": cdr.hex(),
            "cdr_sha256": hashlib.sha256(cdr).hexdigest()}


def write(path: Path, *rows):
    path.write_bytes(b"".join((json.dumps(value, allow_nan=False, separators=(",", ":"))
                               + "\n").encode() for value in rows))
    return path


def test_complete_sample_is_offline_only_and_preserves_both_px4_times(tmp_path):
    result = audit_status_source_journal(write(
        tmp_path / "status.jsonl", row(), row(2), finish(2)))
    assert result.terminal_claimed_complete and not result.completed and result.samples == 2
    exited = audit_status_source_journal(tmp_path / "status.jsonl", observed_writer_exit_code=0)
    assert exited.completed
    failed_exit = audit_status_source_journal(tmp_path / "status.jsonl", observed_writer_exit_code=2)
    assert not failed_exit.completed
    assert result.first_cdr == bytes.fromhex("00010000aabbccdd")
    assert result.publisher_gid_hex == "ab" * 24
    assert result.last_publication_us == 20_020
    assert result.last_sample_us == 20_000
    assert result.publication_to_sample_delay_us == 20
    assert not result.live_source_authenticated
    assert not result.fusion_qualified
    assert not result.camera_calibration_qualified
    assert not result.training_eligible


def test_unavailable_ratio_is_null_with_explicit_false_not_zero(tmp_path):
    value = row()
    value["innovation_test_ratios"]["vel_test_ratio"] = None
    value["innovation_ratio_available"]["vel_test_ratio"] = False
    result = audit_status_source_journal(write(tmp_path / "status.jsonl", value, finish(1)))
    assert "vel_test_ratio" in result.unavailable_innovation_ratios
    assert not result.training_eligible


@pytest.mark.parametrize("ratios,available", [
    ({"vel_test_ratio": None}, {"vel_test_ratio": True}),
    ({"vel_test_ratio": 0.0}, {"vel_test_ratio": False}),
    ({"vel_test_ratio": -0.1}, {"vel_test_ratio": True}),
    ({"vel_test_ratio": 1e100}, {"vel_test_ratio": True}),
    ({"not_a_ratio": 0.1}, {}),
])
def test_ratio_availability_mismatch_or_bad_value_refused(tmp_path, ratios, available):
    value = row()
    value["innovation_test_ratios"].update(ratios)
    value["innovation_ratio_available"].update(available)
    with pytest.raises(ValueError):
        audit_status_source_journal(write(tmp_path / "status.jsonl", value, finish(1)))


@pytest.mark.parametrize("changed", [
    {"topic": "/fmu/out/estimator_status_flags"},
    {"ros_type": "px4_msgs/msg/EstimatorStatusFlags"},
    {"message_sha256": "0" * 64},
    {"publisher_gid_hex": "0" * 48},
    {"publisher_gid_hex": "ab"},
    {"px4_sample_us": 10_011},
    {"px4_sample_us": 0},
    {"callback_steady_ns": 0},
    {"rmw_publication_sequence": -1},
    {"filter_fault_flags": -1},
    {"filter_fault_flags": 2**32},
    {"pos_horiz_accuracy": -1.0},
    {"pos_vert_accuracy": None},
    {"reset_counters": {name: 0 for name in RESETS if name != "reset_count_quat"}},
    {"cdr_hex": "00010000aabbccde"},
    {"cdr_hex": "ab" * 4097},
])
def test_malformed_type_identity_time_fields_or_cdr_refused(tmp_path, changed):
    with pytest.raises(ValueError):
        audit_status_source_journal(write(tmp_path / "status.jsonl", row(**changed), finish(1)))


@pytest.mark.parametrize("changed", [
    {"journal_sequence": 1}, {"publisher_gid_hex": "cd" * 24},
    {"rmw_implementation": "rmw_other"}, {"px4_sample_us": 9_000},
    {"px4_publication_us": 9_010}, {"callback_steady_ns": 19_000_000},
    {"px4_sample_us": 120_001, "px4_publication_us": 120_002},
    {"rmw_publication_sequence": 1}, {"rmw_reception_sequence": 1},
    {"run_id": "another"},
    {"reset_counters": {**{name: 0 for name in RESETS}, "reset_count_quat": 1}},
])
def test_source_replacement_clock_rollback_or_reset_ends_session(tmp_path, changed):
    with pytest.raises(ValueError):
        audit_status_source_journal(write(tmp_path / "status.jsonl", row(), row(2, **changed), finish(2)))


def test_unsupported_rmw_metadata_is_unknown_not_zero(tmp_path):
    value = row(rmw_publication_sequence=None, rmw_reception_sequence=None,
                rmw_source_timestamp_ns=None, rmw_received_timestamp_ns=None,
                rmw_source_timestamp_available=False, rmw_received_timestamp_available=False)
    result = audit_status_source_journal(write(tmp_path / "status.jsonl", value, finish(1)))
    assert not result.rmw_sequences_supported


@pytest.mark.parametrize("changed", [
    {"rmw_source_timestamp_ns": 0},
    {"rmw_source_timestamp_ns": None},
    {"rmw_source_timestamp_available": False},
    {"rmw_received_timestamp_ns": 0},
    {"rmw_received_timestamp_ns": None},
    {"rmw_received_timestamp_available": False},
])
def test_rmw_timestamp_availability_mismatch_refused(tmp_path, changed):
    with pytest.raises(ValueError):
        audit_status_source_journal(write(tmp_path / "status.jsonl", row(**changed), finish(1)))


def test_writer_exit_evidence_type_and_failed_terminal_must_agree(tmp_path):
    complete = write(tmp_path / "complete.jsonl", row(), finish(1))
    with pytest.raises(ValueError):
        audit_status_source_journal(complete, observed_writer_exit_code=True)
    failed = write(tmp_path / "failed.jsonl", finish(0, status="failed", reason="no_messages"))
    with pytest.raises(ValueError):
        audit_status_source_journal(failed, observed_writer_exit_code=0)


def test_rmw_gap_only_records_reader_observation_not_upstream_loss(tmp_path):
    result = audit_status_source_journal(write(
        tmp_path / "status.jsonl", row(), row(2, rmw_publication_sequence=4), finish(2)))
    assert result.observed_rmw_gap
    assert not result.upstream_loss_qualified


def test_explicit_failed_zero_sample_and_cdr_fault_journals(tmp_path):
    zero = audit_status_source_journal(write(
        tmp_path / "zero.jsonl", finish(0, status="failed", reason="no_messages")))
    assert not zero.completed and zero.samples == 0 and zero.first_cdr == b""
    bad = audit_status_source_journal(write(
        tmp_path / "bad.jsonl", row(), fault(),
        finish(1, status="failed", reason="decode_error")))
    assert not bad.completed and bad.faults == 1


def test_oversized_cdr_fault_retains_hash_and_length_without_unbounded_hex(tmp_path):
    payload = b"x" * 4097
    event = fault(payload, reason="cdr_oversize")
    event["cdr_hex"] = ""
    result = audit_status_source_journal(write(
        tmp_path / "oversized.jsonl", event,
        finish(0, status="failed", reason="cdr_oversize")))
    assert result.faults == 1 and not result.completed
    event["cdr_length"] = 4096
    with pytest.raises(ValueError):
        audit_status_source_journal(write(
            tmp_path / "false_length.jsonl", event,
            finish(0, status="failed", reason="cdr_oversize")))


def test_read_io_failure_never_returns_success(tmp_path, monkeypatch):
    path = write(tmp_path / "status.jsonl", row(), finish(1))
    original_open = Path.open

    def unavailable(self, *args, **kwargs):
        if self == path:
            raise OSError("injected journal read failure")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unavailable)
    with pytest.raises(OSError, match="read failure"):
        audit_status_source_journal(path)


@pytest.mark.parametrize("rows", [
    (row(),), (row(), finish(2)), (row(), finish(1), row(2)),
    (fault(), finish(0)), (fault(), row(), finish(1, status="failed", reason="decode_error")),
])
def test_truncation_miscount_post_terminal_and_fault_order_refused(tmp_path, rows):
    with pytest.raises(ValueError):
        audit_status_source_journal(write(tmp_path / "status.jsonl", *rows))


def test_legacy_odometry_schema_cannot_be_accepted_as_status(tmp_path):
    value = row(schema="flydrones.px4_ros2_odometry_cdr.v2")
    with pytest.raises(ValueError):
        audit_status_source_journal(write(tmp_path / "status.jsonl", value, finish(1)))


def test_duplicate_json_key_and_nan_literal_are_refused(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b'{"schema":"x","schema":"y"}\n')
    with pytest.raises(ValueError):
        audit_status_source_journal(path)
    path.write_bytes(b'{"schema":NaN}\n')
    with pytest.raises(ValueError):
        audit_status_source_journal(path)


def test_symlink_and_oversized_line_are_refused(tmp_path):
    path = write(tmp_path / "target.jsonl", row(), finish(1))
    link = tmp_path / "link.jsonl"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlink privileges unavailable")
    with pytest.raises(ValueError):
        audit_status_source_journal(link)
    path.write_bytes(b"x" * 100_000 + b"\n")
    with pytest.raises(ValueError):
        audit_status_source_journal(path)
