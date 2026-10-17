"""A source-only ROS interface overlay; never a compiled or live PX4 claim."""

import hashlib
import json
import os
import subprocess

import pytest


@pytest.fixture
def parent_tree(tmp_path, monkeypatch):
    from flydrones.connectome_training import px4_ros2_build_source as source

    repo = tmp_path / "px4_msgs"
    (repo / "msg").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    original = b"uint64 timestamp\nuint8 GPS_CHECK_FAIL_JAMMED = 11\n"
    replacement = b"uint64 timestamp\n"
    (repo / "msg/EstimatorStatus.msg").write_bytes(original)
    (repo / "msg/VehicleOdometry.msg").write_bytes(b"uint64 timestamp\n")
    (repo / "package.xml").write_bytes(b"<package/>\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "messages"], check=True)
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                     text=True).strip()
    collector = tmp_path / "collector"
    collector.mkdir()
    for name in source.FULL_COLLECTOR_FILES:
        (collector / name).write_bytes(name.encode() + b"\n")
    parent = tmp_path / "parent"
    source.prepare_workspace(repo, commit, collector, parent,
                             collector_files=source.FULL_COLLECTOR_FILES)
    monkeypatch.setattr(source, "PINNED_COMMIT", commit)
    monkeypatch.setattr(source, "PINNED_MESSAGE_SHA256",
                        hashlib.sha256(b"uint64 timestamp\n").hexdigest())
    monkeypatch.setattr(source, "PINNED_PARENT_V2_PROFILE_SHA256", hashlib.sha256(
        (parent / "build-source-profile.json").read_bytes()).hexdigest())
    monkeypatch.setattr(source, "PINNED_PARENT_FILE_COUNT", 3 + len(source.FULL_COLLECTOR_FILES))
    monkeypatch.setattr(source, "ROS_STATUS_BASE_SHA256", hashlib.sha256(original).hexdigest())
    monkeypatch.setattr(source, "PX4_STATUS_SHA256", hashlib.sha256(replacement).hexdigest())
    fixed_msg = tmp_path / "fixed-px4-status.msg"
    fixed_msg.write_bytes(replacement)
    return source, parent, fixed_msg, original, replacement


def test_exact_overlay_changes_only_status_and_preserves_parent(parent_tree, tmp_path):
    source, parent, fixed_msg, original, replacement = parent_tree
    original_profile = (parent / "build-source-profile.json").read_bytes()
    destination = tmp_path / "derived"
    profile = source.derive_status_overlay_workspace(parent, fixed_msg, destination)
    name = "src/px4_msgs/msg/EstimatorStatus.msg"
    assert profile["schema"] == "flydrones.px4_ros2_build_source.status_overlay.v1"
    assert profile["status_overlay"] == {
        "path": name,
        "replaces_sha256": hashlib.sha256(original).hexdigest(),
        "sha256": hashlib.sha256(replacement).hexdigest(),
    }
    assert profile["parent_source_profile_sha256"] == hashlib.sha256(original_profile).hexdigest()
    assert profile["build_started"] is False
    assert profile["firmware_compiled_verified"] is False
    assert profile["live_source_authenticated"] is False
    assert profile["training_eligible"] is False
    assert (destination / name).read_bytes() == replacement
    assert (parent / name).read_bytes() == original
    parent_files = json.loads(original_profile)["files"]
    assert {key for key in profile["files"] if profile["files"][key] != parent_files[key]} == {name}
    assert source.verify_workspace(destination)["file_count"] == len(parent_files)
    assert (parent / "build-source-profile.json").read_bytes() == original_profile


