import json
from dataclasses import replace

import pytest
import torch
from test_learning_roles import config as _config
from test_learning_roles import inert_backends as _inert
from test_learning_roles import save_session

from flydrones.connectome_training import curriculum_session as sessions
from flydrones.connectome_training import role_comparison as comparison
from flydrones.connectome_training import trainer

config = _config
inert_backends = _inert


def three_sequences(config):
    return replace(config, stages=(replace(config.stages[0], train_seeds=(11, 12, 13), epochs_per_batch=2),))


def build(config):
    return sessions.ConnectomeCurriculumSession(
        three_sequences(config), device="cpu", dynamics_format="frozen-drive-exponential-v1"
    )


def test_actual_six_optimizer_returns_are_distinct_from_two_epochs(config):
    current = build(config)
    result = current.train_batch(current.config.stages[0], 4)
    counts = result["training_effort_lifetime"]["counts"]
    assert result["updates"] == 2 and result["environment_steps"] == 48
    assert counts == dict(
        epoch_calls_started=2,
        epoch_calls_returned=2,
        sequence_calls_started=6,
        backward_sequences_returned=6,
        backward_frames_returned=48,
        optimizer_step_calls_started=6,
        optimizer_step_calls_returned=6,
        optimizer_step_calls_raised=0,
        frames_at_returned_optimizer_steps=48,
    )
    current.evaluate(current.config.stages[0])
    assert current.training_effort == result["training_effort_lifetime"]


def test_real_optimizer_update_then_raise_retains_unreturned_prefix(config, monkeypatch):
    current = build(config)
    actual = current.optimizer.step
    calls = []

    def update_then_raise(*args, **kwargs):
        actual(*args, **kwargs)
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("after third actual update")

    monkeypatch.setattr(current.optimizer, "step", update_then_raise)
    before = current.model.readout.detach().clone()
    with pytest.raises(RuntimeError, match="third actual"):
        current.train_batch(current.config.stages[0], 5)
    assert not torch.equal(before, current.model.readout)
    counts = current.training_effort["counts"]
    assert counts["epoch_calls_started"] == 1 and counts["epoch_calls_returned"] == 0
    assert counts["backward_frames_returned"] == 24
    assert counts["optimizer_step_calls_started"] == 3 and counts["optimizer_step_calls_returned"] == 2
    assert counts["optimizer_step_calls_raised"] == 1 and counts["frames_at_returned_optimizer_steps"] == 16


def test_restore_never_rewinds_lifetime_and_fresh_resume_claims_no_old_work(config, tmp_path):
    current = build(config)
    current.train_batch(current.config.stages[0], 4)
    save_session(current, tmp_path / "checkpoint")
    current.train_batch(current.config.stages[0], 5)
    snapshot = current.training_effort
    current.restore_checkpoint(tmp_path / "checkpoint")
    assert current.training_effort == snapshot and snapshot["counts"]["optimizer_step_calls_returned"] == 12
    fresh = build(config)
    fresh.restore_checkpoint(tmp_path / "checkpoint")
    assert all(v == 0 for v in fresh.training_effort["counts"].values())
    snapshot["counts"]["optimizer_step_calls_returned"] = -999
    assert current.training_effort["counts"]["optimizer_step_calls_returned"] == 12


def test_actual_role_producer_persists_each_lifetime(config, tmp_path):
    result = comparison.run_role_comparison(three_sequences(config), tmp_path / "roles", max_batches=1, device="cpu")
    assert result["status"] == "FINISHED" and len(result["variants"]) == 3
    for row in result["variants"]:
        assert row["training_effort_lifetime"]["counts"]["optimizer_step_calls_returned"] == 6
        assert row["state"]["global_updates"] == 2
    assert json.loads((tmp_path / "roles/comparison.json").read_bytes()) == result
    assert result["training_success_verified"] is False and result["flight_eligible"] is False


