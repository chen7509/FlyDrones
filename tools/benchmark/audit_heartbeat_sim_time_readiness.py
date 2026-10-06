"""Replay immutable physical refusal ages against the dual-clock readiness gate."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.readiness_anchor import JournaledReadiness


def audit(source):
    source = Path(source).resolve(strict=True)
    value = json.loads(source.read_text(encoding="utf-8"))
    failures = []

    def require(condition, label):
        if not condition:
            failures.append(label)

    require(value.get("schema") == "openvins-handoff-physical-attempt-audit-v1", "source schema")
    require(value.get("failure_evidence_qualified") is True, "source qualification")
    require(value.get("classification") == "journaled-heartbeat-wall-age-slow-simulation-refusal", "source cause")
    wall_age = value.get("heartbeat_wall_age_ns")
    sim_age = value.get("heartbeat_sim_age_ns")
    require(type(wall_age) is int and wall_age > 2_000_000_000, "wall age")
    require(type(sim_age) is int and 0 <= sim_age <= 2_000_000_000, "simulation age")

    proof = counterfactual = None
    if not failures:
        now = wall_age + 100
        heartbeat_sim = 3_679_000_000
        gate = JournaledReadiness(clock=lambda: now)
        gate.on_record(
            {
                "kind": "heartbeat",
                "arrival_monotonic_ns": 100,
                "recorded_monotonic_ns": 100,
                "observed_sim_ns": heartbeat_sim,
                "system_id": 9,
                "base_mode": 29,
            },
            None,
        )
        for kind in ("imu", "rgb", "info"):
            row = {"kind": kind, "arrival_monotonic_ns": now, "recorded_monotonic_ns": now}
            if kind == "imu":
                row["observed_sim_ns"] = heartbeat_sim + sim_age
            gate.on_record(row, None)
        proof = gate.proof()
        require(proof is not None, "fixed refusal should be simulation-time ready")
        if proof:
            require(proof["freshness"]["heartbeat_wall_age_ns"] == wall_age, "wall diagnostic")
            require(proof["freshness"]["heartbeat_sim_age_ns"] == sim_age, "simulation diagnostic")

        later = now + 1
        silent = JournaledReadiness(clock=lambda: later)
        for kind, row in gate.snapshot()["records"].items():
            copied = {key: val for key, val in row.items() if key != "journal_ack_monotonic_ns"}
            if kind in ("imu", "rgb", "info"):
                copied["arrival_monotonic_ns"] = later
                copied["recorded_monotonic_ns"] = later
            if kind == "imu":
                copied["observed_sim_ns"] = heartbeat_sim + 2_000_000_001
            silent.on_record(copied, None)
        counterfactual = silent.proof()
        require(counterfactual is None, "simulation-time heartbeat silence must refuse")

    return {
        "schema": "heartbeat-simulation-time-readiness-audit-v1",
        "failures": failures,
        "qualified": not failures,
        "source_sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest(),
        "heartbeat_wall_age_ns": wall_age,
        "heartbeat_sim_age_ns": sim_age,
        "fixed_evidence_ready": not failures and proof is not None,
        "simulation_silence_refused": not failures and counterfactual is None,
        "timeout_increased": False,
        "physical_rerun": False,
        "vio_accuracy_qualified": False,
        "fusion_eligible": False,
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.source)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
