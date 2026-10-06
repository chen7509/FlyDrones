import hashlib
import importlib.util
import json
import threading
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


def test_idle_callback_runs_on_writer_thread_only_after_queued_records_finish(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    idle = threading.Event()
    seen = []

    def on_record(row, _payload):
        seen.append(row["sample_ns"])
        if len(seen) == 1:
            entered.set()
            assert release.wait(1)

    writer = api().CaptureWriter(
        tmp_path, on_record=on_record, on_idle=lambda _now: idle.set(), idle_period_s=0.01
    )
    writer.submit(event(sample_ns=4_000_000))
    assert entered.wait(1)
    writer.submit(event(sample_ns=8_000_000))
    assert not idle.wait(0.05)
    release.set()
    assert idle.wait(1)
    assert writer.finish()["written"]["imu"] == 2
    assert seen == [4_000_000, 8_000_000]


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


def test_camera_info_keeps_all_sample_stamps_and_payloads(tmp_path):
    fields = dict(
        width=160,
        height=120,
        frame_id="camera",
        intrinsics_k=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        projection_p=[1.0] * 12,
        distortion_model=0,
        distortion_k=[],
    )
    writer = api().CaptureWriter(tmp_path)
    row = dict(
        kind="info", sample_ns=2_000_000, arrival_monotonic_ns=time.monotonic_ns(), observed_sim_ns=2_000_000, camera_info=fields
    )
    try:
        writer.submit(row, b"first protobuf")
        with pytest.raises(ValueError, match="duplicate"):
            writer.submit(row, b"duplicate")
        writer.submit(dict(row, sample_ns=100_000_000), b"second protobuf")
    finally:
        writer.finish()
    records = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [r["sample_ns"] for r in records] == [2_000_000, 100_000_000]
    assert [(tmp_path / r["payload_path"]).read_bytes() for r in records] == [b"first protobuf", b"second protobuf"]


@pytest.mark.parametrize("phase", ["subscription", "fixture", "ulog"])
def test_failure_journal_preserves_setup_and_cleanup_errors(tmp_path, phase):
    called = []
    result = {"status": "incomplete", "errors": []}
    with api().CaptureJournal(tmp_path, result) as journal:
        journal.cleanup("writer", lambda: called.append("writer"), priority=80)

        def fail():
            raise OSError("injected " + phase)

        journal.cleanup("ulog", fail if phase == "ulog" else lambda: called.append("ulog"), priority=100)
        if phase != "ulog":
            fail()
        result["status"] = "capture_completed"
    saved = json.loads((tmp_path / "result.json").read_text())
    assert saved["status"] == "capture_failed"
    assert phase in str(saved["errors"])
    assert "writer" in called


def test_supervisor_terminates_own_blocked_worker(tmp_path):
    import subprocess

    killed = []

    class Blocked:
        pid = 54321
        returncode = None

        def wait(self, timeout):
            if not killed:
                raise subprocess.TimeoutExpired("blocked server", timeout)
            self.returncode = -9
            return -9

    result = api().supervise_worker(
        ["synthetic"],
        tmp_path / "capture",
        timeout_s=0.01,
        spawn=lambda command: Blocked(),
        terminate=lambda worker: killed.append(worker.pid),
    )
    assert killed == [54321]
    assert result["status"] == "supervisor_timeout"
    saved = json.loads((tmp_path / "capture/result.json").read_text())
    assert saved["status"] == "capture_failed"


def test_supervisor_passes_only_materialized_declared_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', 'hostile-parent')
    monkeypatch.setenv('HTTP_PROXY', 'hostile-proxy')
    contract_path = tmp_path / 'execution-contract.json'
    contract_path.write_text('{"schema":"capture-execution-v2"}\n')
    declared = {'HOME': '/home/test', 'PYTHONPATH': None, 'SDF_PATH': ''}
    calls = []

    class Done:
        pid = 54321
        returncode = 0

        def wait(self, timeout):
            return 0

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return Done()

    result = api().supervise_worker(
        ['synthetic'], tmp_path / 'capture', spawn=spawn, terminate=lambda _worker: None,
        launch_environment=declared, execution_contract=contract_path,
    )
    assert result['status'] == 'worker_exited'
    assert calls == [(['synthetic'], {'env': {'HOME': '/home/test', 'SDF_PATH': ''}})]
    record_path = tmp_path / 'capture.supervisor-environment.json'
    record = json.loads(record_path.read_text())
    assert record['declared'] == declared
    assert record['materialized'] == {'HOME': '/home/test', 'SDF_PATH': ''}
    assert record['execution_contract']['sha256'] == hashlib.sha256(contract_path.read_bytes()).hexdigest()
    assert record['ambient_inherited'] is False
    assert record['runtime_environment_qualified'] is False


def test_supervisor_environment_record_survives_spawn_failure(tmp_path):
    contract_path = tmp_path / 'execution-contract.json'
    contract_path.write_text('{}\n')

    def fail(_command, **_kwargs):
        raise OSError('injected spawn failure')

    with pytest.raises(OSError, match='spawn failure'):
        api().supervise_worker(
            ['synthetic'], tmp_path / 'capture', spawn=fail, terminate=lambda _worker: None,
            launch_environment={'HOME': '/home/test'}, execution_contract=contract_path,
        )
    assert (tmp_path / 'capture.supervisor-environment.json').is_file()
    assert not (tmp_path / 'capture').exists()


def test_supervisor_refuses_environment_record_failure_before_spawn(tmp_path, monkeypatch):
    contract_path = tmp_path / 'execution-contract.json'
    contract_path.write_text('{}\n')
    calls = []
    monkeypatch.setattr(api(), 'write_manifest', lambda *_args: (_ for _ in ()).throw(OSError('short write')))
    with pytest.raises(OSError, match='short write'):
        api().supervise_worker(
            ['synthetic'], tmp_path / 'capture', spawn=lambda *a, **k: calls.append((a, k)),
            terminate=lambda _worker: None, launch_environment={'HOME': '/home/test'},
            execution_contract=contract_path,
        )
    assert calls == []


@pytest.mark.parametrize('environment,contract', [
    ({'HOME': 1}, 'valid'), ({'HOME': '/home/test'}, 'missing'),
])
def test_supervisor_refuses_invalid_environment_inputs(tmp_path, environment, contract):
    contract_path = tmp_path / 'execution-contract.json'
    if contract == 'valid':
        contract_path.write_text('{}\n')
    with pytest.raises((ValueError, FileNotFoundError)):
        api().supervise_worker(
            ['synthetic'], tmp_path / 'capture', spawn=lambda *_a, **_k: None,
            terminate=lambda _worker: None, launch_environment=environment,
            execution_contract=contract_path,
        )
