from __future__ import annotations

from types import SimpleNamespace

import pytest

from flydrones.benchmark import gateway as gateway_module
from flydrones.benchmark.gateway import Gateway, NativeGazeboPx4Backend
from flydrones.benchmark.score import EpisodeScorer, ScoreSample
from tools.benchmark.run_episode import (
    mark_prelude_failure,
    prearm_duration,
    prelude_step_count,
    run_hover_prelude,
)


def test_prearm_option_is_dev_only_and_defaults_off(tmp_path):
    backend = NativeGazeboPx4Backend(tmp_path, tmp_path / "run", {"goal": [0, 0, 1]})
    assert backend.development_prearm_stationary_s == 0.
    assert backend.prearm_stationary_evidence is None
    assert prearm_duration(0., frozen=True, record_rgb=False,
                           record_camera_info=False) == 0.
    assert prearm_duration(4., frozen=False, record_rgb=True,
                           record_camera_info=True) == 4.
    for seconds in (-1., 8.01, float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="prearm"):
            prearm_duration(seconds, frozen=False, record_rgb=True,
                            record_camera_info=True)
    for frozen, rgb, info in ((True, True, True), (False, False, True),
                              (False, True, False)):
        with pytest.raises(ValueError, match="prearm"):
            prearm_duration(4., frozen=frozen, record_rgb=rgb,
                            record_camera_info=info)


def test_prearm_wait_uses_simulation_time_and_records_progress(tmp_path, monkeypatch):
    backend = NativeGazeboPx4Backend(
        tmp_path, tmp_path / "run", {"goal": [0, 0, 1]},
        development_prearm_stationary_s=4.)
    backend.stats["sim_ns"] = 1_000_000_000
    sends = []
    backend.drone = SimpleNamespace(send=sends.append, telemetry=lambda: None)

    def advance_sim(_seconds):
        backend.stats["sim_ns"] += 500_000_000

    monkeypatch.setattr(gateway_module.time, "sleep", advance_sim)
    result = backend._hold_prearm_stationary("hover")
    assert result["status"] == "completed"
    assert result["start_sim_ns"] == 1_000_000_000
    assert result["end_sim_ns"] >= 5_000_000_000
    assert result["commands_sent"] == len(sends) == 8


