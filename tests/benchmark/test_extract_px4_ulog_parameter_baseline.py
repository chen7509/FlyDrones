from __future__ import annotations

from dataclasses import dataclass

import pytest

from tools.benchmark.extract_px4_ulog_parameter_baseline import extract_baseline
from tools.benchmark.openvins_ekf2_disarmed_preflight import required_parameter_names


@dataclass
class Topic:
    name: str


class ULogFixture:
    def __init__(self, parameters):
        self.initial_parameters = parameters
        self.data_list = [Topic("vehicle_status"), Topic("estimator_status"), Topic("vehicle_status")]


def values():
    return {"MAV_SYS_ID": 9, **{name: 0 for name in required_parameter_names()}}


def test_extracts_exact_required_baseline_and_topic_inventory(tmp_path):
    ulog = tmp_path / "run.ulg"
    ulog.write_bytes(b"ULog fixture")
    result = extract_baseline(ULogFixture(values()), ulog)
    assert result["parameters"]["MAV_SYS_ID"] == 9
    assert set(required_parameter_names()).issubset(result["parameters"])
    assert result["topics"] == ["estimator_status", "vehicle_status"]
    assert result["source_ulog"]["bytes"] == len(b"ULog fixture")
    assert len(result["source_ulog"]["sha256"]) == 64


def test_missing_parameter_is_rejected(tmp_path):
    ulog = tmp_path / "run.ulg"
    ulog.write_bytes(b"ULog fixture")
    parameters = values()
    parameters.pop("EKF2_EV_CTRL")
    with pytest.raises(ValueError, match="EKF2_EV_CTRL"):
        extract_baseline(ULogFixture(parameters), ulog)
