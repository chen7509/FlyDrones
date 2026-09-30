from pathlib import Path

from flydrones.multitask_curriculum import CurriculumConfig
from flydrones.training import MultiTaskAcceptance


def passing_metrics():
    return {
        "episodes": 1000,
        "full_scale_episodes": 100,
        "collisions": 0,
        "geofence_violations": 0,
        "return_reserve_violations": 0,
        "central_control_commands": 0,
        "exit_success": 0.95,
        "tracking_success": 0.95,
        "tracking_rmse_m": 0.75,
        "tracking_loss_fraction": 0.05,
        "search_coverage": 0.95,
        "duplicate_coverage": 0.20,
        "formation_rmse_m": 0.40,
        "gate_success": 0.90,
        "gate_contacts": 0,
        "task_release_s": 3.0,
        "task_reopen_s": 3.2,
        "task_reassign_s": 5.0,
        "compound_success": 0.90,
        "maximum_skill_drop": 0.02,
    }


def test_acceptance_requires_every_safety_and_task_gate():
    gate = MultiTaskAcceptance.spec_defaults()
    assert gate.evaluate(passing_metrics()).passed
    unsafe = passing_metrics()
    unsafe["collisions"] = 1
    report = gate.evaluate(unsafe)
    assert not report.passed
    assert "collisions" in report.failures


def test_missing_and_nonfinite_metrics_fail_closed_in_key_order():
    gate = MultiTaskAcceptance.spec_defaults()
    metrics = passing_metrics()
    del metrics["exit_success"]
    metrics["tracking_rmse_m"] = float("nan")
    assert gate.evaluate(metrics).failures == ("exit_success", "tracking_rmse_m")


def test_canonical_config_contains_strict_profiles_and_frozen_layers():
    config = CurriculumConfig.load(Path("configs/multitask_training.yaml"))
    assert set(config.profiles) == {"smoke", "desktop", "full"}
    assert config.frozen == (
        "malecns_reflex",
        "safety_projector",
        "px4_inner_loop",
    )
    assert config.deployment["central_control_commands_allowed"] == 0
    assert 100 not in {
        fleet
        for profile in (config.profiles["smoke"], config.profiles["desktop"])
        for stage in profile
        for fleet in stage.fleets
    }
    assert 100 in {
        fleet for stage in config.profiles["full"] for fleet in stage.fleets
    }