def test_prearm_timeout_keeps_partial_simulation_progress(tmp_path, monkeypatch):
    backend = NativeGazeboPx4Backend(
        tmp_path, tmp_path / "run", {"goal": [0, 0, 1]},
        development_prearm_stationary_s=4.)
    backend.stats["sim_ns"] = 1_000_000_000
    backend.drone = SimpleNamespace(send=lambda _: None, telemetry=lambda: None)
    ticks = iter((0., 0., 0.1, 1.1))
    monkeypatch.setattr(gateway_module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(gateway_module.time, "sleep", lambda _: None)
    with pytest.raises(TimeoutError, match="prearm"):
        backend._hold_prearm_stationary("hover", max_wall_s=1.)
    assert backend.prearm_stationary_evidence["status"] == "timeout"
    assert backend.prearm_stationary_evidence["end_sim_ns"] == 1_000_000_000


def test_dev_prelude_counts_fixed_steps_without_changing_zero_default() -> None:
    assert prelude_step_count(0., .05, frozen=True,
                              record_rgb=False, record_camera_info=False) == 0
    assert prelude_step_count(4., .05, frozen=False,
                              record_rgb=True, record_camera_info=True) == 80


@pytest.mark.parametrize("seconds", [-1., float("nan"), float("inf"), 8.05, .075])
def test_dev_prelude_rejects_invalid_duration(seconds: float) -> None:
    with pytest.raises(ValueError, match="prelude"):
        prelude_step_count(seconds, .05, frozen=False,
                           record_rgb=True, record_camera_info=True)


@pytest.mark.parametrize("frozen,rgb,info", [
    (True, True, True), (False, False, True), (False, True, False),
])
def test_dev_prelude_rejects_formal_manifest_or_missing_capture(
    frozen: bool, rgb: bool, info: bool,
) -> None:
    with pytest.raises(ValueError, match="development.*prelude"):
        prelude_step_count(2., .05, frozen=frozen,
                           record_rgb=rgb, record_camera_info=info)


class _Backend:
    def __init__(self) -> None:
        self.time_ns = 1_000_000_000
        self.commands = []

    def start(self, _world) -> None:
        pass

    def advance(self, command, dt_s: float) -> None:
        self.commands.append((command, dt_s))
        self.time_ns += round(dt_s * 1e9)

    def score_sample(self) -> ScoreSample:
        return ScoreSample(self.time_ns, (0., 0., 1.5), 1.,
                           contact=len(self.commands) == 2, in_bounds=True)


def test_hover_prelude_scores_each_step_and_stops_on_collision() -> None:
    backend = _Backend()
    gateway = Gateway({"control": {"dt_s": .05, "speed_max_mps": .8,
                                    "acceleration_max_mps2": 1.,
                                    "yaw_rate_max_radps": 1.}}, backend)
    gateway.start("unused")
    scorer = EpisodeScorer((8., 0., 1.5), .5, 1., 20.)
    zero = run_hover_prelude(gateway, scorer, 0)
    assert zero["actual_steps"] == 0
    assert scorer.samples == []
    result = run_hover_prelude(gateway, scorer, 80)
    assert result["actual_steps"] == 2
    assert result["terminal_status"] == "collision"
    assert len(scorer.samples) == 3
    assert all(command == (0., 0., 0., 0.) and dt == .05
               for command, dt in backend.commands)


def test_hover_prelude_keeps_partial_progress_if_gateway_fails() -> None:
    class FailingBackend(_Backend):
        def advance(self, command, dt_s: float) -> None:
            if len(self.commands) == 1:
                raise RuntimeError("backend failed")
            super().advance(command, dt_s)

    backend = FailingBackend()
    gateway = Gateway({"control": {"dt_s": .05, "speed_max_mps": .8,
                                    "acceleration_max_mps2": 1.,
                                    "yaw_rate_max_radps": 1.}}, backend)
    gateway.start("unused")
    scorer = EpisodeScorer((8., 0., 1.5), .5, 1., 20.)
    progress = run_hover_prelude(gateway, scorer, 0)
    with pytest.raises(RuntimeError, match="backend failed"):
        run_hover_prelude(gateway, scorer, 80, progress=progress)
    assert progress["requested_steps"] == 80
    assert progress["actual_steps"] == 1
    assert progress["scored_steps"] == 1
    assert progress["start_sim_ns"] == 1_000_000_000
    assert progress["end_sim_ns"] == 1_050_000_000


def test_hover_prelude_counts_advance_even_if_sampling_fails() -> None:
    class FailingSampleBackend(_Backend):
        def score_sample(self) -> ScoreSample:
            if len(self.commands) == 2:
                raise RuntimeError("sample failed")
            return super().score_sample()

    backend = FailingSampleBackend()
    gateway = Gateway({"control": {"dt_s": .05, "speed_max_mps": .8,
                                    "acceleration_max_mps2": 1.,
                                    "yaw_rate_max_radps": 1.}}, backend)
    gateway.start("unused")
    scorer = EpisodeScorer((8., 0., 1.5), .5, 1., 20.)
    progress = run_hover_prelude(gateway, scorer, 0)
    with pytest.raises(RuntimeError, match="sample failed"):
        run_hover_prelude(gateway, scorer, 80, progress=progress)
    assert progress["actual_steps"] == 2
    assert progress["scored_steps"] == 1
    assert progress["end_sim_ns"] == 1_050_000_000  # last sampled time


def test_last_step_sampling_failure_is_labeled_prelude_failure() -> None:
    partial = {"actual_steps": 80, "scored_steps": 79, "terminal_status": None}
    mark_prelude_failure(partial, 80, "infrastructure_error")
    assert partial["terminal_status"] == "infrastructure_error"
    completed = {"actual_steps": 80, "scored_steps": 80, "terminal_status": None}
    mark_prelude_failure(completed, 80, "controller_error")
    assert completed["terminal_status"] is None
