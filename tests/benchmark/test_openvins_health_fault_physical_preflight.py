from pathlib import Path

import pytest

from tools.benchmark.openvins_health_physical_preflight import run_args


def source_contract(tmp_path):
    return {
        "profiles": {
            "motion_profile": "supported-ready-v1",
            "physics_trace_profile": "substep-ready-v1",
            "reference_fault_profile": None,
            "source_fanout_profile": "ready-shadow-heartbeat-estimator-v1",
            "motion_intent_profile": "native-beginning-zupt-v1",
        },
        "inputs": {
            "shadow_binary": str(tmp_path / "old-probe"),
            "shadow_config": str(tmp_path / "config"),
            "reference_module": str(tmp_path / "reference.so"),
        },
        "reference_sha256": "a" * 64,
    }


def test_fault_plan_predeclares_distinct_profiles_seeds_and_expected_outcomes():
    from tools.benchmark.openvins_health_fault_physical_preflight import fault_plan

    assert fault_plan() == [
        {
            "run_id": "source-loss-seed-27301",
            "role": "source_loss",
            "seed": 27301,
            "health_fault_profile": "imu-source-loss-after-8s-v1",
            "expected_capture_status": "capture_failed",
            "expected_command_returncode": 2,
        },
        {
            "run_id": "native-restart-seed-27302",
            "role": "native_restart",
            "seed": 27302,
            "health_fault_profile": "native-restart-after-8s-v1",
            "expected_capture_status": "capture_completed",
            "expected_command_returncode": 0,
        },
    ]


@pytest.mark.parametrize(
    "profile",
    ["imu-source-loss-after-8s-v1", "native-restart-after-8s-v1"],
)
def test_fault_run_args_preserves_workload_and_declares_fault(tmp_path, profile):
    from tools.benchmark.openvins_health_fault_physical_preflight import fault_run_args

    base = run_args(
        output=tmp_path / "capture-v1",
        source_contract=source_contract(tmp_path),
        health_binary=tmp_path / "health-probe",
        policy_path=tmp_path / "policy.json",
        binding_path=tmp_path / "binding.json",
        execution_path=tmp_path / "execution.json",
        seed=27301,
    )
    selected = fault_run_args(base, profile)
    assert selected.output == Path(tmp_path / "capture-v1")
    assert selected.health_fault_profile == profile
    assert selected.health_profile == "px4-d6f12ad-gate-floor-v1"
    assert selected.simulation_seed == 27301
    assert selected.motion_profile == "supported-ready-v1"
    assert selected.physics_trace_profile == "substep-ready-v1"
    assert selected.motion_intent_profile == "native-beginning-zupt-v1"


def test_fault_run_args_rejects_unknown_profile(tmp_path):
    from tools.benchmark.openvins_health_fault_physical_preflight import fault_run_args

    base = run_args(
        output=tmp_path / "capture-v1",
        source_contract=source_contract(tmp_path),
        health_binary=tmp_path / "health-probe",
        policy_path=tmp_path / "policy.json",
        binding_path=tmp_path / "binding.json",
        execution_path=tmp_path / "execution.json",
        seed=27301,
    )
    with pytest.raises(ValueError, match="health fault profile"):
        fault_run_args(base, "typo")
