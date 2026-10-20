import copy

import pytest


def state(sample_ns, *, zupt, bias_z, pz, vz, public=False):
    return {
        "kind": "C",
        "sequence": sample_ns // 1_000_000,
        "sample_ns": sample_ns,
        "receive_ns": sample_ns + 1,
        "start_ns": sample_ns + 2,
        "end_ns": sample_ns + 3,
        "internal_initialized": True,
        "public_initialized": public,
        "initializer_time_s": 2.4,
        "state_time_s": sample_ns / 1e9,
        "last_regular_update_s": sample_ns / 1e9 if public else -1,
        "zupt_flag_latched": zupt,
        "has_moved_since_zupt": public,
        "imu_state": [0, 0, 0, 1, 0, 0, pz, 0, 0, vz, 0, 0, 0, 0, 0, bias_z],
        "fusion_eligible": False,
        "quality": None,
        "reset_counter": None,
    }


def truth(sample_ns, *, pz, vz, az):
    return {
        "sim_ns": sample_ns,
        "position": [0, 0, pz],
        "velocity_world": [0, 0, vz],
        "accel_world": [0, 0, az],
        "angular_world": [0, 0, 0],
        "quaternion_xyzw": [1, 0, 0, 0],
        "truth_for_fixture_audit_only": True,
    }


def fixture():
    states = [
        state(2_400_000_000, zupt=False, bias_z=0.00045, pz=0.0, vz=0.0),
        state(2_500_000_000, zupt=True, bias_z=0.00070, pz=0.0, vz=0.0),
        state(2_600_000_000, zupt=True, bias_z=0.00048, pz=0.0, vz=0.0),
        state(2_700_000_000, zupt=True, bias_z=-0.027, pz=-0.016, vz=-0.029),
        state(2_800_000_000, zupt=True, bias_z=-0.098, pz=-0.059, vz=-0.107),
        state(2_900_000_000, zupt=True, bias_z=-0.172, pz=-0.103, vz=-0.188),
        state(3_300_000_000, zupt=False, bias_z=-0.172, pz=-0.147, vz=-0.041, public=True),
    ]
    truths = [
        truth(2_400_000_000, pz=0.0, vz=0.0, az=0.0),
        truth(2_500_000_000, pz=0.0, vz=0.0, az=0.0),
        truth(2_600_000_000, pz=0.0, vz=0.0, az=0.0),
        truth(2_700_000_000, pz=0.00024, vz=0.0087, az=0.210),
        truth(2_800_000_000, pz=0.00254, vz=0.0400, az=0.401),
        truth(2_900_000_000, pz=0.00880, vz=0.0867, az=0.519),
        truth(3_300_000_000, pz=0.08794, vz=0.3019, az=0.432),
    ]
    log = "\n".join(
        [
            "[ZUPT]: passed disparity (0.000 < 0.500, 37 features)",
            "[ZUPT]: accepted |v_IinG| = 0.001 (chi2 0.212 < 0.000)",
            "[ZUPT]: passed disparity (0.238 < 0.500, 36 features)",
            "[ZUPT]: accepted |v_IinG| = 0.107 (chi2 5663.846 < 0.000)",
            "[ZUPT]: failed disparity (0.563 > 0.500, 36 features)",
            "[ZUPT]: rejected |v_IinG| = 0.188 (chi2 6359.960 > 0.000)",
            "[TIME]: 0.0001 seconds for MSCKF update (0 feats)",
            "[TIME]: 0.0001 seconds for MSCKF update (1 feats)",
            "[TIME]: 0.0000 seconds for SLAM update (0 feats)",
            "[TIME]: 0.0000 seconds for SLAM update (0 feats)",
        ]
    )
    return states, truths, log


def test_diagnosis_identifies_motion_during_zupt_and_bias_change():
    from tools.benchmark.diagnose_openvins_zupt_bias import diagnose

    states, truths, log = fixture()
    result = diagnose(states, truths, log, anchor_ns=2_621_000_000)
    assert result["zupt_state_count"] == 5
    assert result["zupt_states_after_motion_anchor"] == 3
    assert result["first_motion_accepted_as_zupt_ns"] == 2_700_000_000
    assert result["bias_z_before_motion"] == pytest.approx(0.00048)
    assert result["bias_z_after_accepted_motion"] == pytest.approx(-0.172)
    assert result["bias_z_change_during_motion_zupt"] == pytest.approx(-0.17248)
    assert result["native_log"]["accepted_zupt_count"] == 2
    assert result["native_log"]["accepted_over_speed_count"] == 1
    assert result["native_log"]["msckf_nonzero_update_count"] == 1
    assert result["classification"] == "physical-motion-accepted-as-zupt-with-accelerometer-bias-corruption"
    assert result["entire_terminal_drift_single_cause_proven"] is False


def test_preinitialization_state_without_truth_is_retained_but_not_scored():
    from tools.benchmark.diagnose_openvins_zupt_bias import diagnose

    states, truths, log = fixture()
    pre = copy.deepcopy(states[0])
    pre.update(
        sequence=1,
        sample_ns=2_000_000,
        receive_ns=2_000_001,
        start_ns=2_000_002,
        end_ns=2_000_003,
        internal_initialized=False,
        public_initialized=False,
        initializer_time_s=-1,
        state_time_s=-1,
        imu_state=None,
    )
    states.insert(0, pre)
    result = diagnose(states, truths, log, anchor_ns=2_621_000_000)
    assert result["state_count"] == 8
    assert result["initialized_state_count"] == 7


@pytest.mark.parametrize("mutation", ["duplicate", "missing_truth", "nan_bias", "bad_truth_scope"])
def test_diagnosis_rejects_invalid_fixed_evidence(mutation):
    from tools.benchmark.diagnose_openvins_zupt_bias import diagnose

    states, truths, log = fixture()
    if mutation == "duplicate":
        states.insert(1, copy.deepcopy(states[0]))
    elif mutation == "missing_truth":
        truths.pop(3)
    elif mutation == "nan_bias":
        states[3]["imu_state"][15] = float("nan")
    else:
        truths[3]["truth_for_fixture_audit_only"] = False
    with pytest.raises(ValueError):
        diagnose(states, truths, log, anchor_ns=2_621_000_000)
