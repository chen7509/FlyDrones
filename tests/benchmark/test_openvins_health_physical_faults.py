import json

import numpy as np
import pytest

from tools.benchmark.openvins_health_contract import CovarianceProfile
from tools.benchmark.openvins_online_shadow import OnlineHealthEvidence


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


class FakeClient:
    def __init__(self, session_index, *, exit_code=0):
        self.session_index = session_index
        self.sequence = 0
        self.exit_code = exit_code
        self.finished = False

    def send(self, action, pixels=None):
        sequence = self.sequence
        self.sequence += 1
        if action["kind"] != "camera":
            return {"sequence": sequence, "kind": "I"}
        sample = action["sample_ns"]
        return {
            "sequence": sequence,
            "kind": "C",
            "sample_ns": sample,
            "receive_ns": 10,
            "start_ns": 11,
            "end_ns": 12,
            "gray_first": 0,
            "internal_initialized": True,
            "public_initialized": True,
            "initializer_time_s": sample * 1e-9 - 0.5,
            "state_time_s": sample * 1e-9,
            "last_regular_update_s": sample * 1e-9 - 0.1,
            "zupt_flag_latched": False,
            "has_moved_since_zupt": True,
            "imu_state": [0.0, 0.0, 0.0, 1.0] + [0.0] * 12,
            "imu_covariance15": (np.eye(15) * 1e-3).tolist(),
            "fusion_eligible": False,
            "quality": None,
            "reset_counter": None,
        }

    def finish(self):
        if self.finished:
            raise RuntimeError("client already finished")
        self.finished = True
        return {
            "exit": self.exit_code,
            "accepted": self.sequence,
            "failure": None,
            "fusion_eligible": False,
            "quality": None,
            "reset_counter": None,
        }

    def send_motion_intent(self, action):
        return {"kind": "M", "sample_ns": action["sample_ns"], "session_index": self.session_index}


def test_fault_profiles_are_fixed_and_unknown_values_fail_closed():
    from tools.benchmark.openvins_health_physical_faults import fault_profile

    source = fault_profile("imu-source-loss-after-8s-v1")
    restart = fault_profile("native-restart-after-8s-v1")
    assert source == {
        "name": "imu-source-loss-after-8s-v1",
        "trigger_sample_ns": 8_000_000_000,
        "source_kind": "imu",
        "source_loss_wall_timeout_ns": 2_000_000_000,
    }
    assert restart == {
        "name": "native-restart-after-8s-v1",
        "trigger_sample_ns": 8_000_000_000,
        "source_kind": None,
        "source_loss_wall_timeout_ns": None,
    }
    with pytest.raises(ValueError, match="health fault profile"):
        fault_profile("typo")


def test_source_loss_drops_only_estimator_imu_and_latches_negative_health(tmp_path):
    from tools.benchmark.openvins_health_physical_faults import ManagedHealthShadow

    clock = iter([1, 2, 3, 4, 2_000_000_005])
    health = OnlineHealthEvidence(tmp_path, session_id="fault-session-0", profile=CovarianceProfile())
    manager = ManagedHealthShadow(
        tmp_path,
        profile="imu-source-loss-after-8s-v1",
        health=health,
        client_factory=lambda index, session_id: FakeClient(index),
        now=lambda: next(clock),
    )
    manager.on_record(event("imu", 1_000_000, 1), None)
    manager.on_record(event("info", 2_000_000, 2), b"PB")
    manager.on_record(event("rgb", 2_000_000, 3), b"\xff" * 57600)
    manager.on_record(event("imu", 8_000_000_000, 4), None)
    assert manager.failure is None
    manager.on_record(event("info", 8_100_000_000, 5), b"PB")
    result = manager.finish()
    health_result = health.finish()

    assert result["failure"] == "source_loss:imu"
    assert result["dropped_source_records"] == 1
    assert result["sessions"][0]["native"]["exit"] == 0
    assert health_result["last_quality"] == -1
    assert health_result["last_health"]["reasons"] == ["source_failure"]
    records = [json.loads(line) for line in (tmp_path / "health-fault-events.jsonl").read_text().splitlines()]
    assert [row["event"] for row in records] == ["source_loss_started", "source_loss_detected"]
    assert all(row["fusion_eligible"] is False for row in records)