def test_wrong_px4_bytes_refuse(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    fixed_msg.write_bytes(b"uint64 wrong\n")
    with pytest.raises(ValueError, match="pinned PX4 status message"):
        source.derive_status_overlay_workspace(parent, fixed_msg, tmp_path / "wrong")


def test_linked_px4_message_refuses(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    linked = tmp_path / "linked.msg"
    try:
        linked.symlink_to(fixed_msg)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="linked"):
        source.derive_status_overlay_workspace(parent, linked, tmp_path / "linked-output")


def test_existing_destination_refuses(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    fixed_msg.write_bytes(b"uint64 timestamp\n")
    destination = tmp_path / "already-here"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        source.derive_status_overlay_workspace(parent, fixed_msg, destination)


def test_junction_or_symlink_ancestor_of_px4_message_refuses(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    link = tmp_path / "linked-parent"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(tmp_path)],
                       check=True, capture_output=True)
    else:
        link.symlink_to(tmp_path, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match="linked"):
            source.derive_status_overlay_workspace(parent, link / fixed_msg.name,
                                                   tmp_path / "linked-ancestor-output")
    finally:
        link.rmdir() if os.name == "nt" else link.unlink()


def test_corrupt_parent_or_wrong_original_status_refuses(parent_tree, tmp_path):
    source, parent, fixed_msg, original, _ = parent_tree
    status = parent / "src/px4_msgs/msg/EstimatorStatus.msg"
    status.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="source bytes changed"):
        source.derive_status_overlay_workspace(parent, fixed_msg, tmp_path / "corrupt")
    status.write_bytes(original)
    source.ROS_STATUS_BASE_SHA256 = "0" * 64
    with pytest.raises(ValueError, match="base EstimatorStatus"):
        source.derive_status_overlay_workspace(parent, fixed_msg, tmp_path / "wrong-base")


