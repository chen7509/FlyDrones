from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys

import numpy as np
import yaml

from flydrones.benchmark.contract import Command, Decision, Observation
from flydrones.benchmark.fly import FullFlyController
from flydrones.config import load_config
from flydrones.connectome_training.profiling import profile_controller


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--config", default="configs/connectome_training_v1.yaml")
    parser.add_argument(
        "--output",
        default="results/connectome-training/stage-a/baseline_profile.json",
    )
    args = parser.parse_args()
    if args.samples < 1 or args.warmup < 0:
        parser.error("samples must be positive and warmup must be non-negative")
    return args


def make_observation(index: int, shape=(120, 160)):
    sim_ns = (index + 1) * 50_000_000
    return Observation(
        sim_ns,
        sim_ns,
        np.zeros((*shape, 3), np.uint8),
        np.full(shape, 8.0, np.float32),
        (),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, 0.0),
        0.0,
        0.0,
        (8.0, 0.0, 1.0),
    )


class DeterministicFakeController:
    identity = "deterministic-fake"
    model_metadata = {"neurons": 0, "connections": 0, "sha256": None}

    def step(self, obs):
        return Decision(
            Command((0.0, 0.0, 0.0), 0.0),
            0.001,
            {"brain_wall_s": 0.00075, "sim_ns": obs.sim_ns},
        )


def main():
    args = parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    gates = config["latency_gates"]
    if args.fake:
        controller = DeterministicFakeController()
        identity = controller.identity
        model = controller.model_metadata
    else:
        fly_config = load_config("configs/forest-trained-v2.yaml")
        controller = FullFlyController(
            fly_config, Path("data/malecns_full.npz"), guided=False
        )
        identity = "full-male-cns"
        model = {
            "neurons": controller.connectome.n,
            "connections": controller.connectome.n_connections,
            "sha256": controller.model_sha256,
        }
    warmup = [make_observation(i) for i in range(args.warmup)]
    for observation in warmup:
        controller.step(observation)
    start = args.warmup
    latency = profile_controller(
        controller,
        [make_observation(start + i) for i in range(args.samples)],
    )
    report = {
        "schema": "flydrones-connectome-profile-v1",
        "controller_identity": identity,
        "seed": args.seed,
        "warmup": args.warmup,
        "latency": latency,
        "gates": gates,
        "passed_complete_fly_p95": latency["total_s"]["p95"]
        <= gates["complete_fly_p95_s"],
        "environment": {
            "python": sys.version,
            "numpy": np.__version__,
            "platform": platform.platform(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        },
        "model": model,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".writing")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(
        json.dumps(
            {"output": str(output), "passed": report["passed_complete_fly_p95"]}
        )
    )


if __name__ == "__main__":
    main()
