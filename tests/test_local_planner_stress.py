from flydrones.local_planner_stress import run_local_planner_stress


def test_randomized_crossing_and_forest_cases_remain_collision_free():
    result = run_local_planner_stress(seed=20260921, scenario_count=100)
    assert result["accepted"], result
    assert result["metrics"]["scenarios"] == 100
    assert result["metrics"]["static_contacts"] == 0
    assert result["metrics"]["peer_contacts"] == 0
    assert result["metrics"]["minimum_static_clearance_m"] >= 0.60
    assert result["metrics"]["minimum_peer_separation_m"] >= 0.90


def test_stress_seed_is_reproducible():
    assert run_local_planner_stress(7, 10) == run_local_planner_stress(7, 10)
