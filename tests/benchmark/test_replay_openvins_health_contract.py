import copy
import hashlib
import json

import pytest

from tools.benchmark.replay_openvins_health_contract import (
    FAULT_PROFILES,
    audit_fault_results,
    freeze_fault_matrix,
    validate_fault_matrix,
)


def write(path, data):
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def fixture(tmp_path):
    binary = tmp_path / "probe"
    config = tmp_path / "config.yaml"
    capture = tmp_path / "capture"
    capture.mkdir()
    events = capture / "events.jsonl"
    write(binary, b"probe-v1")
    write(config, b"config-v1")
    write(events, b'{"kind":"imu"}\n')
    return binary, config, capture


def test_fault_matrix_is_frozen_before_replay_and_contains_every_required_fault(tmp_path):
    binary, config, capture = fixture(tmp_path)
    manifest = freeze_fault_matrix(binary=binary, config=config, sealed_capture=capture)
    assert set(manifest["profiles"]) == set(FAULT_PROFILES)
    assert manifest["profiles"]["normal"]["expected_quality"] == 0
    assert manifest["profiles"]["process_restart"]["expected_reset_total"] == 1
    assert all(profile["fusion_eligible"] is False for profile in manifest["profiles"].values())
    assert validate_fault_matrix(manifest, binary=binary, config=config, sealed_capture=capture) == manifest


@pytest.mark.parametrize("mutation", ["binary", "config", "source", "profile", "trigger", "claim"])
def test_fault_matrix_rejects_every_post_freeze_mutation(tmp_path, mutation):
    binary, config, capture = fixture(tmp_path)
    manifest = freeze_fault_matrix(binary=binary, config=config, sealed_capture=capture)
    changed = copy.deepcopy(manifest)
    if mutation == "binary":
        binary.write_bytes(b"changed")
    elif mutation == "config":
        config.write_bytes(b"changed")
    elif mutation == "source":
        (capture / "events.jsonl").write_bytes(b"changed")
    elif mutation == "profile":
        changed["profiles"].pop("camera_silence")
    elif mutation == "trigger":
        changed["profiles"]["imu_silence"]["trigger_sim_ns"] += 1
    else:
        changed["profiles"]["normal"]["fusion_eligible"] = True
    with pytest.raises(ValueError):
        validate_fault_matrix(changed, binary=binary, config=config, sealed_capture=capture)


def test_manifest_round_trip_is_canonical_and_json_safe(tmp_path):
    binary, config, capture = fixture(tmp_path)
    first = freeze_fault_matrix(binary=binary, config=config, sealed_capture=capture)
    encoded = json.dumps(first, allow_nan=False, sort_keys=True)
    assert json.loads(encoded) == first
    assert first["matrix_sha256"] == hashlib.sha256(
        json.dumps({k: v for k, v in first.items() if k != "matrix_sha256"}, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def result_fixture(tmp_path, manifest):
    roots = {}
    for name, profile in manifest["profiles"].items():
        root = tmp_path / name
        root.mkdir(parents=True)
        (root / "fault-matrix.json").write_text(json.dumps(manifest))
        health = {
            "last_quality": profile["expected_quality"],
            "reset_total": profile["expected_reset_total"],
            "fusion_eligible": False,
        }
        result = {
            "schema": "openvins-health-fault-result-v1",
            "profile": name,
            "qualified": True,
            "health": health,
            "fusion_eligible": False,
            "network_output": False,
            "odometry_output": False,
        }
        if name == "processing_timeout":
            result["native"] = {
                "exit": -15,
                "failure": "TimeoutError",
                "quality": None,
                "reset_counter": None,
                "fusion_eligible": False,
            }
        else:
            count = 2 if name == "process_restart" else 1
            result["sessions"] = [
                {
                    "native": {
                        "exit": 0,
                        "failure": None,
                        "quality": None,
                        "reset_counter": None,
                        "fusion_eligible": False,
                    }
                }
                for _ in range(count)
            ]
        (root / "fault-result.json").write_text(json.dumps(result))
        roots[name] = root
    return roots


def test_aggregate_audit_requires_every_profile_and_preserves_native_null_fields(tmp_path):
    binary, config, capture = fixture(tmp_path)
    manifest = freeze_fault_matrix(binary=binary, config=config, sealed_capture=capture)
    roots = result_fixture(tmp_path / "runs", manifest)
    result = audit_fault_results(manifest, roots)
    assert result["qualified"] is True
    assert result["fusion_eligible"] is False
    assert set(result["profiles"]) == set(FAULT_PROFILES)


@pytest.mark.parametrize("fault", ["missing", "fusion", "quality", "reset", "matrix", "native_claim", "cleanup"])
def test_aggregate_audit_rejects_incomplete_or_overclaimed_evidence(tmp_path, fault):
    binary, config, capture = fixture(tmp_path)
    manifest = freeze_fault_matrix(binary=binary, config=config, sealed_capture=capture)
    roots = result_fixture(tmp_path / "runs", manifest)
    if fault == "missing":
        roots.pop("camera_silence")
    else:
        root = roots["normal"]
        path = root / ("fault-matrix.json" if fault == "matrix" else "fault-result.json")
        value = json.loads(path.read_text())
        if fault == "fusion":
            value["fusion_eligible"] = True
        elif fault == "quality":
            value["health"]["last_quality"] = 1
        elif fault == "reset":
            value["health"]["reset_total"] = 1
        elif fault == "matrix":
            value["profiles"]["normal"]["stop_sim_ns"] += 1
        elif fault == "native_claim":
            value["sessions"][0]["native"]["quality"] = 0
        else:
            value["sessions"][0]["native"]["exit"] = -9
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        audit_fault_results(manifest, roots)

