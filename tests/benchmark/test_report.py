import pytest

from flydrones.benchmark.report import path_length, summarize_controller


def test_path_length_uses_recorded_three_dimensional_trajectory():
    path = [{'position': [0., 0., 0.]}, {'position': [3., 4., 0.]}, {'position': [3., 4., 12.]}]
    assert path_length(path) == pytest.approx(17.)


def test_controller_summary_keeps_failures_and_actual_latency():
    episodes = [
        {'status': 'success', 'elapsed_sim_s': 10., 'wall_s': 20., 'minimum_clearance_m': .4,
         'path': [], 'decisions': [{'decision_wall_s': .1}]},
        {'status': 'collision', 'elapsed_sim_s': 4., 'wall_s': 8., 'minimum_clearance_m': -.1,
         'path': [], 'decisions': [{'decision_wall_s': .3}]},
    ]
    summary = summarize_controller(episodes)
    assert summary['episodes'] == 2
    assert summary['status_counts'] == {'collision': 1, 'success': 1}
    assert summary['success_rate'] == pytest.approx(.5)
    assert summary['decision_wall_s']['mean'] == pytest.approx(.2)
