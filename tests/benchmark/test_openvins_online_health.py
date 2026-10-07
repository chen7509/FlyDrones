import json

import numpy as np

from tools.benchmark.openvins_health_contract import CovarianceProfile
from tools.benchmark.openvins_online_shadow import OnlineHealthEvidence, ShadowInput


def camera_ack(sample_ns=3_000_000_000, *, public=True, session_covariance=1e-3):
    return {
        "sequence": 7,
        "kind": "C",
        "sample_ns": sample_ns,
        "receive_ns": 10,
        "start_ns": 11,
        "end_ns": 12,
        "gray_first": 0,
        "internal_initialized": True,
        "public_initialized": public,
        "initializer_time_s": 1.2,
        "state_time_s": sample_ns * 1e-9,
        "last_regular_update_s": max(0.0, sample_ns * 1e-9 - 0.1),
        "zupt_flag_latched": False,
        "has_moved_since_zupt": True,
        "imu_state": [0.0] * 16,
        "imu_covariance15": (np.eye(15) * session_covariance).tolist(),
        "fusion_eligible": False,
        "quality": None,
        "reset_counter": None,
        "acknowledged_ns": 13,
        "source_arrival_ns": 9,
        "dispatch_ns": 9,
    }


def event(kind, sample_ns, arrival_ns):
    from tools.benchmark.openvins_causal_input import raw_profile

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
    else:
        row["camera_info"] = raw_profile()["camera_info"]
    return row


class AckingNative:
    def __init__(self):
        self.sequence = 0

    def send(self, action, pixels=None):
        sequence = self.sequence
        self.sequence += 1
        if action["kind"] != "camera":
            return {"sequence": sequence, "kind": "I"}
        row = camera_ack(action["sample_ns"])
        row["sequence"] = sequence
        return row


def test_online_health_keeps_unqualified_profile_unknown_and_records_exact_row(tmp_path):
    evidence = OnlineHealthEvidence(tmp_path, session_id="session-a", profile=CovarianceProfile())
    result = evidence.observe_camera(camera_ack(), source_health=None)
    final = evidence.finish()

    assert result["quality"] == 0
    assert result["reasons"] == ["covariance_profile_unqualified"]
    assert final["last_quality"] == 0
    assert final["reset_total"] == 0
    assert final["fusion_eligible"] is False
    records = [json.loads(line) for line in (tmp_path / "health-evidence.jsonl").read_text().splitlines()]
    assert records[0]["native_sequence"] == 7
    assert records[0]["health"]["quality"] == 0


def test_shadow_input_projects_real_camera_ack_without_mutating_native_fields(tmp_path):
    evidence = OnlineHealthEvidence(
        tmp_path, session_id="session-a", profile=CovarianceProfile(sim_domain_qualified=True)
    )
    shadow = ShadowInput(AckingNative(), tmp_path, session_id="session-a", now=lambda: 20, health=evidence)
    pixels = b"\xff" * 57600
    shadow.on_record(event("imu", 1_000_000, 1), None)
    shadow.on_record(event("info", 2_000_000, 2), b"PB")
    shadow.on_record(event("rgb", 2_000_000, 3), pixels)
    shadow.on_record(event("imu", 4_000_000, 4), None)

    result = shadow.finish()
    health = evidence.finish()
    assert result["health_last"]["quality"] == 1
    assert health["last_quality"] == 1
    assert shadow.delivery_acks[-1]["quality"] is None
    assert shadow.delivery_acks[-1]["reset_counter"] is None


def test_partial_delivery_failure_latches_negative_health_and_cannot_recover(tmp_path):
    evidence = OnlineHealthEvidence(
        tmp_path, session_id="session-a", profile=CovarianceProfile(sim_domain_qualified=True)
    )
    shadow = ShadowInput(AckingNative(), tmp_path, session_id="session-a", now=lambda: 20, health=evidence)
    shadow.on_record(event("rgb", 2_000_000, 3), b"truncated")
    result = shadow.finish()
    failed = evidence.observe_camera(camera_ack(3_100_000_000), source_health=None)
    health = evidence.finish()

    assert "invalid RGB" in result["failure"]
    assert result["health_last"]["quality"] == -1
    assert failed["quality"] == -1
    assert health["last_quality"] == -1


def test_explicit_process_replacement_increments_reset_once_and_rejects_old_session(tmp_path):
    evidence = OnlineHealthEvidence(
        tmp_path, session_id="session-a", profile=CovarianceProfile(sim_domain_qualified=True)
    )
    assert evidence.observe_camera(camera_ack(), source_health=None)["quality"] == 1
    transition = evidence.replace_session("session-b")
    assert transition["reset_total"] == 1
    assert transition["reset_counter"] == 1
    second = evidence.observe_camera(camera_ack(3_100_000_000), source_health=None)
    assert second["quality"] == 1
    assert second["reset_total"] == 1
    evidence.replace_session("session-c")
    assert evidence.observe_camera(camera_ack(3_200_000_000), source_health=None)["reset_total"] == 2
    final = evidence.finish()
    assert final["session_count"] == 3
    assert final["reset_total"] == 2

