"""Prospective byte provenance for a bounded ROS build; no Docker is started."""

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest

COLLECTOR_FILES = ("CMakeLists.txt", "package.xml", "px4_odometry_source.cpp", "README.md")


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def pinned_tree(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "config", "user.name", "FlyDrones Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "msg").mkdir()
    (repo / "msg" / "VehicleOdometry.msg").write_bytes(b"uint64 timestamp\nuint8 quality\n")
    (repo / "package.xml").write_bytes(b"<package>\n</package>\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixed messages")
    commit = _git(repo, "rev-parse", "HEAD")
    (repo / "msg" / "VehicleOdometry.msg").write_bytes(b"uint64 timestamp\r\nuint8 quality\r\n")
    collector = tmp_path / "collector"
    collector.mkdir()
    for name in COLLECTOR_FILES:
        (collector / name).write_bytes(f"fixed {name}\n".encode())
    return repo, commit, collector


def test_build_source_module_exists():
    assert importlib.util.find_spec("flydrones.connectome_training.px4_ros2_build_source")


def test_prepared_build_consumes_raw_git_bytes_not_worktree_line_endings(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import (
        prepare_workspace,
        verify_workspace,
    )

    repo, commit, collector = pinned_tree
    destination = tmp_path / "build-input"
    profile = prepare_workspace(repo, commit, collector, destination)
    built_msg = destination / "src/px4_msgs/msg/VehicleOdometry.msg"
    assert built_msg.read_bytes() == b"uint64 timestamp\nuint8 quality\n"
    assert profile["git_commit"] == commit
    assert profile["build_command"] == "colcon build --base-paths src --packages-select px4_msgs flydrones_px4_ros2_source --executor sequential --parallel-workers 1 --event-handlers console_direct+"
    assert profile["files"]["src/px4_msgs/msg/VehicleOdometry.msg"] == hashlib.sha256(built_msg.read_bytes()).hexdigest()
    assert verify_workspace(destination)["file_count"] == 2 + len(COLLECTOR_FILES)


def test_verifier_rejects_changed_actual_build_file(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import prepare_workspace, verify_workspace

    repo, commit, collector = pinned_tree
    destination = tmp_path / "build-input"
    prepare_workspace(repo, commit, collector, destination)
    (destination / "src/px4_msgs/msg/VehicleOdometry.msg").write_bytes(b"uint64 timestamp\r\nuint8 quality\r\n")
    with pytest.raises(ValueError, match="source bytes changed"):
        verify_workspace(destination)


def test_verifier_rejects_unlisted_build_file_and_changed_profile(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import prepare_workspace, verify_workspace

    repo, commit, collector = pinned_tree
    destination = tmp_path / "build-input"
    prepare_workspace(repo, commit, collector, destination)
    extra = destination / "src/px4_msgs/msg/Unexpected.msg"
    extra.write_bytes(b"uint8 x\n")
    with pytest.raises(ValueError, match="file set changed"):
        verify_workspace(destination)
    extra.unlink()
    profile = destination / "build-source-profile.json"
    data = json.loads(profile.read_text(encoding="utf-8"))
    data["git_commit"] = "0" * 40
    profile.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="profile changed"):
        verify_workspace(destination)


def test_preparation_rejects_wrong_commit_and_existing_destination(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import prepare_workspace

    repo, commit, collector = pinned_tree
    with pytest.raises(ValueError, match="HEAD does not match"):
        prepare_workspace(repo, "0" * 40, collector, tmp_path / "wrong")
    destination = tmp_path / "build-input"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        prepare_workspace(repo, commit, collector, destination)


def test_preparation_rejects_symlink_git_mode(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import prepare_workspace

    repo, _, collector = pinned_tree
    link_blob = subprocess.run(
        ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
        input=b"VehicleOdometry.msg", capture_output=True, check=True,
    ).stdout.decode().strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{link_blob},msg/Link.msg")
    _git(repo, "commit", "-qm", "add symlink")
    commit = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="unsupported git mode"):
        prepare_workspace(repo, commit, collector, tmp_path / "build-input")


def _replace_directory_with_link(source: Path, target: Path):
    source.rename(target)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(source), str(target)],
                       check=True, capture_output=True)
    else:
        source.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("relative", ["src", "src/px4_msgs/msg"])
def test_verifier_rejects_linked_build_directory(pinned_tree, tmp_path, relative):
    from flydrones.connectome_training.px4_ros2_build_source import prepare_workspace, verify_workspace

    repo, commit, collector = pinned_tree
    destination = tmp_path / "build-input"
    prepare_workspace(repo, commit, collector, destination)
    source = destination / relative
    target = tmp_path / ("external-" + relative.replace("/", "-"))
    _replace_directory_with_link(source, target)
    try:
        with pytest.raises(ValueError, match="source link found"):
            verify_workspace(destination)
    finally:
        source.rmdir() if os.name == "nt" else source.unlink()


def test_preparation_rejects_oversize_blob_before_loading(pinned_tree, tmp_path, monkeypatch):
    from flydrones.connectome_training import px4_ros2_build_source as source

    repo, commit, collector = pinned_tree
    real_git = source._git

    def bounded_git(repository, *arguments):
        if arguments[:2] == ("cat-file", "-s"):
            return b"10000001\n"
        if arguments[:2] == ("cat-file", "blob"):
            raise AssertionError("oversized blob was loaded before the size check")
        return real_git(repository, *arguments)

    monkeypatch.setattr(source, "_git", bounded_git)
    with pytest.raises(ValueError, match="git blob exceeds bound"):
        source.prepare_workspace(repo, commit, collector, tmp_path / "build-input")


def test_link_check_works_on_supported_python_without_is_junction(tmp_path, monkeypatch):
    from flydrones.connectome_training.px4_ros2_build_source import _is_link

    monkeypatch.delattr(Path, "is_junction")
    if os.name == "nt":
        with pytest.raises(RuntimeError, match="Python 3.12"):
            _is_link(tmp_path)
    else:
        assert _is_link(tmp_path) is False
