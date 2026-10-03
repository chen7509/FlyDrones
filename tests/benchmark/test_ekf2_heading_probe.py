"""A heading diagnostic must not silently alter formal benchmark flights."""

import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from flydrones.benchmark.gateway import NativeGazeboPx4Backend
from tools.benchmark import probe_ekf2_heading as probe
from tools.benchmark.probe_ekf2_heading import run_probe


def _world():
    return {"start": [0., 0., 0.], "goal": [1., 0., 1.], "seed": 1701}


def test_backend_takeoff_default_unchanged_and_probe_altitude_bounded(tmp_path):
    default = NativeGazeboPx4Backend(tmp_path, tmp_path / "run", _world())
    assert default.takeoff_alt_m == 1.26
    assert default.takeoff_timeout_s == 35.
    raised = NativeGazeboPx4Backend(
        tmp_path, tmp_path / "raised", _world(), takeoff_alt_m=2.1,
        takeoff_timeout_s=90.)
    assert raised.takeoff_alt_m == 2.1
    assert raised.takeoff_timeout_s == 90.
    for bad in (0., 4., float("nan"), float("inf"), True, "2.1"):
        with pytest.raises(ValueError, match="takeoff"):
            NativeGazeboPx4Backend(
                tmp_path, tmp_path / "bad", _world(), takeoff_alt_m=bad)
    for bad in (0., 181., float("nan"), True):
        with pytest.raises(ValueError, match="timeout"):
            NativeGazeboPx4Backend(
                tmp_path, tmp_path / "bad", _world(), takeoff_timeout_s=bad)


class FakeBackend:
    instances = []
    fail_at = None
    emit_ulog = True
    emit_offboard = True

    def __init__(self, root, output, world, *, takeoff_alt_m, takeoff_timeout_s):
        assert takeoff_alt_m in (1.26, 2.1)
        assert takeoff_timeout_s == 90.
        self.takeoff_alt_m = takeoff_alt_m
        self.steps = 0
        self.closed = False
        self.started = False
        self.ulog_evidence = []
        self.ulog_capture_error = None
        self.control_records = []
        self.offboard_evidence = ([{"sim_ns": 0, "custom_mode": 1, "base_mode": 128}]
                                  if self.emit_offboard else [])
        self.__class__.instances.append(self)

    def start(self, path):
        self.started = True
        assert path.is_file()
        assert path.name == "working-world.sdf"
        path.write_text("<sdf mutated/>")

    def advance(self, command, dt_s):
        assert command == (0., 0., 0., 0.)
        assert dt_s == .05
        self.steps += 1
        self.control_records.append({"step": self.steps, "command": command})
        if self.steps == self.fail_at:
            raise RuntimeError("sim failed")

    def score_sample(self):
        return SimpleNamespace(sim_ns=self.steps * 50_000_000,
                               position=(0., 0., 2.1), clearance_m=2.,
                               contact=False, in_bounds=True)

    def close(self):
        self.closed = True
        self.ulog_evidence = ([{"path": "log/test.ulg", "sha256": "a" * 64,
                                "valid_header": True}]
                              if self.emit_ulog else [])


def _inputs(tmp_path):
    output = tmp_path / "probe"
    output.mkdir()
    (output / "world.json").write_text(json.dumps(_world()))
    (output / "world.sdf").write_text("<sdf/>")
    return output


def test_probe_only_hovers_for_four_seconds_and_closes(tmp_path):
    FakeBackend.instances.clear()
    FakeBackend.fail_at = None
    FakeBackend.emit_ulog = True
    FakeBackend.emit_offboard = True
    output = _inputs(tmp_path)
    result = run_probe(output, backend_factory=FakeBackend)
    backend = FakeBackend.instances[-1]
    assert backend.started and backend.closed and backend.steps == 80
    assert result["status"] == "diagnostic_complete"
    assert result["steps_completed"] == 80
    assert len(result["samples"]) == 80
    assert result["ulog_evidence"] == backend.ulog_evidence
    assert result["offboard_evidence"] == backend.offboard_evidence
    assert result["control_records"] == backend.control_records
    assert len(result["command_attempts"]) == 80
    assert all(attempt["local_ned"] == [0., 0., 0., 0.]
               and attempt["completed"] for attempt in result["command_attempts"])
    assert result["eligible_for_live_capture"] is False
    progress = (output / "probe-progress.ndjson").read_text().splitlines()
    assert len(progress) == 160
    assert (output / "world.sdf").read_text() == "<sdf/>"
    assert (output / "working-world.sdf").read_text() == "<sdf mutated/>"
    with pytest.raises(FileExistsError):
        run_probe(output, backend_factory=FakeBackend)


