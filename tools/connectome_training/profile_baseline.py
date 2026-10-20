from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

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

    def __init__(self):
        self.reset_seed = None

    @property
    def model_metadata(self):
        return {
            "neurons": 0,
            "connections": 0,
            "sha256": None,
            "reset_seed": self.reset_seed,
        }

    def reset(self, seed: int):
        self.reset_seed = seed

    def step(self, obs):
        return Decision(
            Command((0.0, 0.0, 0.0), 0.0),
            0.001,
            {"brain_wall_s": 0.00075, "sim_ns": obs.sim_ns},
        )


def evaluate_latency_gate(latency, *, identity, model, maximum_p95_s, minimum_samples):
    """Eligibility of this CPU baseline, not a trained-policy/flight certificate."""
    if (type(maximum_p95_s) not in (int, float)
            or not np.isfinite(maximum_p95_s) or maximum_p95_s <= 0):
        raise ValueError("maximum_p95_s must be finite and positive")
    if type(minimum_samples) is not int or minimum_samples < 1:
        raise ValueError("minimum_samples must be a positive integer")
    measured = latency["outer_s"]["p95"]
    if type(measured) not in (int, float) or not np.isfinite(measured) or measured < 0:
        raise ValueError("outer p95 must be finite and non-negative")
    reasons = []
    if (identity != "full-male-cns"
            or model.get("neurons") != 166700
            or model.get("connections") != 25582837
            or not isinstance(model.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", model["sha256"]) is None):
        reasons.append("not_complete_model")
    if type(latency["samples"]) is not int or latency["samples"] < minimum_samples:
        reasons.append("insufficient_samples")
    eligible = not reasons
    if measured > maximum_p95_s:
        reasons.append("outer_p95_exceeds_limit")
    return {
        "basis": "outer_controller_step_wall_s",
        "eligible": eligible,
        "passed": not reasons,
        "reasons": reasons,
        "minimum_samples": minimum_samples,
        "maximum_p95_s": maximum_p95_s,
    }


def main():
    args = parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    gates = config["latency_gates"]
    if args.fake:
        controller = DeterministicFakeController()
        identity = controller.identity
    else:
        fly_config = load_config("configs/forest-trained-v2.yaml")
        controller = FullFlyController(
            fly_config, Path("data/malecns_full.npz"), guided=False
        )
        identity = "full-male-cns"
    controller.reset(args.seed)
    if args.fake:
        model = controller.model_metadata
    else:
        model = {
            "neurons": controller.connectome.n,
            "connections": controller.connectome.n_connections,
            "sha256": controller.model_sha256,
            "reset_seed": args.seed,
        }
    warmup = [make_observation(i) for i in range(args.warmup)]
    for observation in warmup:
        controller.step(observation)
    start = args.warmup
    latency = profile_controller(
        controller,
        [make_observation(start + i) for i in range(args.samples)],
    )
    gate = evaluate_latency_gate(
        latency, identity=identity, model=model,
        maximum_p95_s=gates["complete_fly_p95_s"],
        minimum_samples=config["profiling"]["samples"],
    )
    if args.warmup < config["profiling"]["warmup"]:
        gate["eligible"] = gate["passed"] = False
        gate["reasons"].append("insufficient_warmup")
    report = {
        "schema": "flydrones-connectome-profile-v2",
        "controller_identity": identity,
        "seed": args.seed,
        "warmup": args.warmup,
        "latency": latency,
        "gates": gates,
        "latency_gate": gate,
        "passed_complete_fly_p95": gate["passed"],
        "trained_policy_verified": False,
        "workload": "synthetic-black-rgb-fixed-depth-goal-cpu-synchronous",
        "controller_implementation": "deterministic-fake" if args.fake else "FullFlyController/Brain/LIFNetwork",
        "timing_scope": "step input to Decision return; excludes acquisition, warmup and flight transport",
        "environment": {
            "python": sys.version,
            "numpy": np.__version__,
            "platform": platform.platform(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        },
        "model": model,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also refuses a competing writer after the early check.
    # Failed/partial writes remain evidence; this is not an atomic/fsync promise.
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {"output": str(output), "passed": report["passed_complete_fly_p95"]}
        )
    )


if __name__ == "__main__":
    main()
