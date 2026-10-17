from pathlib import Path

from tools.benchmark.openvins_health_physical_preflight import cohort_plan, run_args


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


def test_cohort_plan_freezes_development_before_distinct_held_out_seeds():
    plan = cohort_plan()
    assert plan == [
        {"run_id": "development-seed-27101", "role": "development", "seed": 27101},
        {"run_id": "held-out-seed-27111", "role": "held_out", "seed": 27111},
        {"run_id": "held-out-seed-27112", "role": "held_out", "seed": 27112},
        {"run_id": "held-out-seed-27113", "role": "held_out", "seed": 27113},
    ]
    assert len({row["seed"] for row in plan}) == len(plan)

    assert cohort_plan("compatibility-retry-v2") == [
        {"run_id": "development-seed-27201", "role": "development", "seed": 27201},
        {"run_id": "held-out-seed-27211", "role": "held_out", "seed": 27211},
        {"run_id": "held-out-seed-27212", "role": "held_out", "seed": 27212},
        {"run_id": "held-out-seed-27213", "role": "held_out", "seed": 27213},
    ]
    assert cohort_plan("propagated-ekf2-v3") == [
        {"run_id": "development-seed-27401", "role": "development", "seed": 27401},
        {"run_id": "held-out-seed-27411", "role": "held_out", "seed": 27411},
        {"run_id": "held-out-seed-27412", "role": "held_out", "seed": 27412},
        {"run_id": "held-out-seed-27413", "role": "held_out", "seed": 27413},
    ]
    assert cohort_plan("propagated-ekf2-aligned-v4") == [
        {"run_id": "development-seed-27501", "role": "development", "seed": 27501},
        {"run_id": "held-out-seed-27511", "role": "held_out", "seed": 27511},
        {"run_id": "held-out-seed-27512", "role": "held_out", "seed": 27512},
        {"run_id": "held-out-seed-27513", "role": "held_out", "seed": 27513},
    ]
    assert cohort_plan("propagated-ekf2-grid-v5") == [
        {"run_id": "development-seed-27601", "role": "development", "seed": 27601},
        {"run_id": "held-out-seed-27611", "role": "held_out", "seed": 27611},
        {"run_id": "held-out-seed-27612", "role": "held_out", "seed": 27612},
        {"run_id": "held-out-seed-27613", "role": "held_out", "seed": 27613},
    ]


def test_run_args_replaces_binary_and_binds_health_profile_seed(tmp_path):
    args = run_args(
        output=tmp_path / "capture-v1",
        source_contract=source_contract(tmp_path),
        health_binary=tmp_path / "health-probe",
        policy_path=tmp_path / "policy.json",
        binding_path=tmp_path / "binding.json",
        execution_path=tmp_path / "execution.json",
        seed=27111,
    )
    assert args.shadow_binary == Path(tmp_path / "health-probe")
    assert args.health_profile == "px4-d6f12ad-gate-floor-v1"
    assert args.simulation_seed == 27111
    assert args.motion_intent_profile == "native-beginning-zupt-v1"
    assert args.startup_preflight is False
