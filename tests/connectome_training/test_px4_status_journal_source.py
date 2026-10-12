"""Isolated source derivation tests; no Docker or ROS process starts."""

import hashlib
import json

import pytest

from flydrones.connectome_training import px4_status_journal_source as subject


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def sources(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    files = {
        "src/px4_msgs/msg/EstimatorStatus.msg": b"status message",
        "src/flydrones_px4_ros2_source/package.xml": b"old collector",
    }
    for relative, contents in files.items():
        path = parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    profile = {
        "schema": subject.PARENT_SCHEMA,
        "git_commit": subject.PX4_MSGS_COMMIT,
        "build_started": False,
        "files": {name: _sha(data) for name, data in files.items()},
    }
    data = (json.dumps(profile, sort_keys=True) + "\n").encode()
    (parent / "build-source-profile.json").write_bytes(data)
    (parent / "build-source-profile.sha256").write_text(_sha(data) + "\n")
    (parent / "parent-build-source-profile.json").write_text("{}\n")
    monkeypatch.setattr(subject, "PARENT_PROFILE_SHA256", _sha(data))
    monkeypatch.setattr(subject, "PARENT_FILE_COUNT", len(files))
    monkeypatch.setattr(subject, "PX4_STATUS_SHA256", _sha(files["src/px4_msgs/msg/EstimatorStatus.msg"]))
    monkeypatch.setattr(subject, "verify_parent_workspace", lambda _path: {"file_count": len(files)})
    additions = {name: f"collector {name}".encode() for name in subject.COLLECTOR_FILES}
    monkeypatch.setattr(subject, "COLLECTOR_SHA256", {name: _sha(data) for name, data in additions.items()})
    monkeypatch.setattr(subject, "_git_blob", lambda _repo, name: additions[name])
    return parent, additions, tmp_path / "derived"


def test_derivation_keeps_parent_bytes_and_lists_every_new_file(sources, tmp_path):
    parent, additions, derived = sources
    profile = subject.derive_source(parent, tmp_path, derived)
    assert len(profile["files"]) == 5
    assert profile["files"]["src/px4_msgs/msg/EstimatorStatus.msg"] == _sha(b"status message")
    for name, data in additions.items():
        assert (derived / "src/flydrones_px4_status_ros2_source" / name).read_bytes() == data
    assert not (derived / "build").exists()
    assert not (derived / "install").exists()
    assert subject.verify_source(derived)["file_count"] == 5


@pytest.mark.parametrize("mutation", ["changed", "extra", "missing", "build_output"])
def test_tampered_or_unlisted_source_and_prior_build_output_refused(sources, tmp_path, mutation):
    parent, _, derived = sources
    subject.derive_source(parent, tmp_path, derived)
    target = derived / "src/flydrones_px4_status_ros2_source/CMakeLists.txt"
    if mutation == "changed":
        target.write_bytes(b"tampered")
    elif mutation == "extra":
        (derived / "src/px4_msgs/extra.msg").write_bytes(b"extra")
    elif mutation == "missing":
        target.unlink()
    else:
        (derived / "build").mkdir()
    with pytest.raises(ValueError):
        subject.verify_source(derived)
    if mutation == "build_output":
        assert subject.verify_source(derived, allow_build_output=True)["verified"]


def test_wrong_parent_profile_or_existing_target_refused(sources, tmp_path):
    parent, _, derived = sources
    (parent / "build-source-profile.json").write_text("{}\n")
    with pytest.raises(ValueError):
        subject.derive_source(parent, tmp_path, derived)
    assert not derived.exists()
    derived.mkdir()
    with pytest.raises(FileExistsError):
        subject.derive_source(parent, tmp_path, derived)


def test_linked_new_collector_path_or_replaced_manifest_refused(sources, tmp_path):
    parent, _, derived = sources
    subject.derive_source(parent, tmp_path, derived)
    manifest = derived / "source-profile.json"
    manifest.write_text("{}\n")
    with pytest.raises(ValueError):
        subject.verify_source(derived)


def test_source_profile_disclaims_firmware_and_capture(sources, tmp_path):
    parent, _, derived = sources
    profile = subject.derive_source(parent, tmp_path, derived)
    assert profile["firmware_compiled_verified"] is False
    assert profile["live_source_authenticated"] is False
    assert profile["training_eligible"] is False
