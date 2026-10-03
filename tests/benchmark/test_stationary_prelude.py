from __future__ import annotations

import pytest

from flydrones.benchmark.gateway import Gateway
from flydrones.benchmark.score import EpisodeScorer, ScoreSample
from tools.benchmark.run_episode import prelude_step_count, run_hover_prelude


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
