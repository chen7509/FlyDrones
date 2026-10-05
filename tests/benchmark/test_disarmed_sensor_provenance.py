import importlib.util
import json
import time

import numpy as np
import pytest


def api():
    assert importlib.util.find_spec("tools.benchmark.disarmed_sensor_provenance"), "sensor provenance implementation missing"
    from tools.benchmark import disarmed_sensor_provenance

    return disarmed_sensor_provenance


def event(**changes):
    value = dict(
        kind="imu",
        sample_ns=4_000_000,
        arrival_monotonic_ns=time.monotonic_ns(),
        observed_sim_ns=4_000_000,
        gyro_flu=[1.0, 2.0, 3.0],
        accel_flu=[4.0, 5.0, 6.0],
    )
    value.update(changes)
    return value


def test_flu_frd_axes_and_separate_clocks():
    result = api().validate_event(event(observed_sim_ns=3_000_000))
    assert result["gyro_frd"] == [1.0, -2.0, -3.0]
    assert result["accel_frd"] == [4.0, -5.0, -6.0]
    assert result["sim_age_at_callback_ns"] == -1_000_000
    assert "orientation" not in result and "end_to_end_latency" not in result


@pytest.mark.parametrize(
    "change",
    [
        dict(sample_ns=0),
        dict(sample_ns=True),
        dict(arrival_monotonic_ns=-1),
        dict(gyro_flu=[1, float("nan"), 3]),
        dict(accel_flu=[1, 2]),
        dict(kind="pose"),
        dict(orientation=[1, 0, 0, 0]),
        dict(gyro_flu=[True, 0, 0]),
    ],
)
def test_invalid_events_rejected(change):
    with pytest.raises(ValueError):
        api().validate_event(event(**change))


def test_exclusive_recorder_preserves_data_and_rejects_duplicate(tmp_path):
    writer = api().CaptureWriter(tmp_path)
    writer.submit(event())
    with pytest.raises(ValueError):
        writer.submit(event())
    writer.submit(event(sample_ns=8_000_000))
    summary = writer.finish()
    assert summary["written"]["imu"] == 2
    rows = [json.loads(s) for s in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert rows[0]["sample_ns"] == 4_000_000 and rows[0]["gyro_flu"] == [1.0, 2.0, 3.0]
    assert rows[0]["recorded_monotonic_ns"] >= rows[0]["arrival_monotonic_ns"]
    with pytest.raises(FileExistsError):
        api().CaptureWriter(tmp_path)


def test_queue_overflow_is_explicit(tmp_path):
    writer = api().CaptureWriter(tmp_path, capacity=1, start_worker=False)
    writer.submit(event())
    with pytest.raises(RuntimeError, match="overflow"):
        writer.submit(event(sample_ns=8_000_000))
    writer.start()
    assert writer.finish()["written"]["imu"] == 1


def test_writer_io_failure_reported(tmp_path, monkeypatch):
    writer = api().CaptureWriter(tmp_path, start_worker=False)

    def fail(*args):
        raise OSError("injected disk failure")

    monkeypatch.setattr(writer, "_write_event", fail)
    writer.submit(event())
    writer.start()
    with pytest.raises(RuntimeError, match="disk failure"):
        writer.finish()


def test_pairing_reports_offset_and_errors_without_claiming_equivalence():
    rows = [event(sample_ns=n * 4_000_000) for n in range(1, 21)]
    times = np.array([r["sample_ns"] // 1000 + 1000 for r in rows])
    gyro = np.tile([1.0, -2.0, -3.0], (20, 1))
    accel = np.tile([4.0, -5.0, -6.0], (20, 1))
    result = api().compare_imu(rows, times, gyro, accel)
    assert result["paired_samples"] == 20 and result["median_px4_minus_gz_us"] == 1000
    assert result["gyro_absolute_error_max"] == 0 and result["accel_absolute_error_max"] == 0
    assert result["source_equivalence_qualified"] is False
    gyro[1, 0] += 2
    result = api().compare_imu(rows, times, gyro, accel)
    assert result["gyro_absolute_error_max"] == 2


def test_capture_does_not_call_armed_gateway_or_send_mavlink():
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "tools/benchmark/capture_disarmed_sensors.py"
    assert path.is_file(), "disarmed capture entry point missing"
    tree = ast.parse(path.read_text())
    names = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    assert not {"takeoff", "arm", "land", "command_long_send", "odometry_send", "send", "_on_pose"} & set(names)
    assert "NativeGazeboPx4Backend" not in path.read_text()


def test_record_audit_rejects_changed_transform_timing_and_missing_stream(tmp_path):
    writer = api().CaptureWriter(tmp_path)
    writer.submit(event())
    writer.submit(event(sample_ns=8_000_000))
    writer.finish()
    rows = [json.loads(s) for s in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert api().audit_event_records(rows, required_kinds={"imu"})["imu"] == 2
    import copy

    for change in [
        {"gyro_frd": [1, 2, 3]},
        {"recorded_monotonic_ns": 0},
        {"orientation": [1, 0, 0, 0]},
        {"sample_ns": 0},
        {"sim_age_at_callback_ns": 123},
    ]:
        changed = copy.deepcopy(rows)
        changed[0].update(change)
        with pytest.raises(ValueError):
            api().audit_event_records(changed, required_kinds={"imu"})
    with pytest.raises(ValueError):
        api().audit_event_records(rows, required_kinds={"imu", "rgb"})
    with pytest.raises(ValueError):
        api().audit_event_records(rows + rows, required_kinds={"imu"})
