import json
from pathlib import Path

import pytest

from flydrones.connectome_training.curriculum import run_curriculum
from flydrones.connectome_training.curriculum_config import (
    CurriculumConfig,
    CurriculumProfile,
    CurriculumStage,
)
from flydrones.connectome_training.curriculum_state import StateStore


def stage(identifier, order, max_batches=2):
    return CurriculumStage(
        identifier,
        order,
        (10 + order,),
        (100 + order,),
        1,
        max_batches,
        0.15,
        0.8,
        1.02,
        (),
        (),
    )


def config(*stages):
    return CurriculumConfig(
        7,
        CurriculumProfile(
            "smoke",
            "synthetic-smoke",
            "tiny-connectome",
            "cpu",
            tuple(item.id for item in stages),
        ),
        tuple(stages),
        "a" * 64,
    )


class DeterministicSession:
    model_identity = "tiny:test-topology:test-mapping"

    def __init__(self, losses, *, fail_save=False):
        self.losses = losses
        self.step = 0
        self.train_calls = []
        self.fail_save = fail_save

    def train_batch(self, stage, seed):
        self.step += 1
        self.train_calls.append((stage.id, seed))
        return {"updates": stage.epochs_per_batch, "environment_steps": 8}

    def evaluate(self, stage):
        value = self.losses[(self.step, stage.id)]
        return {
            "validation_loss": value,
            "initial_validation_loss": 1.0,
            "parameters_finite": True,
        }

    def save_checkpoint(self, path: Path, metadata: dict):
        if self.fail_save:
            raise OSError("simulated checkpoint failure")
        path.mkdir(parents=True)
        (path / "session.json").write_text(
            json.dumps({"step": self.step, "metadata": metadata}, sort_keys=True),
            encoding="utf-8",
        )

    def restore_checkpoint(self, path: Path):
        self.step = json.loads((path / "session.json").read_text(encoding="utf-8"))[
            "step"
        ]


class AlteredMetricsSession(DeterministicSession):
    def __init__(self, *, override=None, counter_override=None, regression_fault=False):
        super().__init__({(1, "stability"): 0.1, (2, "looming"): 0.05, (2, "stability"): 0.1})
        self.override = override or {}
        self.counter_override = counter_override or {}
        self.regression_fault = regression_fault

    def train_batch(self, stage, seed):
        return {**super().train_batch(stage, seed), **self.counter_override}

    def evaluate(self, stage):
        result = {**super().evaluate(stage), **self.override}
        if self.regression_fault and self.step == 2 and stage.id == "stability":
            result["parameters_finite"] = False
        return result


@pytest.mark.parametrize("override", [
    {"parameters_finite": "false"}, {"parameters_finite": 1}, {"parameters_finite": None},
    {"validation_loss": False}, {"validation_loss": "0.1"}, {"initial_validation_loss": True},
])
def test_malformed_evaluation_cannot_publish_candidate_or_promote(tmp_path, override):
    with pytest.raises(ValueError):
        run_curriculum(config(stage("stability", 0)), tmp_path, AlteredMetricsSession(override=override))
    assert StateStore(tmp_path, "a" * 64).load() is None
    assert not (tmp_path / "checkpoints").exists()


@pytest.mark.parametrize("counter_override", [
    {"updates": 1.5}, {"updates": True}, {"updates": "1"}, {"environment_steps": 8.5},
])
def test_coercive_counters_cannot_be_committed(tmp_path, counter_override):
    with pytest.raises(ValueError):
        run_curriculum(config(stage("stability", 0)), tmp_path,
                       AlteredMetricsSession(counter_override=counter_override))
    assert StateStore(tmp_path, "a" * 64).load() is None


def test_regression_nonfinite_parameters_roll_back_and_retain_failed_candidate(tmp_path):
    session = AlteredMetricsSession(regression_fault=True)
    state = run_curriculum(config(stage("stability", 0), stage("looming", 1, max_batches=1)), tmp_path, session)
    assert state.status == "FAILED"
    assert state.completed_stages == ("stability",)
    assert state.latest_checkpoint == state.best_checkpoint
    assert state.failed_attempts == 1
    assert session.step == 1
    reports = sorted((tmp_path / "reports").glob("*.json"))
    failed = json.loads(reports[-1].read_text())
    assert failed["promoted"] is False
    assert failed["regression_failures"] == ["stability"]
    assert failed["regression_metrics"]["stability"]["parameters_finite"] is False
    assert (tmp_path / failed["candidate_checkpoint"]).is_dir()


