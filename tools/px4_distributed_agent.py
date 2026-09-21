"""Run exactly one PX4/depth/PPO worker with a direct UDP peer endpoint."""

from __future__ import annotations

import argparse
import json

from flydrones.distributed_px4 import DistributedAgentConfig, run_distributed_px4_agent
from flydrones.peer_udp import PeerUdpConfig


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--output", default="results/px4-sitl-distributed")
    parser.add_argument("--model", default="results/autonomous-forest-ppo-v1/autonomous-policy-numpy.npz")
    parser.add_argument("--rate", type=float, default=20.0)
    parser.add_argument("--mission-timeout", type=float, default=70.0)
    parser.add_argument("--peer-base-port", type=int, default=16770)
    parser.add_argument("--peer-range", type=float, default=8.0)
    parser.add_argument("--peer-latency-ms", type=float, default=120.0)
    parser.add_argument("--peer-jitter-ms", type=float, default=40.0)
    parser.add_argument("--peer-loss", type=float, default=0.15)
    parser.add_argument("--peer-track-ttl", type=float, default=0.65)
    parser.add_argument("--blackout-start", type=float, default=18.0)
    parser.add_argument("--blackout-end", type=float, default=23.0)
    args = parser.parse_args()
    radio = PeerUdpConfig(
        range_m=args.peer_range,
        latency_s=args.peer_latency_ms / 1000.0,
        jitter_s=args.peer_jitter_ms / 1000.0,
        packet_loss=args.peer_loss,
        track_ttl_s=args.peer_track_ttl,
        blackout_windows_s=((args.blackout_start, args.blackout_end),),
    )
    config = DistributedAgentConfig(
        vehicle_id=args.vehicle_id,
        output_dir=args.output,
        policy_path=args.model,
        rate_hz=args.rate,
        mission_timeout_s=args.mission_timeout,
        peer_base_port=args.peer_base_port,
        peer_config=radio,
    )
    _trace, result = run_distributed_px4_agent(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
