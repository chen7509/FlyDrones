from types import SimpleNamespace

import numpy as np

from flydrones.benchmark.ulog_health import summarize_ulog


def _ulog(*, nav_states=(4, 14), position_times=(1, 2, 3)):
    values = {
        "vehicle_status": {"timestamp": np.array([1, 2]), "nav_state": np.array(nav_states),
                           "failsafe": np.array([0, 0])},
        "vehicle_local_position": {"timestamp": np.array(position_times),
                                   "xy_valid": np.array([1, 1, 1]),
                                   "z_valid": np.array([1, 1, 1]),
                                   "dead_reckoning": np.array([0, 0, 0])},
        "estimator_status": {"timestamp": np.array([1, 2]),
                             "filter_fault_flags": np.array([0, 0])},
        "estimator_status_flags": {"timestamp": np.array([1, 2]),
                                   "cs_gnss_pos": np.array([1, 1]),
                                   "cs_ev_pos": np.array([0, 0])},
        "trajectory_setpoint": {"timestamp": np.array([1, 2])},
        "vehicle_command_ack": {"timestamp": np.array([1]), "result": np.array([0])},
        "sensor_combined": {"timestamp": np.array([1, 2])},
    }
    return SimpleNamespace(data_list=[SimpleNamespace(name=name, data=data)
                                     for name, data in values.items()])


def test_ulog_health_reports_gnss_without_claiming_visual_fusion():
    summary = summarize_ulog(_ulog())

    assert summary["basic_topic_gate_passed"]
    assert summary["nav_state_counts"] == {"4": 1, "14": 1}
    assert summary["gnss_position_fusion_samples"] == 2
    assert summary["external_vision_position_fusion_samples"] == 0
    assert summary["failsafe_samples"] == 0


def test_ulog_health_rejects_missing_offboard_and_backward_time():
    missing_offboard = summarize_ulog(_ulog(nav_states=(4, 4)))
    assert "offboard_state_missing" in missing_offboard["failures"]

    backwards = summarize_ulog(_ulog(position_times=(1, 3, 2)))
    assert "vehicle_local_position_timestamp_nonmonotonic" in backwards["failures"]
