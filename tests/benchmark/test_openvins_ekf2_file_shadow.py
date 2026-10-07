import json
import socket
from unittest import mock

import numpy as np
import pytest

from tools.benchmark.openvins_causal_input import raw_profile
from tools.benchmark.openvins_ekf2_file_shadow import FileOnlyEkf2ShadowEvidence
from tools.benchmark.openvins_online_shadow import ShadowInput


def declaration(session="session-a"):
    return {
        "schema": "openvins-ekf2-file-shadow-declaration-v1",
        "source_journal_sha256": "a" * 64,
        "native_binary_sha256": "b" * 64,
        "native_config_sha256": "c" * 64,
        "runtime_snapshot_sha256": "d" * 64,
        "estimator_session_id": session,
        "clock_session_id": "shadow-clock-a",
        "publisher_session_id": "file-publisher-a",
        "health_profile": "px4-d6f12ad-gate-floor-v1",
        "sim_domain_qualified": True,
        "max_sample_age_ns": 2_000_000_000,
        "expected_camera_rate_hz": 10,
        "expected_propagated_rate_hz": 50,
        "candidate_output": "ekf2-candidates.jsonl",
        "fusion_rate_qualified": False,
    }


def source(kind, sample_ns, arrival_ns):
    row = {
        "kind": kind,
        "sample_ns": sample_ns,
        "arrival_monotonic_ns": arrival_ns,
        "observed_sim_ns": sample_ns,
    }
    if kind == "imu":
        row.update(gyro_flu=[0.0, 0.0, 0.0], accel_flu=[0.0, 0.0, 9.81])
    elif kind == "rgb":
        row.update(width=160, height=120)
    elif kind == "info":
        row["camera_info"] = raw_profile()["camera_info"]
    return row


class Native:
    def __init__(self, *, fail=False):
        self.sequence = 0
        self.fail = fail

    def send(self, action, pixels=None):
        if self.fail and action["kind"] == "camera":
            raise TimeoutError("native deadline")
        sequence = self.sequence
        self.sequence += 1
        if action["kind"] == "imu":
            return {"sequence": sequence, "kind": "I"}
        sample = action["sample_ns"]
        arrival = action["source_arrival_ns"]
        return {
            "sequence": sequence,
            "kind": "C",
            "sample_ns": sample,
            "receive_ns": arrival + 1,
            "start_ns": arrival + 2,
            "end_ns": arrival + 3,
            "gray_first": pixels[0],
            "internal_initialized": True,
            "public_initialized": True,
            "initializer_time_s": 1.0,
            "state_time_s": sample * 1e-9,
            "last_regular_update_s": sample * 1e-9 - 0.1,
            "zupt_flag_latched": False,
            "has_moved_since_zupt": True,
            "imu_state": [0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0, 0.2, -0.1, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "imu_covariance15": (np.eye(15) * 1e-3).tolist(),
            "fusion_eligible": False,
            "quality": None,
            "reset_counter": None,
            "acknowledged_ns": arrival + 4,
            "source_arrival_ns": arrival,
            "dispatch_ns": arrival,
        }


def deliver_camera(shadow, *, base_sample=2_000_000_000, base_arrival=10_000_000_000):
    shadow.on_record(source("imu", base_sample - 4_000_000, base_arrival - 4_000_000), None)
    shadow.on_record(source("imu", base_sample, base_arrival - 1), None)
    shadow.on_record(source("info", base_sample, base_arrival), b"PB")
    shadow.on_record(source("rgb", base_sample, base_arrival + 1), b"\xff" * 57_600)
    shadow.on_record(source("imu", base_sample + 4_000_000, base_arrival + 4_000_000), None)


def test_actual_shadow_ack_creates_file_only_candidate_with_separate_clocks(tmp_path):
    native_dir = tmp_path / "native"
    native_dir.mkdir()
    with mock.patch.object(socket, "socket", side_effect=AssertionError("network attempted")):
        evidence = FileOnlyEkf2ShadowEvidence(tmp_path, declaration())
        shadow = ShadowInput(Native(), native_dir, session_id="session-a", now=lambda: 10_100_000_000, health=evidence)
        deliver_camera(shadow)
        shadow_result = shadow.finish()
        result = evidence.finish()
    rows = [json.loads(line) for line in (tmp_path / "ekf2-candidates.jsonl").read_text().splitlines()]
    assert shadow_result["failure"] is None
    assert result["candidate_count"] == 1 and result["refusal_count"] == 0
    assert rows[0]["composition"]["status"] == "candidate"
    assert rows[0]["timing"] == {
        "capture_sample_ns": 2_000_000_000,
        "source_arrival_ns": 10_000_000_001,
        "dispatch_ns": 10_000_000_001,
        "native_receive_ns": 10_000_000_002,
        "native_start_ns": 10_000_000_003,
        "native_end_ns": 10_000_000_004,
        "acknowledged_ns": 10_000_000_005,
    }
    assert rows[0]["composition"]["candidate"]["fusion_eligible"] is False
    assert result["receiver_shadow_rate_qualified"] is False
    assert result["fusion_rate_qualified"] is False


def test_source_loss_and_native_timeout_latch_without_candidate(tmp_path):
    source_dir = tmp_path / "source-loss"
    source_dir.mkdir()
    source_evidence = FileOnlyEkf2ShadowEvidence(source_dir, declaration())
    assert source_evidence.fail("source_failure")["quality"] == -1
    assert source_evidence.finish()["candidate_count"] == 0

    timeout_dir = tmp_path / "timeout"
    timeout_dir.mkdir()
    native_dir = timeout_dir / "native"
    native_dir.mkdir()
    timeout_evidence = FileOnlyEkf2ShadowEvidence(timeout_dir, declaration())
    shadow = ShadowInput(Native(fail=True), native_dir, session_id="session-a", now=lambda: 10_100_000_000, health=timeout_evidence)
    deliver_camera(shadow)
    assert shadow.finish()["failure"] is not None
    result = timeout_evidence.finish()
    assert result["candidate_count"] == 0 and result["last_quality"] == -1


def test_explicit_session_replacement_increments_reset(tmp_path):
    evidence = FileOnlyEkf2ShadowEvidence(tmp_path, declaration())
    first_dir = tmp_path / "first"
    first_dir.mkdir()
    first = ShadowInput(Native(), first_dir, session_id="session-a", now=lambda: 10_100_000_000, health=evidence)
    deliver_camera(first)
    first.finish()
    transition = evidence.replace_session("session-b")
    assert transition["reset_counter"] == 1
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second = ShadowInput(Native(), second_dir, session_id="session-b", now=lambda: 20_100_000_000, health=evidence)
    deliver_camera(second, base_sample=12_000_000_000, base_arrival=20_000_000_000)
    second.finish()
    result = evidence.finish()
    rows = [json.loads(line) for line in (tmp_path / "ekf2-candidates.jsonl").read_text().splitlines()]
    assert result["candidate_count"] == 2 and result["reset_counter"] == 1
    assert rows[-1]["composition"]["candidate"]["fields"]["reset_counter"] == 1


def test_declaration_is_strict_and_precedes_outputs(tmp_path):
    bad = declaration()
    bad["candidate_output"] = "../escape.jsonl"
    with pytest.raises(ValueError):
        FileOnlyEkf2ShadowEvidence(tmp_path, bad)
    assert not any(tmp_path.iterdir())
