from __future__ import annotations

import math

from flydrones.distributed_stress import (
    StressTrialConfig,
    avoidance_velocity,
    run_udp_process_trial,
)
from flydrones.peer_udp import PeerTrack


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
