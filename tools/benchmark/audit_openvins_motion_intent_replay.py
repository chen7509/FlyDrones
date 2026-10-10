"""Independent checks for the fixed-input native motion-intent evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path):
    return json.loads(Path(path).read_text())


def audit(root, source_capture, binary, config):
    root, source_capture = Path(root), Path(source_capture)
    binary, config = Path(binary), Path(config)
    failures = []

    def require(condition, message):
        if not condition:
            failures.append(message)

    binary_hash, config_hash = _sha256(binary), _sha256(config)
    source_requests = source_capture / "shadow" / "native-requests.jsonl"
    source_hash = _sha256(source_requests)
    preinit = _load(root / "preinit-refusal-v2" / "summary.json")
    duplicate = _load(root / "duplicate-refusal-v1" / "summary.json")
    replay = _load(root / "fixed-replay-v3" / "summary.json")
    require(preinit.get("qualified") is True, "pre-initialization refusal not qualified")
    require(preinit.get("binary_sha256") == binary_hash, "pre-initialization binary mismatch")
    require(preinit.get("config_sha256") == config_hash, "pre-initialization config mismatch")
    require(preinit.get("native_result", {}).get("accepted") == 0, "pre-initialization request accepted")
    require(preinit.get("native_result", {}).get("exit") == 2, "pre-initialization native exit mismatch")
    require(
        "motion intent before internal initialization" in (root / "preinit-refusal-v2" / "native.log").read_text(),
        "pre-initialization native refusal missing",
    )

    require(duplicate.get("qualified") is True, "duplicate refusal not qualified")
    require(duplicate.get("binary_sha256") == binary_hash, "duplicate binary mismatch")
    require(duplicate.get("config_sha256") == config_hash, "duplicate config mismatch")
    require(duplicate.get("source_records_before_intent") == 627, "duplicate replay source count mismatch")
    require(duplicate.get("gate", {}).get("qualified") is True, "first intent did not qualify")
    require(duplicate.get("native", {}).get("exit") == 2, "duplicate native exit mismatch")
    require(
        "duplicate native motion intent" in (root / "duplicate-refusal-v1" / "native.log").read_text(),
        "duplicate native refusal missing",
    )

    require(replay.get("qualified") is True, "fixed replay not qualified")
    require(replay.get("binary_sha256") == binary_hash, "fixed replay binary mismatch")
    require(replay.get("config_sha256") == config_hash, "fixed replay config mismatch")
    require(replay.get("source_requests_sha256") == source_hash, "sealed request source mismatch")
    require(replay.get("initialized_sample_ns") == 2_400_000_000, "initialized sample mismatch")
    require(replay.get("effective_sim_ns") == 2_621_000_000, "effective motion time mismatch")
    require(replay.get("replayed_source_records") == 783, "fixed replay source count mismatch")
    require(replay.get("transport_accepted") == 784, "fixed replay transport count mismatch")
    require(replay.get("truth_used") is False, "truth entered fixed replay")
    require(replay.get("physical_replay") is False, "fixed replay mislabeled physical")
    require(replay.get("fusion_eligible") is False, "fixed replay granted fusion")
    gate = replay.get("gate", {})
    require(gate.get("qualified") is True, "motion-intent gate not qualified")
    require(gate.get("native_adapter_integrated") is True, "native adapter not integrated")
    require(gate.get("physical_validation") is False, "fixed replay mislabeled physical validation")
    acknowledgement = replay.get("intent_ack", {})
    for key in (
        "internal_initialized",
        "has_moved_since_zupt",
        "motion_intent_applied",
        "try_zupt",
        "zupt_only_at_beginning",
    ):
        require(acknowledgement.get(key) is True, "intent acknowledgement missing " + key)
    require(acknowledgement.get("native_sequence") == 627, "intent native sequence mismatch")
    post = replay.get("post_intent_camera_states", [])
    require([row.get("sample_ns") for row in post] == [2_700_000_000, 2_800_000_000, 2_900_000_000, 3_000_000_000],
            "post-intent camera samples mismatch")
    require(all(row.get("has_moved_since_zupt") is True for row in post), "movement latch did not persist")
    require(all(row.get("zupt_flag_latched") is False for row in post), "post-intent ZUPT remained latched")
    require(all(len(row.get("imu_state", [])) == 16 for row in post), "post-intent IMU state missing")
    require(
        post and all(abs(row["imu_state"][-1] - 0.00045162984734758993) < 1e-15 for row in post),
        "post-intent accelerometer bias changed in fixed replay",
    )
    raw_acks = [json.loads(line) for line in (root / "fixed-replay-v3" / "native-acks.jsonl").read_text().splitlines()]
    motion_acks = [row for row in raw_acks if row.get("kind") == "M"]
    require(len(motion_acks) == 1, "fixed replay motion acknowledgement count mismatch")
    require(motion_acks and "gray_first" not in motion_acks[0], "motion acknowledgement inherited pixel field")
    return {
        "schema": "openvins-motion-intent-replay-audit-v1",
        "binary_sha256": binary_hash,
        "config_sha256": config_hash,
        "source_requests_sha256": source_hash,
        "failures": failures,
        "qualified": not failures,
        "truth_used": False,
        "physical_validation": False,
        "fusion_eligible": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-capture", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.source_capture, args.binary, args.config)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
