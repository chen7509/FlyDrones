import copy
import importlib.util

import numpy as np
import pytest


def api():
    assert importlib.util.find_spec("tools.benchmark.openvins_causal_input"), "causal input API missing"
    from tools.benchmark import openvins_causal_input

    return openvins_causal_input


def sample(kind, stamp, wall=1_000_000_000):
    row = dict(kind=kind, sample_ns=stamp, arrival_monotonic_ns=wall, observed_sim_ns=stamp)
    if kind == "imu":
        row.update(gyro_flu=[1.0, 2.0, 3.0], accel_flu=[4.0, 5.0, 6.0])
    elif kind == "rgb":
        row.update(width=160, height=120)
    else:
        row.update(camera_info=api().raw_profile()["camera_info"])
    return row


def stream():
    return api().CausalInput(session_id="capture-v2", clock_id="sim-and-monotonic-v2")


def send(s, n, row, **changes):
    return s.accept(
        row,
        sequence=n,
        session_id=changes.get("session_id", "capture-v2"),
        clock_id=changes.get("clock_id", "sim-and-monotonic-v2"),
    )


def test_model_noise_density_roundtrip_and_not_calibrated():
    p = api().raw_profile()
    for key in ["gyro", "accel"]:
        noise = p["noise"][key]
        assert np.allclose(np.square(noise["density_xyz"]) / 0.004, np.square(noise["sample_stddev_xyz"]), rtol=1e-14)
        assert noise["scalar_density_envelope"] == max(noise["density_xyz"])
        assert noise["bias_random_walk"] is None
    assert len(set(p["noise"]["accel"]["sample_stddev_xyz"])) == 2
    assert p["covariance_calibrated"] is False
    assert p["eligible_for_px4_fusion"] is False
    p["camera_info"]["intrinsics_k"][0] = -1
    assert api().raw_profile()["camera_info"]["intrinsics_k"][0] > 0


@pytest.mark.parametrize("order", [("rgb", "info"), ("info", "rgb")])
def test_camera_requires_consumed_strictly_later_imu_and_info(order):
    s = stream()
    assert send(s, 0, sample("imu", 1_000_000))[0]["wm"] == [1.0, -2.0, -3.0]
    assert send(s, 1, sample(order[0], 2_000_000)) == []
    assert send(s, 2, sample(order[1], 2_000_000)) == []
    # Equality is insufficient.
    actions = send(s, 3, sample("imu", 2_000_000))
    assert [a["kind"] for a in actions] == ["imu"]
    actions = send(s, 4, sample("imu", 4_000_000))
    assert [a["kind"] for a in actions] == ["imu", "camera"]
    assert actions[1]["release_sequence"] == 4 and actions[1]["imu_boundary_ns"] == 4_000_000
    assert actions[1]["eligible_for_px4_fusion"] is False
    assert s.finish() == []


def test_late_info_cannot_be_used_before_arrival_and_inputs_are_copied():
    s = stream()
    send(s, 0, sample("imu", 1_000_000))
    send(s, 1, sample("rgb", 2_000_000))
    assert [a["kind"] for a in send(s, 2, sample("imu", 4_000_000))] == ["imu"]
    row = sample("info", 2_000_000, wall=1_005_000_000)
    actions = send(s, 3, row)
    row["camera_info"]["intrinsics_k"][0] = 0
    assert actions[0]["release_wall_ns"] == 1_005_000_000
    assert actions[0]["camera_info"]["intrinsics_k"][0] > 0


