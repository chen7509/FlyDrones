"""Prospective byte provenance for a bounded ROS build; no Docker is started."""

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest

COLLECTOR_FILES = ("CMakeLists.txt", "package.xml", "px4_odometry_source.cpp", "README.md")
FULL_COLLECTOR_FILES = COLLECTOR_FILES + ("full_odometry_fields.hpp",)


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


def test_full_state_profile_seals_new_header_without_changing_legacy_profile(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import (
        prepare_workspace,
        verify_workspace,
    )

    repo, commit, collector = pinned_tree
    (collector / "full_odometry_fields.hpp").write_bytes(b"fixed full state header\n")
    destination = tmp_path / "full-build-input"
    profile = prepare_workspace(repo, commit, collector, destination, collector_files=FULL_COLLECTOR_FILES)
    header = destination / "src/flydrones_px4_ros2_source/full_odometry_fields.hpp"
    assert profile["files"]["src/flydrones_px4_ros2_source/full_odometry_fields.hpp"] == hashlib.sha256(header.read_bytes()).hexdigest()
    assert profile["schema"] == "flydrones.px4_ros2_build_source.v2"
    assert profile["build_command"].startswith("MAKEFLAGS=-j1 colcon build ")
    assert verify_workspace(destination)["file_count"] == 2 + len(FULL_COLLECTOR_FILES)
    header.write_bytes(b"different\n")
    with pytest.raises(ValueError, match="source bytes changed"):
        verify_workspace(destination)


def test_full_state_profile_requires_exact_supported_collector_set(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import prepare_workspace

    repo, commit, collector = pinned_tree
    with pytest.raises(ValueError, match="unsupported collector file set"):
        prepare_workspace(repo, commit, collector, tmp_path / "invalid", collector_files=("README.md",))


def test_current_collector_cannot_be_prepared_without_its_header(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import prepare_workspace

    repo, commit, collector = pinned_tree
    (collector / "px4_odometry_source.cpp").write_bytes(b'#include "full_odometry_fields.hpp"\n')
    (collector / "full_odometry_fields.hpp").write_bytes(b"#pragma once\n")
    with pytest.raises(ValueError, match="full-state header requires v2 source profile"):
        prepare_workspace(repo, commit, collector, tmp_path / "invalid")


def test_full_state_workspace_can_derive_from_verified_legacy_git_blob_tree(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import (
        derive_full_state_workspace,
        prepare_workspace,
        verify_workspace,
    )

    repo, commit, collector = pinned_tree
    legacy = tmp_path / "legacy"
    prepare_workspace(repo, commit, collector, legacy)
    (collector / "full_odometry_fields.hpp").write_bytes(b"#pragma once\n")
    (collector / "px4_odometry_source.cpp").write_bytes(b'#include "full_odometry_fields.hpp"\n')
    full = tmp_path / "full"
    profile = derive_full_state_workspace(legacy, collector, full)
    assert profile["git_commit"] == commit
    assert profile["parent_source_profile_sha256"] == hashlib.sha256(
        (legacy / "build-source-profile.json").read_bytes()).hexdigest()
    assert (full / "src/px4_msgs/msg/VehicleOdometry.msg").read_bytes() == b"uint64 timestamp\nuint8 quality\n"
    assert verify_workspace(full)["file_count"] == 2 + len(FULL_COLLECTOR_FILES)


def test_full_state_derivation_rejects_corrupt_parent(pinned_tree, tmp_path):
    from flydrones.connectome_training.px4_ros2_build_source import (
        derive_full_state_workspace,
        prepare_workspace,
    )

    repo, commit, collector = pinned_tree
    legacy = tmp_path / "legacy"
    prepare_workspace(repo, commit, collector, legacy)
    (legacy / "src/px4_msgs/msg/VehicleOdometry.msg").write_bytes(b"bad")
    (collector / "full_odometry_fields.hpp").write_bytes(b"#pragma once\n")
    with pytest.raises(ValueError, match="source bytes changed"):
        derive_full_state_workspace(legacy, collector, tmp_path / "full")


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
