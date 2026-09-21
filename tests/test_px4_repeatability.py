import json

from flydrones.px4_repeatability import evaluate_px4_repetitions


def write_run(path, *, accepted=True, preflight=True, planner_p95=4.0):
    path.mkdir()
    summary = {
        "accepted": accepted,
        "checks": {
            "all_reached_altitude": preflight,
            "all_escaped": accepted,
            "all_rallied": accepted,
            "all_landed": True,
            "zero_forest_contacts": True,
            "safe_forest_clearance": True,
            "safe_intervehicle_separation": True,
            "zero_direct_global_neighbor_reads": True,
            "udp_blackout_exercised": True,
        },
        "metrics": {
            "minimum_forest_clearance_m": 0.15,
            "minimum_intervehicle_distance_m": 1.0,
            "planner_p95_ms": planner_p95,
            "central_control_commands": 0,
        },
    }
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_repeatability_requires_five_consecutive_complete_runs(tmp_path):
    runs = [tmp_path / f"run-{index}" for index in range(5)]
    for run in runs:
        write_run(run)
    result = evaluate_px4_repetitions(runs, required=5)
    assert result["accepted"]
    assert result["metrics"]["consecutive_passes"] == 5


def test_repeatability_rejects_preflight_failure(tmp_path):
    runs = [tmp_path / f"run-{index}" for index in range(5)]
    for index, run in enumerate(runs):
        write_run(run, accepted=index != 2, preflight=index != 2)
    result = evaluate_px4_repetitions(runs, required=5)
    assert not result["accepted"]
    assert result["metrics"]["consecutive_passes"] == 2
    assert result["failures"][0]["category"] == "preflight"