@pytest.mark.parametrize("failure", ["duplicate", "gap", "session", "clock", "sequence", "nan", "truth", "calibration"])
def test_faults_latch_and_never_resume(failure):
    s = stream()
    send(s, 0, sample("imu", 1_000_000))
    row, kw, n = sample("imu", 4_000_000), {}, 1
    if failure == "duplicate":
        row["sample_ns"] = 1_000_000
    if failure == "gap":
        row["sample_ns"] = 9_000_000
    if failure == "session":
        kw["session_id"] = "new"
    if failure == "clock":
        kw["clock_id"] = "new"
    if failure == "sequence":
        n = 2
    if failure == "nan":
        row["gyro_flu"][0] = float("nan")
    if failure == "truth":
        row["orientation"] = [1, 0, 0, 0]
    if failure == "calibration":
        row = sample("info", 2_000_000)
        row["camera_info"]["intrinsics_k"][0] += 1
    with pytest.raises(ValueError):
        send(s, n, row, **kw)
    with pytest.raises(ValueError, match="latched"):
        send(s, 1, sample("imu", 4_000_000))


def test_wall_idle_does_not_expire_simulation_pair_and_queue_overflow_is_explicit():
    s = stream()
    send(s, 0, sample("rgb", 2_000_000))
    assert s.tick(1_250_000_001) == []
    s = stream()
    for n in range(8):
        send(s, n, sample("rgb", 2_000_000 + n * 30_000_000))
    with pytest.raises(ValueError, match="capacity"):
        send(s, 8, sample("rgb", 242_000_000))


def test_study_v9_exact_stamp_complement_transitions_before_old_stage_expires():
    """The exact complementary RGB changes dependency stage before expiry."""
    s = stream()
    assert send(s, 0, sample("imu", 1_000_000, wall=26_727_469_680))[0]["kind"] == "imu"
    assert send(s, 1, sample("info", 2_000_000, wall=28_173_399_627)) == []
    assert send(s, 2, sample("rgb", 2_000_000, wall=28_432_165_379)) == []
    actions = send(s, 3, sample("imu", 4_000_000, wall=28_432_743_501))
    assert [action["kind"] for action in actions] == ["imu", "camera"]
    assert actions[1]["sample_ns"] == 2_000_000
    assert actions[1]["rgb_sequence"] == 2 and actions[1]["info_sequence"] == 1


def test_study_v16_same_sim_pair_survives_slow_wall_callbacks():
    s = stream()
    send(s, 0, sample("imu", 1_000_000, wall=75_113_106_330))
    info = sample("info", 2_000_000, wall=76_528_630_909)
    info["observed_sim_ns"] = 3_000_000
    assert send(s, 1, info) == []
    assert s.tick(76_822_710_787) == []
    rgb = sample("rgb", 2_000_000, wall=76_883_730_253)
    rgb["observed_sim_ns"] = 3_000_000
    assert send(s, 2, rgb) == []
    actions = send(s, 3, sample("imu", 4_000_000, wall=76_885_044_839))
    assert [action["kind"] for action in actions] == ["imu", "camera"]
    assert actions[1]["release_sim_ns"] == 4_000_000


def test_reverse_exact_stamp_complement_uses_the_same_stage_transition():
    s = stream()
    send(s, 0, sample("imu", 1_000_000, wall=900_000_000))
    send(s, 1, sample("rgb", 2_000_000, wall=1_000_000_000))
    send(s, 2, sample("info", 2_000_000, wall=1_258_765_752))
    actions = send(s, 3, sample("imu", 4_000_000, wall=1_259_000_000))
    assert [action["kind"] for action in actions] == ["imu", "camera"]
    assert actions[1]["rgb_sequence"] == 1 and actions[1]["info_sequence"] == 2


def test_paired_stage_waiting_for_imu_is_not_expired_by_wall_idle():
    s = stream()
    send(s, 0, sample("imu", 1_000_000, wall=900_000_000))
    send(s, 1, sample("info", 2_000_000, wall=1_000_000_000))
    send(s, 2, sample("rgb", 2_000_000, wall=1_200_000_000))
    assert s.tick(1_450_000_001) == []
    assert s.finish()[0]["reason"] == "later_imu_missing"


def test_simulation_advance_expires_another_unpaired_stamp():
    s = stream()
    send(s, 0, sample("info", 2_000_000, wall=1_000_000_000))
    with pytest.raises(ValueError, match="simulation wait"):
        send(s, 1, sample("rgb", 253_000_001, wall=1_000_000_001))


