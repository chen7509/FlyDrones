from __future__ import annotations

import json
import math
import threading
from pathlib import Path

from flydrones.distributed_stress import (
    StressTrialConfig,
    _aggregate_stress,
    _publish_start_signal,
    _read_start_signal,
    avoidance_velocity,
    run_udp_process_trial,
)
from flydrones.peer_udp import PeerTrack


def test_start_signal_appears_only_after_complete_json_is_published(tmp_path, monkeypatch) -> None:
    (tmp_path / "start.json.pending").write_text("stale", encoding="utf-8")
    staged = threading.Event()
    release = threading.Event()
    errors = []
    original_write_text = Path.write_text

    def pause_after_staging(path, content, *args, **kwargs):
        written = original_write_text(path, content, *args, **kwargs)
        if path.name == "start.json.pending":
            staged.set()
            if not release.wait(5):
                raise TimeoutError("test did not release staged signal")
        return written

    monkeypatch.setattr(Path, "write_text", pause_after_staging)

    def publish():
        try:
            _publish_start_signal(tmp_path / "start.json", 123.25)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=publish)
    worker.start()
    try:
        assert staged.wait(5)
        assert not (tmp_path / "start.json").exists()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert not errors
    assert json.loads((tmp_path / "start.json").read_text(encoding="utf-8")) == {
        "start_at": 123.25,
    }


def test_start_signal_read_retries_transient_windows_permission_error(tmp_path, monkeypatch) -> None:
    signal = tmp_path / "start.json"
    signal.write_text('{"start_at": 123.25}', encoding="utf-8")
    original = Path.read_text
    attempts = 0

    def intermittently_locked(path, *args, **kwargs):
        nonlocal attempts
        if path == signal and attempts < 2:
            attempts += 1
            raise PermissionError(13, "sharing violation", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", intermittently_locked)
    assert _read_start_signal(signal, timeout_s=0.5) == 123.25
    assert attempts == 2


def test_start_signal_read_times_out_if_access_never_recovers(tmp_path, monkeypatch) -> None:
    signal = tmp_path / "start.json"
    signal.write_text('{"start_at": 123.25}', encoding="utf-8")

    def locked(*_args, **_kwargs):
        raise PermissionError(13, "sharing violation", str(signal))

    monkeypatch.setattr(Path, "read_text", locked)
    import pytest

    with pytest.raises(TimeoutError, match="start signal"):
        _read_start_signal(signal, timeout_s=0.03)


def test_aggregate_reports_worker_error_before_missing_trace(tmp_path) -> None:
    import pytest

    config = StressTrialConfig(vehicle_count=2, output_dir=tmp_path)
    with pytest.raises(RuntimeError, match="PermissionError.*start.json"):
        _aggregate_stress(config, [{"vehicle_id": 0,
                                    "error": "PermissionError: start.json"}], tmp_path)


def test_local_avoidance_deflects_a_head_on_peer() -> None:
    peer = PeerTrack(
        sender_id=1,
        sequence=3,
        sent_at=1.0,
        received_at=1.1,
        position=(2.0, 0.0, 20.0),
        velocity=(-6.0, 0.0, 0.0),
    )

    correction, interventions = avoidance_velocity(
        vehicle_id=0,
        position=(-2.0, 0.0, 20.0),
        velocity=(6.0, 0.0, 0.0),
        preferred_velocity=(6.0, 0.0, 0.0),
        tracks=[peer],
        protected_separation_m=1.5,
        planning_separation_m=3.0,
        horizon_s=3.0,
    )

    assert interventions == 1
    assert abs(correction[1]) > 0.5
    assert math.dist(correction, (0.0, 0.0, 0.0)) > 0.5


def test_four_independent_udp_processes_converge(tmp_path) -> None:
    config = StressTrialConfig(
        vehicle_count=4,
        output_dir=tmp_path,
        duration_s=4.0,
        rate_hz=10.0,
        radius_m=6.0,
        altitude_layers=1,
        target_speed_mps=3.0,
        rotation_deg=90.0,
        peer_base_port=0,
        packet_loss=0.02,
        blackout_windows_s=((1.4, 1.7),),
    )

    summary = run_udp_process_trial(config)

    assert summary["accepted"] is True
    assert summary["checks"]["one_process_per_vehicle"] is True
    assert summary["checks"]["real_udp_exchange"] is True
    assert summary["metrics"]["arrived"] == 4
    assert summary["metrics"]["controller_processes"] == 4
    assert summary["metrics"]["collisions"] == 0
    assert summary["metrics"]["minimum_intervehicle_distance_m"] >= 1.5
