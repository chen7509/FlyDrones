"""Independent status bytes/fields; no ROS, PX4, Docker or network process."""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from flydrones.connectome_training import px4_status_cdr_fields as fields
from flydrones.connectome_training.px4_status_cdr_fields import audit_status_cdr_fields

ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "tests/fixtures/px4_status_transport/EstimatorStatus.d6f12ad.msg"
ARCHIVE_SHA = "6fbefedf287fb6915fd208211d2f0fbd18d825a08e0c0ff30cd6158387cc9a4d"
MEMBER = "results/px4-status-journal-synthetic-dev-1701-v2/normal/source.jsonl"
JOURNAL_SHA = "c51acb744e31e3d4f210f2b3f48253e9b47e52019421327415da22913c1e2ad1"


@pytest.fixture
def native_rows():
    raw = (ROOT / "evidence/px4-estimator-status-journal-dev-1701.zip").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA
    with ZipFile(ROOT / "evidence/px4-estimator-status-journal-dev-1701.zip") as archive:
        data = archive.read(MEMBER)
    assert hashlib.sha256(data).hexdigest() == JOURNAL_SHA
    return [json.loads(line) for line in data.splitlines()]


def write(tmp_path, rows):
    target = tmp_path / "status.jsonl"
    target.write_bytes(b"".join((json.dumps(row, allow_nan=False) + "\n").encode() for row in rows))
    return target


def audit(path, definition=None, exit_code=0):
    return audit_status_cdr_fields(
        path, DEFINITION.read_bytes() if definition is None else definition,
        observed_writer_exit_code=exit_code,
    )


def test_all_native_callback_fields_match_without_live_authority(tmp_path, native_rows):
    result = audit(write(tmp_path, native_rows))
    assert result["samples"] == 3
    assert result["logged_fields_verified"]
    assert result["writer_completed"]
    assert result["unavailable_ratios"] == ["vel_test_ratio"]
    assert len(result["sample_records"]) == 3
    assert all(row["cdr_bytes"] == 140 for row in result["sample_records"])
    for name in ("live_source_authenticated", "upstream_loss_qualified", "clock_epoch_qualified",
                 "fusion_qualified", "camera_calibration_qualified", "training_eligible"):
        assert result[name] is False


@pytest.mark.parametrize("payload", [b"\0\1\0\0bad", b"\0\1\0\0", b"\0\0\0\0bad"])
def test_uninterpretable_rehashed_cdr_refused(tmp_path, native_rows, payload):
    native_rows[0]["cdr_hex"] = payload.hex()
    native_rows[0]["cdr_sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError, match="CDR"):
        audit(write(tmp_path, native_rows))


def test_extra_cdr_tail_and_nonzero_options_are_refused(tmp_path, native_rows):
    for data in (bytes.fromhex(native_rows[0]["cdr_hex"]) + b"\0" * 4,
                 b"\0\1\0\1" + bytes.fromhex(native_rows[0]["cdr_hex"])[4:]):
        changed = [dict(row) for row in native_rows]
        changed[0]["cdr_hex"] = data.hex()
        changed[0]["cdr_sha256"] = hashlib.sha256(data).hexdigest()
        with pytest.raises(ValueError, match="CDR"):
            audit(write(tmp_path, changed))


def test_changed_message_definition_is_refused(tmp_path, native_rows):
    with pytest.raises(ValueError, match="definition"):
        audit(write(tmp_path, native_rows), DEFINITION.read_bytes() + b"\n")


@pytest.mark.parametrize("field", [
    "px4_publication_us", "px4_sample_us", "control_mode_flags", "filter_fault_flags",
    "gps_check_fail_flags", "solution_status_flags", "pos_horiz_accuracy", "pos_vert_accuracy",
])
def test_structurally_valid_metadata_cannot_disagree_with_cdr(tmp_path, native_rows, field):
    native_rows[0][field] += 1
    with pytest.raises(ValueError, match="field"):
        audit(write(tmp_path, native_rows))


def test_later_sample_fault_claim_is_also_checked(tmp_path, native_rows):
    native_rows[1]["filter_fault_flags"] = 123
    with pytest.raises(ValueError, match="field"):
        audit(write(tmp_path, native_rows))


def test_consistently_relabelled_reset_counter_is_refused(tmp_path, native_rows):
    for row in native_rows:
        if row["kind"] == "sample":
            row["reset_counters"]["reset_count_quat"] += 1
    with pytest.raises(ValueError, match="field"):
        audit(write(tmp_path, native_rows))


def test_ratio_value_and_unavailable_state_must_come_from_cdr(tmp_path, native_rows):
    native_rows[0]["innovation_test_ratios"]["hdg_test_ratio"] += 0.5
    with pytest.raises(ValueError, match="field"):
        audit(write(tmp_path, native_rows))


def test_finite_cdr_ratio_cannot_be_marked_unknown(tmp_path, native_rows):
    native_rows[0]["innovation_test_ratios"]["hdg_test_ratio"] = None
    native_rows[0]["innovation_ratio_available"]["hdg_test_ratio"] = False
    with pytest.raises(ValueError, match="field"):
        audit(write(tmp_path, native_rows))


def test_unknown_cdr_ratio_cannot_be_presented_as_healthy_zero(tmp_path, native_rows):
    row = next(row for row in native_rows if row.get("innovation_ratio_available", {}).get("vel_test_ratio") is False)
    row["innovation_test_ratios"]["vel_test_ratio"] = 0.0
    row["innovation_ratio_available"]["vel_test_ratio"] = True
    with pytest.raises(ValueError, match="field"):
        audit(write(tmp_path, native_rows))


def test_input_changed_after_structural_audit_is_refused(tmp_path, native_rows, monkeypatch):
    path = write(tmp_path, native_rows)
    original = fields.audit_status_source_journal

    def change_after(*args, **kwargs):
        result = original(*args, **kwargs)
        native_rows[0]["filter_fault_flags"] += 1
        write(tmp_path, native_rows)
        return result

    monkeypatch.setattr(fields, "audit_status_source_journal", change_after)
    with pytest.raises(ValueError, match="changed"):
        audit(path)


def test_wrong_decoder_version_refuses_without_fallback(tmp_path, native_rows, monkeypatch):
    monkeypatch.setattr(fields, "version", lambda _name: "0.12.0")
    with pytest.raises(RuntimeError, match="0.11.5"):
        audit(write(tmp_path, native_rows))


def test_writer_failure_is_separate_from_correct_decoded_fields(tmp_path, native_rows):
    result = audit(write(tmp_path, native_rows), exit_code=2)
    assert result["logged_fields_verified"]
    assert not result["writer_completed"]
    assert not result["training_eligible"]


def test_zero_sample_failure_does_not_grant_positive_field_claim(tmp_path):
    path = write(tmp_path, [{"schema": "flydrones.px4_estimator_status_cdr.v1", "kind": "finish",
                            "run_id": "zero-samples", "samples": 0, "status": "failed", "reason": "no_messages"}])
    result = audit(path, exit_code=2)
    assert result["samples"] == 0
    assert not result["logged_fields_verified"]
    assert not result["writer_completed"]


def test_json_carriage_return_whitespace_does_not_change_lf_record_framing(tmp_path, native_rows):
    path = write(tmp_path, native_rows)
    path.write_bytes(path.read_bytes().replace(b",", b",\r ", 1))
    assert fields.audit_status_source_journal(path, observed_writer_exit_code=0).completed
    result = audit(path)
    assert result["samples"] == 3
    assert result["logged_fields_verified"]