def test_paired_stage_wall_delay_does_not_change_simulation_contract():
    s = stream()
    send(s, 0, sample("imu", 1_000_000, wall=900_000_000))
    send(s, 1, sample("info", 2_000_000, wall=1_000_000_000))
    send(s, 2, sample("rgb", 2_000_000, wall=1_258_765_752))
    actions = send(s, 3, sample("imu", 4_000_000, wall=1_508_765_753))
    assert [action["kind"] for action in actions] == ["imu", "camera"]


def test_end_of_capture_preserves_missing_boundary_and_metadata():
    s = stream()
    send(s, 0, sample("imu", 1_000_000))
    send(s, 1, sample("rgb", 2_000_000))
    send(s, 2, sample("info", 2_000_000))
    pending = s.finish()
    assert len(pending) == 1 and pending[0]["reason"] == "later_imu_missing"
    assert pending[0]["rgb_sequence"] == 1 and pending[0]["info_sequence"] == 2
    with pytest.raises(ValueError):
        send(s, 3, sample("imu", 4_000_000))


def test_pending_copy_does_not_follow_external_mutation_and_cross_stream_wall_order():
    s = stream()
    send(s, 0, sample("imu", 1_000_000, wall=1_002_000_000))
    row = sample("rgb", 2_000_000, wall=1_001_000_000)
    original = copy.deepcopy(row)
    send(s, 1, row)
    row["sample_ns"] = 100_000_000
    send(s, 2, sample("info", 2_000_000, wall=1_003_000_000))
    actions = send(s, 3, sample("imu", 4_000_000, wall=1_004_000_000))
    assert actions[1]["sample_ns"] == original["sample_ns"]
    assert actions[1]["release_wall_ns"] >= original["arrival_monotonic_ns"]


def test_newly_enqueued_old_sim_camera_is_rejected_at_current_sim_watermark():
    s = stream()
    send(s, 0, sample("imu", 300_000_001))
    s.tick(2_000_000_000)
    with pytest.raises(ValueError, match="simulation wait"):
        send(s, 1, sample("rgb", 2_000_000, wall=1_100_000_000))


def test_info_boolean_cannot_masquerade_as_numeric_calibration():
    s = stream()
    row = sample("info", 2_000_000)
    row["camera_info"]["intrinsics_k"][-1] = True
    with pytest.raises(ValueError, match="calibration"):
        send(s, 0, row)


def test_release_refusal_retains_triggering_imu_and_does_not_commit_it():
    s = stream()
    send(s, 0, sample("rgb", 1_000_000))
    send(s, 1, sample("info", 1_000_000))
    with pytest.raises(ValueError) as caught:
        send(s, 2, sample("imu", 4_000_000))
    disposition = caught.value.disposition
    assert disposition["source_sequence"] == 2 and disposition["input"]["kind"] == "imu"
    assert s._last_sequence == 1 and s._imu_latest is None
    records = s.finish()
    assert len(records) == 2
    assert records[0]["rgb_sequence"] == 0 and records[0]["info_sequence"] == 1
    assert records[1]["source_sequence"] == 2 and records[1]["kind"] == "refused_input"
    disposition["input"]["gyro_flu"][0] = 999
    assert records[1]["input"]["gyro_flu"][0] == 1


def test_integer_vector_overflow_latches_and_retains_refusal():
    s = stream()
    row = sample("imu", 1_000_000)
    row["gyro_flu"][0] = 10**400
    with pytest.raises(ValueError):
        send(s, 0, row)
    with pytest.raises(ValueError, match="latched"):
        send(s, 0, sample("imu", 1_000_000))
    assert s.finish()[0]["source_sequence"] == 0


def test_boolean_distortion_scalar_is_not_a_valid_integer_enum():
    s = stream()
    row = sample("info", 1_000_000)
    row["camera_info"]["distortion_model"] = False
    with pytest.raises(ValueError, match="calibration"):
        send(s, 0, row)