def test_probe_paired_low_altitude_uses_same_backend_and_records_variant(tmp_path):
    FakeBackend.instances.clear()
    FakeBackend.fail_at = None
    FakeBackend.emit_ulog = True
    FakeBackend.emit_offboard = True
    result = run_probe(_inputs(tmp_path), backend_factory=FakeBackend,
                       takeoff_alt_m=1.26)
    assert result["status"] == "diagnostic_complete"
    assert result["takeoff_alt_m"] == 1.26
    assert FakeBackend.instances[-1].takeoff_alt_m == 1.26
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    with pytest.raises(ValueError, match="paired altitude"):
        run_probe(_inputs(invalid), backend_factory=FakeBackend, takeoff_alt_m=1.8)


def test_probe_failure_keeps_partial_samples_and_closes(tmp_path):
    FakeBackend.instances.clear()
    FakeBackend.fail_at = 3
    FakeBackend.emit_ulog = True
    FakeBackend.emit_offboard = True
    output = _inputs(tmp_path)
    result = run_probe(output, backend_factory=FakeBackend)
    assert FakeBackend.instances[-1].closed
    assert result["status"] == "infrastructure_error"
    assert result["steps_completed"] == 2
    assert len(result["samples"]) == 2
    assert result["command_attempts"][-1]["completed"] is False
    assert len((output / "probe-progress.ndjson").read_text().splitlines()) == 5
    assert "sim failed" in result["failure"]
    assert json.loads((output / "probe-result.json").read_text())["status"] == result["status"]


def test_probe_without_raw_ulog_cannot_be_diagnostic_complete(tmp_path):
    FakeBackend.instances.clear()
    FakeBackend.fail_at = None
    FakeBackend.emit_ulog = False
    FakeBackend.emit_offboard = True
    result = run_probe(_inputs(tmp_path), backend_factory=FakeBackend)
    assert result["status"] == "infrastructure_error"
    assert "ULog" in result["failure"]


def test_probe_without_offboard_evidence_cannot_be_diagnostic_complete(tmp_path):
    FakeBackend.instances.clear()
    FakeBackend.fail_at = None
    FakeBackend.emit_ulog = True
    FakeBackend.emit_offboard = False
    result = run_probe(_inputs(tmp_path), backend_factory=FakeBackend)
    assert result["status"] == "infrastructure_error"
    assert "OFFBOARD" in result["failure"]


def test_px4_provenance_rejects_changed_binary_even_with_same_commit(monkeypatch, tmp_path):
    monkeypatch.setattr(probe.Path, "home", classmethod(lambda cls: tmp_path))

    def fake_run(args, **kwargs):
        output = (probe.PX4_COMMIT if "rev-parse" in args else
                  " M Tools/simulation/flightgear/flightgear_bridge\n"
                  " M Tools/simulation/gz\n"
                  " M src/modules/sensors/vehicle_imu/VehicleIMU.cpp\n")
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    monkeypatch.setattr(probe, "_digest_file", lambda path: (
        "0" * 64 if path.as_posix().endswith("/bin/px4") else
        probe.VEHICLE_IMU_SHA256 if path.as_posix().endswith("VehicleIMU.cpp") else
        probe.PX4_BASE_MODEL_SHA256 if path.as_posix().endswith("x500_base/model.sdf") else
        probe.CAMERA_MODEL_SHA256 if path.as_posix().endswith("OakD-Benchmark/model.sdf") else
        probe.BENCHMARK_MODEL_SHA256))
    with pytest.raises(ValueError, match="binary"):
        probe._px4_provenance()


def test_model_tree_digest_covers_included_mesh_bytes(tmp_path):
    model = tmp_path / "x500_base"
    mesh = model / "meshes" / "rotor.dae"
    mesh.parent.mkdir(parents=True)
    (model / "model.sdf").write_text("<model/>")
    mesh.write_bytes(b"rotor-v1")
    first = probe._tree_digest(model)
    mesh.write_bytes(b"rotor-v2")
    assert probe._tree_digest(model) != first


