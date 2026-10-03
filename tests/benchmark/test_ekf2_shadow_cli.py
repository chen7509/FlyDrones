"""The fixed evidence reader must fail closed and never rewrite evidence."""

import hashlib
import json
import zipfile

import numpy as np
import pytest

from tools.benchmark.audit_ekf2_shadow import _audit_verified_archive, write_report_once


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path, *, bad_schema=False, extra=None):
    root = "openvins-texture-dev/"
    ulog_path = "episode-v1/px4-ulog/log/2026-10-03/01_28_24.ulg"
    ulog = b"ULogfake"
    frames = [
        {"frame_ns": 0, "path": "rgb-frames/0.ppm", "width": 1, "height": 1,
         "sha256": _sha(b"P6 fake")},
        {"frame_ns": 100_000_000, "path": "rgb-frames/100000000.ppm",
         "width": 1, "height": 1, "sha256": _sha(b"P6 fake")},
    ]
    members = {
        "episode-v1/rgb-capture-manifest.json": json.dumps({
            "schema": "wrong" if bad_schema else "flydrones-rgb-capture-v1",
            "frames": frames}).encode(),
        "episode-v1/px4-ulog-manifest.json": json.dumps({
            "schema": "flydrones-px4-ulog-capture-v1",
            "logs": [{"path": ulog_path.removeprefix("episode-v1/"),
                      "bytes": len(ulog), "sha256": _sha(ulog),
                      "valid_header": True}]}).encode(),
        "episode-v1/result.json": json.dumps({
            "status": "out_of_bounds", "odometry_source": "gazebo_model_truth",
            "camera_pose_source": "gazebo_model_truth",
            "px4_ulogs": [{"path": ulog_path.removeprefix("episode-v1/"),
                            "bytes": len(ulog), "sha256": _sha(ulog),
                            "valid_header": True}]}).encode(),
        ulog_path: ulog,
        "episode-v1/rgb-frames/0.ppm": b"P6 fake",
        "episode-v1/rgb-frames/100000000.ppm": b"P6 fake",
    }
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, content in members.items():
            z.writestr(root + name, content)
        for name, content in extra or []:
            z.writestr(name, content)
    index = tmp_path / "source.sha256.json"
    index.write_text(json.dumps({
        "schema": "flydrones-openvins-texture-dev-evidence-v1",
        "archive_sha256": _sha(archive.read_bytes()),
        "file_count": len(members),
        "files": [{"path": name, "bytes": len(content), "sha256": _sha(content)}
                  for name, content in members.items()],
    }))
    return archive, index, _sha(archive.read_bytes()), _sha(ulog)


def _topics(_path):
    fast = np.array([50_000], np.int64)
    local = {key: np.ones(1) for key in (
        "x", "y", "z", "vx", "vy", "vz", "xy_valid", "z_valid",
        "v_xy_valid", "v_z_valid", "heading_good_for_control")}
    local.update(timestamp=fast, dead_reckoning=np.zeros(1))
    return {
        "vehicle_local_position": local,
        "vehicle_attitude": {"timestamp": fast, "q[0]": np.ones(1),
                             "q[1]": np.zeros(1), "q[2]": np.zeros(1),
                             "q[3]": np.zeros(1)},
        "estimator_status": {"timestamp": fast, "filter_fault_flags": np.zeros(1)},
        "estimator_status_flags": {"timestamp": np.array([0]),
                                   "cs_gnss_pos": np.ones(1),
                                   "cs_ev_pos": np.zeros(1)},
    }


def _audit(fixture, **kwargs):
    archive, index, archive_sha, ulog_sha = fixture
    return _audit_verified_archive(
        archive, index, expected_archive_sha256=archive_sha,
        expected_ulog_sha256=ulog_sha, read_ulog=kwargs.get("read_ulog", _topics))


def test_valid_archive_retains_missing_early_frame_and_cleans_ulog(tmp_path):
    fixture = _fixture(tmp_path)
    extracted = []

    def reader(path):
        extracted.append(path)
        assert path.read_bytes() == b"ULogfake"
        return _topics(path)

    report = _audit(fixture, read_ulog=reader)
    assert report["frame_count"] == 2
    assert report["counts"] == {"valid": 1, "invalid": 0, "missing": 1}
    assert report["source_counts_healthy_estimates"] == {"gnss": 1}
    assert report["input_archive_sha256"] == fixture[2]
    assert report["input_ulog_sha256"] == fixture[3]
    assert report["eligible_for_live_capture"] is False
    assert not extracted[0].exists()


def test_tampered_archive_rejected_before_ulog_reader(tmp_path):
    fixture = _fixture(tmp_path)
    with fixture[0].open("ab") as f:
        f.write(b"tamper")
    with pytest.raises(ValueError, match="archive SHA"):
        _audit(fixture, read_ulog=lambda _: pytest.fail("must not read ULog"))


@pytest.mark.parametrize("extra", [
    [("openvins-texture-dev/episode-v1/../evil", b"x")],
    [("openvins-texture-dev/episode-v1/result.json", b"duplicate")],
])
def test_unsafe_or_duplicate_member_rejected(tmp_path, extra):
    fixture = _fixture(tmp_path, extra=extra)
    with pytest.raises(ValueError, match="member"):
        _audit(fixture, read_ulog=lambda _: pytest.fail("must not read ULog"))


def test_changed_required_manifest_rejected_even_when_index_is_resigned(tmp_path):
    fixture = _fixture(tmp_path, bad_schema=True)
    with pytest.raises(ValueError, match="RGB manifest"):
        _audit(fixture, read_ulog=lambda _: pytest.fail("must not read ULog"))


def test_index_mismatch_rejected_and_output_is_write_once(tmp_path):
    fixture = _fixture(tmp_path)
    index_data = json.loads(fixture[1].read_text())
    index_data["files"][0]["sha256"] = "0" * 64
    fixture[1].write_text(json.dumps(index_data))
    with pytest.raises(ValueError, match="index"):
        _audit(fixture)
    output = tmp_path / "report.json"
    write_report_once(output, {"first": True})
    with pytest.raises(FileExistsError):
        write_report_once(output, {"first": False})
    assert json.loads(output.read_text()) == {"first": True}


def test_reader_failure_leaves_no_output_or_extracted_ulog(tmp_path):
    fixture = _fixture(tmp_path)
    seen = []

    def reader(path):
        seen.append(path)
        raise RuntimeError("reader failed")

    with pytest.raises(RuntimeError, match="reader failed"):
        _audit(fixture, read_ulog=reader)
    assert not seen[0].exists()
    assert not (tmp_path / "report.json").exists()
