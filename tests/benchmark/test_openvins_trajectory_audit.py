from __future__ import annotations

import csv
import json

import pytest

from tools.benchmark.analyze_openvins_trajectory import analyze


def _write_inputs(tmp_path, *, initialized: bool = True):
    states = tmp_path / "states.csv"
    truth = tmp_path / "result.json"
    with states.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("image_ns", "initialized", "state_timestamp_s",
                         "qx", "qy", "qz", "qw", "px", "py", "pz"))
        for t, xyz in ((1, (0, 0, 0)), (2, (1, 0, 0)), (3, (1, 1, 0))):
            writer.writerow((t * 1_000_000_000, int(initialized), t,
                             0, 0, 0, 1, *xyz) if initialized else
                            (t * 1_000_000_000, 0, -1, "", "", "", "", "", "", ""))
    truth.write_text(json.dumps({"odometry_source": "gazebo_model_truth", "path": [
        {"sim_ns": t * 1_000_000_000, "position": pos}
        for t, pos in ((1, [2, 3, 0]), (2, [2, 4, 0]), (3, [1, 4, 0]))
    ]}))
    return states, truth


def test_metric_alignment_removes_only_rigid_gauge(tmp_path) -> None:
    states, truth = _write_inputs(tmp_path)
    result = analyze(states, truth)
    assert result["status"] == "trajectory_present"
    assert result["initialized_frames"] == 3
    assert result["aligned_ate_rmse_m"] == pytest.approx(0, abs=1e-10)
    assert result["vio_displacement_m"] == pytest.approx(2 ** .5)
    assert result["truth_displacement_m"] == pytest.approx(2 ** .5)
    assert result["alignment_scale"] == 1.0


def test_no_initialization_is_explicit_failure(tmp_path) -> None:
    states, truth = _write_inputs(tmp_path, initialized=False)
    result = analyze(states, truth)
    assert result["status"] == "no_initialization"
    assert result["initialized_frames"] == 0
    assert result["aligned_ate_rmse_m"] is None


def test_state_without_visual_updates_is_not_called_vio(tmp_path) -> None:
    states, truth = _write_inputs(tmp_path)
    log = tmp_path / "upstream.log"
    log.write_text(("[TIME]: 0.0 seconds for MSCKF update (0 feats)\n"
                    "[TIME]: 0.0 seconds for SLAM update (0 feats)\n") * 3)
    result = analyze(states, truth, log)
    assert result["status"] == "inertial_only_after_init"
    assert result["msckf_nonzero_update_frames"] == 0
    assert result["slam_landmark_max"] == 0