def test_derived_file_set_bytes_and_metadata_fail_closed(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    destination = tmp_path / "derived"
    source.derive_status_overlay_workspace(parent, fixed_msg, destination)
    status = destination / "src/px4_msgs/msg/EstimatorStatus.msg"
    status.write_bytes(b"changed")
    with pytest.raises(ValueError, match="source bytes changed"):
        source.verify_workspace(destination)
    status.write_bytes(fixed_msg.read_bytes())
    extra = destination / "src/px4_msgs/msg/Extra.msg"
    extra.write_bytes(b"uint8 x\n")
    with pytest.raises(ValueError, match="file set changed"):
        source.verify_workspace(destination)
    extra.unlink()
    profile_path = destination / "build-source-profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["status_overlay"]["replaces_sha256"] = "0" * 64
    changed = (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode()
    profile_path.write_bytes(changed)
    (destination / "build-source-profile.sha256").write_text(
        hashlib.sha256(changed).hexdigest() + "\n", encoding="ascii")
    with pytest.raises(ValueError, match="overlay metadata"):
        source.verify_workspace(destination)


def test_rehashed_nonstatus_file_cannot_be_relabelled_as_unchanged(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    destination = tmp_path / "derived"
    source.derive_status_overlay_workspace(parent, fixed_msg, destination)
    relative = "src/px4_msgs/package.xml"
    (destination / relative).write_bytes(b"<changed/>\n")
    profile_path = destination / "build-source-profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["files"][relative] = hashlib.sha256(b"<changed/>\n").hexdigest()
    changed = (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode()
    profile_path.write_bytes(changed)
    (destination / "build-source-profile.sha256").write_text(
        hashlib.sha256(changed).hexdigest() + "\n", encoding="ascii")
    with pytest.raises(ValueError, match="parent manifest"):
        source.verify_workspace(destination)


def test_wrong_parent_schema_or_commit_refuses(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    profile_path = parent / "build-source-profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["git_commit"] = "0" * 40
    changed = (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode()
    profile_path.write_bytes(changed)
    (parent / "build-source-profile.sha256").write_text(
        hashlib.sha256(changed).hexdigest() + "\n", encoding="ascii")
    with pytest.raises(ValueError, match="parent PX4 ROS commit"):
        source.derive_status_overlay_workspace(parent, fixed_msg, tmp_path / "bad-commit")


def _reseal_profile(destination, profile):
    changed = (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode()
    (destination / "build-source-profile.json").write_bytes(changed)
    (destination / "build-source-profile.sha256").write_text(
        hashlib.sha256(changed).hexdigest() + "\n", encoding="ascii")


@pytest.mark.parametrize("mutation", ["git_tree", "schema"])
def test_rehashed_derived_profile_cannot_relabel_parent_metadata(
    parent_tree, tmp_path, mutation,
):
    source, parent, fixed_msg, _, _ = parent_tree
    destination = tmp_path / "derived"
    source.derive_status_overlay_workspace(parent, fixed_msg, destination)
    profile = json.loads((destination / "build-source-profile.json").read_bytes())
    if mutation == "git_tree":
        profile["git_tree"] = "0" * 40
    else:
        profile["schema"] = "flydrones.px4_ros2_build_source.v2"
    _reseal_profile(destination, profile)
    with pytest.raises(ValueError, match="overlay|canonical"):
        source.verify_workspace(destination)


def test_downgrade_with_removed_overlay_marker_still_refuses(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    destination = tmp_path / "derived"
    source.derive_status_overlay_workspace(parent, fixed_msg, destination)
    (destination / "parent-build-source-profile.json").unlink()
    profile = json.loads((destination / "build-source-profile.json").read_bytes())
    profile["schema"] = "flydrones.px4_ros2_build_source.v2"
    profile.pop("status_overlay")
    _reseal_profile(destination, profile)
    with pytest.raises(ValueError, match="overlay|canonical"):
        source.verify_workspace(destination)


def test_downgrade_with_third_status_bytes_and_no_marker_refuses(parent_tree, tmp_path):
    source, parent, fixed_msg, _, _ = parent_tree
    destination = tmp_path / "derived"
    source.derive_status_overlay_workspace(parent, fixed_msg, destination)
    (destination / "parent-build-source-profile.json").unlink()
    third = b"uint64 timestamp\nuint8 different = 17\n"
    (destination / source.STATUS_RELATIVE).write_bytes(third)
    profile = json.loads((destination / "build-source-profile.json").read_bytes())
    profile["schema"] = "flydrones.px4_ros2_build_source.v2"
    profile["files"][source.STATUS_RELATIVE] = hashlib.sha256(third).hexdigest()
    for key in ("status_overlay", "parent_source_profile_sha256",
                "firmware_compiled_verified", "live_source_authenticated",
                "training_eligible"):
        profile.pop(key)
    _reseal_profile(destination, profile)
    with pytest.raises(ValueError, match="canonical"):
        source.verify_workspace(destination)


@pytest.mark.parametrize("seal_name", [
    "build-source-profile.json", "build-source-profile.sha256",
])
def test_linked_parent_seal_refuses_before_derivation(
    parent_tree, tmp_path, monkeypatch, seal_name,
):
    source, parent, fixed_msg, _, _ = parent_tree
    original_is_link = source._is_link
    linked_seal = parent / seal_name
    monkeypatch.setattr(
        source, "_is_link", lambda path: path == linked_seal or original_is_link(path),
    )
    with pytest.raises(ValueError, match="link"):
        source.derive_status_overlay_workspace(parent, fixed_msg, tmp_path / "derived")
    assert not (tmp_path / "derived").exists()


@pytest.mark.parametrize("seal_name", [
    "build-source-profile.json", "build-source-profile.sha256",
])
def test_linked_derived_seal_refuses_verification(
    parent_tree, tmp_path, monkeypatch, seal_name,
):
    source, parent, fixed_msg, _, _ = parent_tree
    destination = tmp_path / "derived"
    source.derive_status_overlay_workspace(parent, fixed_msg, destination)
    original_is_link = source._is_link
    linked_seal = destination / seal_name
    monkeypatch.setattr(
        source, "_is_link", lambda path: path == linked_seal or original_is_link(path),
    )
    with pytest.raises(ValueError, match="link"):
        source.verify_workspace(destination)