def test_native_restart_replaces_session_once_and_continues_with_reset_one(tmp_path):
    from tools.benchmark.openvins_health_physical_faults import ManagedHealthShadow

    clients = []
    replacements = []
    finished = []

    def factory(index, session_id):
        assert session_id == f"fault-session-{index}"
        client = FakeClient(index)
        clients.append(client)
        return client

    health = OnlineHealthEvidence(tmp_path, session_id="fault-session-0", profile=CovarianceProfile())
    manager = ManagedHealthShadow(
        tmp_path,
        profile="native-restart-after-8s-v1",
        health=health,
        client_factory=factory,
        client_finisher=lambda client: (finished.append(client.session_index), client.finish())[1],
        now=lambda: 20,
    )
    manager.set_session_replacement_callback(
        lambda session_id, reset_total: replacements.append((session_id, reset_total))
    )
    manager.on_record(event("imu", 1_000_000, 1), None)
    manager.on_record(event("imu", 8_000_000_000, 2), None)
    manager.on_record(event("info", 8_002_000_000, 3), b"PB")
    manager.on_record(event("rgb", 8_002_000_000, 4), b"\xff" * 57600)
    manager.on_record(event("imu", 8_004_000_000, 5), None)
    result = manager.finish()
    health_result = health.finish()

    assert len(clients) == 2
    assert all(client.finished for client in clients)
    assert finished == [0, 1]
    assert replacements == [("fault-session-1", 1)]
    assert result["failure"] is None
    assert result["restart_count"] == 1
    assert len(result["sessions"]) == 2
    assert health_result["session_count"] == 2
    assert health_result["reset_total"] == 1
    assert health_result["reset_counter"] == 1
    assert health_result["last_quality"] == 0
    assert health_result["last_health"]["reasons"] == ["covariance_profile_unqualified"]
    transitions = [
        json.loads(line)
        for line in (tmp_path / "health-evidence.jsonl").read_text().splitlines()
        if '"session_replacement"' in line
    ]
    assert transitions[0]["transition"]["reset_total"] == 1


def test_managed_shadow_routes_motion_intent_to_the_current_native_session(tmp_path):
    from tools.benchmark.openvins_health_physical_faults import ManagedHealthShadow

    health = OnlineHealthEvidence(tmp_path, session_id="fault-session-0", profile=CovarianceProfile())
    manager = ManagedHealthShadow(
        tmp_path,
        profile="native-restart-after-8s-v1",
        health=health,
        client_factory=lambda index, session_id: FakeClient(index),
        now=lambda: 20,
    )
    assert manager.send_motion_intent({"sample_ns": 1})["session_index"] == 0
    manager.on_record(event("imu", 8_000_000_000, 2), None)
    assert manager.send_motion_intent({"sample_ns": 8_000_000_001})["session_index"] == 1
    manager.finish()
    health.finish()


def test_restart_spawn_failure_latches_native_failure_and_keeps_first_session_evidence(tmp_path):
    from tools.benchmark.openvins_health_physical_faults import ManagedHealthShadow

    def factory(index, session_id):
        if index == 1:
            raise RuntimeError("restart spawn refused")
        return FakeClient(index)

    health = OnlineHealthEvidence(tmp_path, session_id="fault-session-0", profile=CovarianceProfile())
    manager = ManagedHealthShadow(
        tmp_path,
        profile="native-restart-after-8s-v1",
        health=health,
        client_factory=factory,
        now=lambda: 20,
    )
    manager.on_record(event("imu", 1_000_000, 1), None)
    manager.on_record(event("imu", 8_000_000_000, 2), None)
    result = manager.finish()
    health_result = health.finish()

    assert "restart spawn refused" in result["failure"]
    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["native"]["exit"] == 0
    assert health_result["last_quality"] == -1
    assert health_result["last_health"]["reasons"] == ["native_restart_failed"]
