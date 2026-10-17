import copy
import hashlib
import json

import pytest

from tools.benchmark.openvins_causal_input import raw_profile

RGB = b"\x01\x02\x03" * (160 * 120)


def source_fixture(root):
    source = root / "capture"
    (source / "rgb-frames").mkdir(parents=True)
    (source / "camera-info-messages").mkdir()
    info_payload = b"fixed-camera-info"
    rows = [
        dict(
            kind="imu",
            sample_ns=1_000_000,
            arrival_monotonic_ns=26_727_469_680,
            observed_sim_ns=1_000_000,
            gyro_flu=[0.1, 0.2, 0.3],
            accel_flu=[0.0, 0.0, 9.81],
            source_sequence=0,
        ),
        dict(
            kind="info",
            sample_ns=2_000_000,
            arrival_monotonic_ns=28_173_399_627,
            observed_sim_ns=3_000_000,
            camera_info=raw_profile()["camera_info"],
            payload_path="camera-info-messages/2000000.pb",
            payload_sha256=hashlib.sha256(info_payload).hexdigest(),
            source_sequence=1,
        ),
        dict(
            kind="depth",
            sample_ns=2_000_000,
            arrival_monotonic_ns=28_431_684_420,
            observed_sim_ns=3_000_000,
            width=160,
            height=120,
            source_sequence=2,
        ),
        dict(
            kind="rgb",
            sample_ns=2_000_000,
            arrival_monotonic_ns=28_432_165_379,
            observed_sim_ns=3_000_000,
            width=160,
            height=120,
            source_sequence=3,
        ),
        dict(
            kind="imu",
            sample_ns=4_000_000,
            arrival_monotonic_ns=28_432_743_501,
            observed_sim_ns=4_000_000,
            gyro_flu=[0.2, 0.3, 0.4],
            accel_flu=[0.1, 0.0, 9.8],
            source_sequence=4,
        ),
        dict(
            kind="imu",
            sample_ns=8_000_000,
            arrival_monotonic_ns=28_436_925_451,
            observed_sim_ns=8_000_000,
            gyro_flu=[0.3, 0.4, 0.5],
            accel_flu=[0.0, 0.1, 9.8],
            source_sequence=5,
        ),
    ]
    (source / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (source / "rgb-frames/2000000.ppm").write_bytes(b"P6\n160 120\n255\n" + RGB)
    (source / "camera-info-messages/2000000.pb").write_bytes(info_payload)
    (source / "result.json").write_text(json.dumps({"status": "capture_failed", "fusion_eligible": False}))
    return source


def test_fixed_replay_releases_exact_camera_only_after_later_imu(tmp_path):
    from tools.benchmark.replay_causal_pair_stage import replay

    result = replay(source_fixture(tmp_path), tmp_path / "replay")
    assert result["source_row_count"] == 6
    assert [row["kind"] for row in result["actions"]] == ["imu", "imu", "camera", "imu"]
    camera = result["actions"][2]
    assert camera["sample_ns"] == 2_000_000
    assert camera["rgb_source_sequence"] == 3
    assert camera["info_source_sequence"] == 1
    assert camera["imu_boundary_ns"] == 4_000_000
    assert camera["rgb_sha256"] == hashlib.sha256(RGB).hexdigest()
    assert result["shadow_failure"] is None
    assert result["physical_execution_qualified"] is False


def test_independent_audit_accepts_fixed_replay(tmp_path):
    from tools.benchmark.audit_causal_pair_stage import audit
    from tools.benchmark.replay_causal_pair_stage import replay

    source = source_fixture(tmp_path)
    output = tmp_path / "replay"
    replay(source, output)
    result = audit(source, output)
    assert result["failures"] == []
    assert result["fixed_replay_qualified"] is True
    assert result["physical_execution_qualified"] is False


@pytest.mark.parametrize("mutation", ["action_order", "rgb_hash", "limit", "positive_claim", "source_hash"])
def test_independent_audit_rejects_replay_mutations(tmp_path, mutation):
    from tools.benchmark.audit_causal_pair_stage import audit
    from tools.benchmark.replay_causal_pair_stage import replay

    source = source_fixture(tmp_path)
    output = tmp_path / "replay"
    replay(source, output)
    path = output / "result.json"
    result = json.loads(path.read_text())
    if mutation == "action_order":
        result["actions"][1], result["actions"][2] = result["actions"][2], result["actions"][1]
    elif mutation == "rgb_hash":
        result["actions"][2]["rgb_sha256"] = "0" * 64
    elif mutation == "limit":
        result["wall_wait_ns"] += 1
    elif mutation == "positive_claim":
        result["fusion_eligible"] = True
    else:
        result["source_events_sha256"] = "0" * 64
    path.write_text(json.dumps(result, indent=2))
    audited = audit(source, output)
    assert audited["failures"]
    assert audited["fixed_replay_qualified"] is False


def test_audit_rejects_changed_source_after_replay(tmp_path):
    from tools.benchmark.audit_causal_pair_stage import audit
    from tools.benchmark.replay_causal_pair_stage import replay

    source = source_fixture(tmp_path)
    output = tmp_path / "replay"
    replay(source, output)
    rows = [json.loads(line) for line in (source / "events.jsonl").read_text().splitlines()]
    changed = copy.deepcopy(rows)
    changed[3]["arrival_monotonic_ns"] += 1
    (source / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in changed))
    result = audit(source, output)
    assert "source events hash" in result["failures"]


def test_audit_rejects_changed_camera_info_payload_after_replay(tmp_path):
    from tools.benchmark.audit_causal_pair_stage import audit
    from tools.benchmark.replay_causal_pair_stage import replay

    source = source_fixture(tmp_path)
    output = tmp_path / "replay"
    replay(source, output)
    (source / "camera-info-messages/2000000.pb").write_bytes(b"changed-camera-info")
    result = audit(source, output)
    assert "camera info payload" in result["failures"]
