"""Actual artifact application with synthetic calibration/rig/PX4 columns."""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest
from scipy.spatial.transform import Rotation


def base():
    spec = importlib.util.spec_from_file_location(
        "px4_calibration_fixture", Path(__file__).with_name("test_px4_camera_source.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact(tmp_path, *, offset="0.05", **changes):
    f = base()
    binding = f.rig(tmp_path)
    camera = {
        "camera_model": "pinhole",
        "intrinsics": [100.0, 100.0, 80.0, 60.0],
        "distortion_model": "radtan",
        "distortion_coeffs": [0.0, 0.0, 0.0, 0.0],
        "resolution": [160, 120],
        "rostopic": "/camera",
        "T_cam_imu": [[0.0, -1.0, 0.0, 1.0], [1.0, 0.0, 0.0, 2.0], [0.0, 0.0, 1.0, 3.0], [0.0, 0.0, 0.0, 1.0]],
        "timeshift_cam_imu": offset,
    }
    ch = f.write_json(tmp_path / "camchain.yaml", {"cam0": camera})
    results = b"synthetic result fixture; not a Kalibr measurement"
    (tmp_path / "results.txt").write_bytes(results)
    doc = {
        "schema": "flydrones-kalibr-artifact-binding-v1",
        "rig_sha256": binding.sha256,
        "body_id": binding.body_id,
        "camera_id": binding.camera_id,
        "camera_key": "cam0",
        "imu_contract": "px4-d6f12ad-sensor-combined-frd-interval-mean-v1",
        "camchain": {"path": "camchain.yaml", "sha256": ch},
        "results": {"path": "results.txt", "sha256": hashlib.sha256(results).hexdigest()},
    }
    doc.update(changes)
    bh = f.write_json(tmp_path / "artifact.json", doc)
    return f, binding, tmp_path / "artifact.json", bh


def load(tmp_path, **changes):
    f, rig, path, sha = artifact(tmp_path, **changes)
    api = importlib.import_module("flydrones.benchmark.kalibr_camera_consumption")
    return f, rig, api.KalibrCameraArtifact.load(path, sha, rig)


def produce(f, binding, calibration, *, source=None, frames=None):
    p = f.api().Px4UlogCameraSource.from_decoded_topics(source or f.topics(), binding)
    frames = [1_000_000_000] if frames is None else frames
    declaration = {
        "schema": "flydrones-camera-px4-epoch-declaration-v1",
        "relation": "same-px4-boot-epoch",
        "rig_sha256": binding.sha256,
        "ulog_sha256": p.ulog_sha256,
        "frame_sequence_sha256": hashlib.sha256(json.dumps(frames, separators=(",", ":")).encode()).hexdigest(),
    }
    return p.produce(frames, epoch_declaration=declaration, calibration_artifact=calibration)


def test_transform_inverse_projection_and_no_calibration_grant(tmp_path):
    _, _, c = load(tmp_path)
    assert c.body_from_camera()[1] == pytest.approx([-2.0, 1.0, -3.0])
    projected = c.project_imu_point([2.0, 4.0, 6.0])
    assert projected == pytest.approx([80.0 - 100.0 / 3.0, 60.0 + 400.0 / 9.0])
    assert c.record()["camera_calibration_qualified"] is False


def test_nonzero_radtan_projection_consumes_intrinsics_and_distortion(tmp_path):
    f, binding, path, _ = artifact(tmp_path)
    chain = json.loads((tmp_path / "camchain.yaml").read_text())
    chain["cam0"]["distortion_coeffs"] = [0.1, 0.01, 0.02, -0.03]
    ch = f.write_json(tmp_path / "camchain.yaml", chain)
    doc = json.loads(path.read_text())
    doc["camchain"]["sha256"] = ch
    bh = f.write_json(path, doc)
    api = importlib.import_module("flydrones.benchmark.kalibr_camera_consumption")
    c = api.KalibrCameraArtifact.load(path, bh, binding)
    assert c.project_imu_point([0.0, 0.0, 1.0]) == pytest.approx([104.9931640625, 112.486328125])


def test_signed_fractional_offset_preserves_integer_precision(tmp_path):
    _, _, c = load(tmp_path, offset="-0.0000000015")
    assert c.lookup_ns(2**53 + 9) == 2**53 + 7
    assert c.record()["timeshift_rounding_error_ns"] == "-0.5"


def test_actual_producer_uses_shifted_state_and_artifact_inverse(tmp_path):
    f, binding, c = load(tmp_path)
    source = f.topics()
    source["vehicle_local_position"]["x"][:] = [1.0, 10.0, 100.0]
    result = produce(f, binding, c, source=source)
    row = result["records"][0]
    assert row["frame_ns"] == 1_000_000_000
    assert row["calibration_lookup"]["imu_lookup_ns"] == 1_050_000_000
    assert row["geometry"]["camera_pose_enu_xyzw"][:3] == pytest.approx([3.0, 8.0, 6.0])
    assert Rotation.from_quat(row["geometry"]["camera_pose_enu_xyzw"][3:]).apply([1.0, 0.0, 0.0]) == pytest.approx(
        [-1.0, 0.0, 0.0]
    )
    assert result["camera_calibration_qualified"] is False
    assert row["host_receipt_ns"] is None


def test_calibration_shift_never_rescues_original_heading_refusal(tmp_path):
    f, binding, c = load(tmp_path)
    source = f.topics()
    source["vehicle_local_position"]["heading_good_for_control"][0] = 0
    result = produce(f, binding, c, source=source)
    assert result["records"][0]["geometry"] is None
    assert result["records"][0]["reasons"]


def test_shifted_state_must_pass_same_health_gate(tmp_path):
    f, binding, c = load(tmp_path, offset="0.25")
    row = produce(f, binding, c)["records"][0]
    assert row["geometry"] is None
    assert any(r.startswith("calibration_lookup:") for r in row["reasons"])


@pytest.mark.parametrize("changes", [{"rig_sha256": "a" * 64}, {"imu_contract": "raw-device-imu"}])
def test_wrong_rig_or_imu_coordinate_contract_is_refused(tmp_path, changes):
    with pytest.raises(ValueError):
        load(tmp_path, **changes)


def test_loading_does_not_claim_artifact_applied_to_state(tmp_path):
    _, _, c = load(tmp_path)
    assert "artifact_applied" not in c.record()
    assert c.record()["artifact_parameters_loaded"] is True


def test_timeshift_bound_is_not_rounded_before_comparison(tmp_path):
    with pytest.raises(ValueError, match="timeshift"):
        load(tmp_path, offset="1.0000000000000000000000000000001")


@pytest.mark.parametrize(
    "offset,frames,bad", [("-0.000000001", [0, 1_000_000_100], 0), ("0.000000001", [1_000_000_100, 2**63 - 1], 1)]
)
def test_shift_outside_boot_range_retains_all_original_rows(tmp_path, offset, frames, bad):
    f, binding, c = load(tmp_path, offset=offset)
    result = produce(f, binding, c, frames=frames)
    assert [r["frame_ns"] for r in result["records"]] == frames
    refused = result["records"][bad]
    assert refused["geometry"] is None
    assert refused["calibration_lookup"]["imu_lookup_ns"] is None
    assert "calibration_lookup:lookup_timestamp_outside_boot_range" in refused["reasons"]
    assert result["records"][1 - bad]["geometry"] is not None


def cli(tmp_path, monkeypatch, *, corrupt=False):
    import sys

    from tools.benchmark import produce_px4_camera_file as command

    f, binding, bundle, bundle_sha = artifact(tmp_path)
    raw = b"constructed parser fixture, not a ULog"
    (tmp_path / "source.ulg").write_bytes(raw)
    uh = hashlib.sha256(raw).hexdigest()
    fh = f.write_json(tmp_path / "frames.json", {"frame_ns": [1_000_000_000]})
    eh = f.write_json(
        tmp_path / "epoch.json",
        {
            "schema": "flydrones-camera-px4-epoch-declaration-v1",
            "relation": "same-px4-boot-epoch",
            "rig_sha256": binding.sha256,
            "ulog_sha256": uh,
            "frame_sequence_sha256": hashlib.sha256(b"[1000000000]").hexdigest(),
        },
    )
    if corrupt:
        (tmp_path / "results.txt").write_bytes(b"changed")

    def decoded(path, digest, rig):
        p = command.Px4UlogCameraSource.from_decoded_topics(f.topics(), rig)
        p.ulog_sha256 = digest  # Explicit parser replacement, never real byte-reader qualification.
        return p

    monkeypatch.setattr(command.Px4UlogCameraSource, "from_ulog", decoded)
    out = tmp_path / "produced"
    argv = [
        "producer",
        "--output",
        str(out),
        "--ulog",
        str(tmp_path / "source.ulg"),
        "--ulog-sha256",
        uh,
        "--rig",
        str(tmp_path / "rig.json"),
        "--rig-sha256",
        binding.sha256,
        "--frames-json",
        str(tmp_path / "frames.json"),
        "--frames-sha256",
        fh,
        "--body-id",
        binding.body_id,
        "--camera-id",
        binding.camera_id,
        "--epoch-declaration-json",
        str(tmp_path / "epoch.json"),
        "--epoch-sha256",
        eh,
        "--calibration-artifact",
        str(bundle),
        "--calibration-sha256",
        bundle_sha,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return command.main(), out, bundle


def test_real_cli_path_snapshots_and_applies_artifact_with_parser_replaced(tmp_path, monkeypatch):
    code, out, bundle = cli(tmp_path, monkeypatch)
    assert code == 0
    assert (out / "inputs/calibration/artifact.json").read_bytes() == bundle.read_bytes()
    row = json.loads((out / "rows.jsonl").read_text())
    assert row["calibration_lookup"]["imu_lookup_ns"] == 1_050_000_000
    assert row["geometry"] is not None
    assert json.loads((out / "completion.json").read_text())["camera_calibration_qualified"] is False


def test_real_cli_retains_failure_when_referenced_results_change(tmp_path, monkeypatch):
    code, out, _ = cli(tmp_path, monkeypatch, corrupt=True)
    assert code == 1
    assert (out / "request.json").exists()
    result = json.loads((out / "completion.json").read_text())
    assert result["status"] == "failed"
    assert result["camera_calibration_qualified"] is False