def test_valid_false_current_parameters_retains_failed_report(tmp_path):
    state = run_curriculum(config(stage("stability", 0, max_batches=1)), tmp_path,
                           AlteredMetricsSession(override={"parameters_finite": False}))
    assert state.status == "FAILED"
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    assert report["gate_failures"] == ["parameters_finite"]
    assert report["promoted"] is False
    assert (tmp_path / report["candidate_checkpoint"]).is_dir()


def test_nonfinite_initial_model_cannot_become_a_resume_checkpoint(tmp_path):
    session = AlteredMetricsSession(override={"parameters_finite": False})
    state = run_curriculum(config(stage("stability", 0, max_batches=2)), tmp_path, session)
    assert state.status == "FAILED"
    assert state.latest_checkpoint is None
    assert len(session.train_calls) == 1
    assert len(list((tmp_path / "reports").glob("*.json"))) == 1


def test_nonfinite_current_stage_resumes_only_from_previous_valid_checkpoint(tmp_path):
    class CurrentFaultSession(AlteredMetricsSession):
        def evaluate(self, stage):
            result = super().evaluate(stage)
            if stage.id == "looming":
                result["parameters_finite"] = False
            return result

    settings = config(stage("stability", 0), stage("looming", 1, max_batches=2))
    session = CurrentFaultSession()
    partial = run_curriculum(settings, tmp_path, session, max_batches=2)
    assert partial.status == "COMMITTED"
    assert partial.latest_checkpoint == partial.best_checkpoint
    assert session.step == 1
    resumed = CurrentFaultSession()
    final = run_curriculum(settings, tmp_path, resumed)
    assert final.status == "FAILED"
    assert final.latest_checkpoint == partial.best_checkpoint
    assert resumed.step == 1
    assert resumed.train_calls == [("looming", 11)]
    failed = [json.loads(path.read_text()) for path in (tmp_path / "reports").glob("*.json")]
    failed = [report for report in failed if report["promoted"] is False]
    assert len(failed) == 2
    assert all((tmp_path / report["candidate_checkpoint"]).is_dir() for report in failed)


def test_two_stage_curriculum_promotes_and_completes(tmp_path):
    stages = (stage("stability", 0), stage("looming", 1))
    session = DeterministicSession(
        {(1, "stability"): 0.1, (2, "looming"): 0.05, (2, "stability"): 0.1}
    )
    state = run_curriculum(config(*stages), tmp_path, session)
    assert state.status == "COMPLETE"
    assert state.completed_stages == ("stability", "looming")
    assert session.train_calls == [("stability", 10), ("looming", 11)]
    assert len(list((tmp_path / "reports").glob("*.json"))) == 2


def test_resume_restores_checkpoint_without_replaying_committed_batch(tmp_path):
    stages = (stage("stability", 0), stage("looming", 1))
    losses = {
        (1, "stability"): 0.1,
        (2, "looming"): 0.05,
        (2, "stability"): 0.1,
    }
    first = DeterministicSession(losses)
    partial = run_curriculum(config(*stages), tmp_path, first, max_batches=1)
    assert partial.status == "COMMITTED"
    assert first.train_calls == [("stability", 10)]
    resumed = DeterministicSession(losses)
    final = run_curriculum(config(*stages), tmp_path, resumed)
    assert final.status == "COMPLETE"
    assert resumed.train_calls == [("looming", 11)]


def test_regression_failure_rolls_back_to_previous_best(tmp_path):
    stages = (stage("stability", 0), stage("looming", 1, max_batches=3))
    losses = {
        (1, "stability"): 0.1,
        (2, "looming"): 0.05,
        (2, "stability"): 0.2,
    }
    session = DeterministicSession(losses)
    state = run_curriculum(config(*stages), tmp_path, session, max_batches=2)
    assert state.status == "COMMITTED"
    assert state.stage_index == 1
    assert state.failed_attempts == 1
    assert state.completed_stages == ("stability",)
    assert state.latest_checkpoint == state.best_checkpoint
    assert session.step == 1
    report = json.loads(sorted((tmp_path / "reports").glob("*.json"))[-1].read_text())
    assert report["regression_failures"] == ["stability"]


def test_maximum_batches_marks_stage_failed(tmp_path):
    only = stage("stability", 0, max_batches=1)
    session = DeterministicSession({(1, "stability"): 0.9})
    state = run_curriculum(config(only), tmp_path, session)
    assert state.status == "FAILED"
    assert state.completed_stages == ()


def test_interruption_before_checkpoint_commit_preserves_previous_state(tmp_path):
    only = stage("stability", 0)
    session = DeterministicSession({(1, "stability"): 0.1}, fail_save=True)
    with pytest.raises(OSError, match="checkpoint failure"):
        run_curriculum(config(only), tmp_path, session)
    assert StateStore(tmp_path, "a" * 64).load() is None