def test_actual_role_step_failure_persists_partial_work_before_release(config, tmp_path, monkeypatch):
    actual = sessions.ConnectomeCurriculumSession

    def construct(*args, **kwargs):
        current = actual(*args, **kwargs)
        step = current.optimizer.step
        calls = []

        def injected(*a, **k):
            step(*a, **k)
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("actual prefix then error")

        monkeypatch.setattr(current.optimizer, "step", injected)
        return current

    monkeypatch.setattr(comparison, "ConnectomeCurriculumSession", construct)
    with pytest.raises(RuntimeError, match="actual prefix"):
        comparison.run_role_comparison(three_sequences(config), tmp_path / "roles", max_batches=1, device="cpu")
    record = json.loads((tmp_path / "roles/comparison.json").read_bytes())
    assert record["status"] == "ERROR" and len(record["variants"]) == 1
    counts = record["variants"][0]["training_effort_lifetime"]["counts"]
    assert counts["optimizer_step_calls_started"] == 3 and counts["optimizer_step_calls_returned"] == 2
    assert counts["optimizer_step_calls_raised"] == 1


def test_accounting_keeps_actual_two_epoch_trajectory_and_metrics_identical(config):
    counted, reference = build(config), build(config)
    data = counted.datasets[counted.config.stages[0].id][0]
    for _ in range(2):
        a = trainer.train_epoch(counted.model, data, counted.optimizer, 4, effort=counted._training_effort)
        b = trainer.train_epoch(reference.model, data, reference.optimizer, 4)
        assert a == b
        assert all(torch.equal(p, q) for p, q in zip(counted.model.parameters(), reference.model.parameters(), strict=True))
    assert counted.training_effort["counts"]["optimizer_step_calls_returned"] == 6


def test_late_input_error_counts_first_step_without_epoch_return(config):
    current = build(config)
    data = current.datasets[current.config.stages[0].id][0]
    data[1].frames[0].depth_m[0, 0] = -1
    with pytest.raises(ValueError, match="positive finite"):
        current.train_batch(current.config.stages[0], 1)
    counts = current.training_effort["counts"]
    assert counts["sequence_calls_started"] == 2 and counts["backward_sequences_returned"] == 1
    assert counts["optimizer_step_calls_returned"] == 1 and counts["frames_at_returned_optimizer_steps"] == 8
    assert counts["epoch_calls_returned"] == 0 and counts["optimizer_step_calls_raised"] == 0


def test_partial_window_backward_is_explicitly_not_completed_frame_credit(config, monkeypatch):
    current = build(config)
    actual = current.model.forward_sequence
    calls = []

    def late_failure(*a, **k):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("third window before completion")
        return actual(*a, **k)

    monkeypatch.setattr(current.model, "forward_sequence", late_failure)
    current.truncate_steps = 2
    # Direct trainer boundary: session rejects truncate baseline drift by design.
    with pytest.raises(RuntimeError, match="third window"):
        trainer.train_epoch(
            current.model, current.datasets[current.config.stages[0].id][0], current.optimizer, 2, effort=current._training_effort
        )
    assert any(p.grad is not None for p in current.model.parameters())
    counts = current.training_effort["counts"]
    assert counts["sequence_calls_started"] == 1 and counts["backward_frames_returned"] == 0
    assert counts["optimizer_step_calls_started"] == 0


def test_baseexception_step_is_recorded_and_reraised(config, monkeypatch):
    current = build(config)

    def interrupt(*a, **k):
        raise KeyboardInterrupt("step interrupted")

    monkeypatch.setattr(current.optimizer, "step", interrupt)
    with pytest.raises(KeyboardInterrupt, match="interrupted"):
        current.train_batch(current.config.stages[0], 7)
    counts = current.training_effort["counts"]
    assert counts["optimizer_step_calls_started"] == counts["optimizer_step_calls_raised"] == 1
    assert counts["optimizer_step_calls_returned"] == 0 and counts["backward_frames_returned"] == 8