def test_supervisor_times_out_and_records_targeted_cleanup(monkeypatch, tmp_path):
    output = tmp_path / "timed-out-probe"

    class HungWorker:
        pid = 4567
        returncode = None

        def communicate(self, *, timeout):
            assert timeout == 1
            raise subprocess.TimeoutExpired("worker", timeout)

        def wait(self, *, timeout):
            self.returncode = -15
            return self.returncode

    starts = []
    kills = []
    monkeypatch.setattr(probe.subprocess, "Popen", lambda args, **kw: (
        starts.append((args, kw)) or HungWorker()))
    monkeypatch.setattr(probe.os, "killpg", lambda pid, sig: kills.append((pid, sig)),
                        raising=False)
    monkeypatch.setattr(probe, "_cleanup_owned_processes", lambda path: {
        "terminated": [999], "still_running": [], "unverified": []})
    monkeypatch.setattr(probe, "_recover_ulog", lambda path: {"status": "runtime_missing"})
    result = probe.supervise_probe(tmp_path / "source.zip", tmp_path / "index.json",
                                    output, timeout_s=1)
    assert starts[0][1]["start_new_session"] is True
    assert kills and kills[0][0] == 4567
    assert result["status"] == "supervisor_timeout"
    assert result["cleanup"]["terminated"] == [999]
    assert json.loads((output / "supervisor-result.json").read_text())["status"] == result["status"]


def test_supervisor_accepts_only_clean_worker_and_preserves_report(monkeypatch, tmp_path):
    output = tmp_path / "complete-probe"

    class CompleteWorker:
        pid = 4568
        returncode = 0

        def communicate(self, *, timeout):
            output.mkdir()
            log = output / "px4-ulog/log/test.ulg"
            log.parent.mkdir(parents=True)
            raw = b"ULog\x01\x12\x35" + b"0" * 9
            log.write_bytes(raw)
            record = {"path": "px4-ulog/log/test.ulg", "bytes": len(raw),
                      "sha256": hashlib.sha256(raw).hexdigest(), "valid_header": True}
            (output / "px4-ulog-manifest.json").write_text(json.dumps({"logs": [record]}))
            (output / "probe-result.json").write_text(json.dumps({
                "status": "diagnostic_complete", "ulog_evidence": [record]}))
            return "complete", ""

    monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: CompleteWorker())
    monkeypatch.setattr(probe, "_cleanup_owned_processes", lambda path: {
        "terminated": [], "still_running": [], "unverified": []})
    monkeypatch.setattr(probe, "_recover_ulog", lambda path: {"status": "already_captured"})
    result = probe.supervise_probe(tmp_path / "source.zip", tmp_path / "index.json", output)
    assert result["status"] == "diagnostic_complete"
    assert result["worker_stdout_tail"] == "complete"
    assert json.loads((output / "probe-result.json").read_text())["status"] == "diagnostic_complete"


def test_supervisor_rejects_worker_success_without_verifiable_ulog(monkeypatch, tmp_path):
    output = tmp_path / "bad-evidence"

    class CompleteWorker:
        returncode = 0

        def communicate(self, *, timeout):
            output.mkdir()
            (output / "probe-result.json").write_text(json.dumps({
                "status": "diagnostic_complete", "ulog_evidence": []}))
            return "", ""

    monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: CompleteWorker())
    monkeypatch.setattr(probe, "_cleanup_owned_processes", lambda path: {
        "terminated": [], "still_running": [], "unverified": []})
    monkeypatch.setattr(probe, "_recover_ulog", lambda path: {"status": "runtime_missing"})
    result = probe.supervise_probe(tmp_path / "source.zip", tmp_path / "index.json", output)
    assert result["status"] == "evidence_invalid"


def test_supervisor_keyboard_interrupt_still_cleans_worker(monkeypatch, tmp_path):
    output = tmp_path / "interrupted"

    class InterruptedWorker:
        pid = 9876
        returncode = None

        def communicate(self, *, timeout):
            raise KeyboardInterrupt

        def wait(self, *, timeout):
            self.returncode = -15
            return self.returncode

    kills = []
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: InterruptedWorker())
    monkeypatch.setattr(probe.os, "killpg", lambda pid, sig: kills.append((pid, sig)),
                        raising=False)
    monkeypatch.setattr(probe, "_cleanup_owned_processes", lambda path: {
        "terminated": [], "still_running": [], "unverified": []})
    monkeypatch.setattr(probe, "_recover_ulog", lambda path: {"status": "runtime_missing"})
    result = probe.supervise_probe(tmp_path / "source.zip", tmp_path / "index.json", output)
    assert result["status"] == "supervisor_interrupted"
    assert kills and kills[0][0] == 9876
    assert (output / "supervisor-result.json").exists()
