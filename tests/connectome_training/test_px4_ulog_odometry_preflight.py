"""A logged topic is only a prerequisite for future DDS/ULog comparison."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from flydrones.connectome_training.px4_ulog_odometry_preflight import audit_topic


def dataset(name="vehicle_odometry", count=2, **changed):
    columns = {
        "timestamp": [100, 200], "timestamp_sample": [90, 190],
        "pose_frame": [1, 1], "velocity_frame": [1, 1],
        "reset_counter": [0, 0], "quality": [0, 0],
    }
    for prefix, size in (
        ("position", 3), ("q", 4), ("velocity", 3),
        ("angular_velocity", 3), ("position_variance", 3),
        ("orientation_variance", 3), ("velocity_variance", 3),
    ):
        for index in range(size):
            columns[f"{prefix}[{index}]"] = [0.0] * count
    columns.update(changed)
    return SimpleNamespace(name=name, multi_id=0, data=columns)


def test_missing_vehicle_odometry_cannot_support_exact_dds_crosscheck():
    audit = audit_topic([dataset("vehicle_local_position")])
    assert audit.reason == "vehicle_odometry_not_logged"
    assert audit.usable_for_exact_crosscheck is False
    assert audit.eligible_for_live_capture is False


def test_complete_single_topic_is_only_a_crosscheck_candidate():
    audit = audit_topic([dataset()])
    assert audit.usable_for_exact_crosscheck is True
    assert audit.samples == 2
    assert audit.eligible_for_live_capture is False


def test_missing_column_and_nonzero_instance_fail_closed():
    item = dataset()
    del item.data["q[3]"]
    assert audit_topic([item]).reason == "odometry_fields_missing"
    item = dataset()
    item.multi_id = 1
    assert audit_topic([item]).reason == "odometry_instance_ambiguous"


def test_length_and_time_regressions_fail_closed():
    assert audit_topic([dataset(**{"position[0]": [1.0]})]).reason == "odometry_column_length"
    assert audit_topic([dataset(timestamp_sample=[190, 90])]).reason == "odometry_time_order"


def test_malformed_non_time_values_cannot_be_crosscheck_candidates():
    assert audit_topic([dataset(**{"q[0]": ["bad", 1.0]})]).usable_for_exact_crosscheck is False
    assert audit_topic([dataset(pose_frame=[True, 1])]).usable_for_exact_crosscheck is False
    assert audit_topic([dataset(reset_counter=[-1, 0])]).usable_for_exact_crosscheck is False


def test_cli_refusal_prints_evidence_but_exits_nonzero(tmp_path, monkeypatch, capsys):
    script = Path(__file__).resolve().parents[2] / "tools/connectome/audit_px4_ulog_odometry.py"
    spec = importlib.util.spec_from_file_location("audit_px4_ulog_odometry_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "existing.ulg"
    path.write_bytes(b"ULog for fake reader")
    monkeypatch.setitem(sys.modules, "pyulog", SimpleNamespace(
        ULog=lambda _: SimpleNamespace(data_list=[dataset("vehicle_local_position")])
    ))
    monkeypatch.setattr(module, "version", lambda _: "test-version")
    assert module.main([str(path)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["results"][0]["vehicle_odometry_audit"]["reason"] == "vehicle_odometry_not_logged"
