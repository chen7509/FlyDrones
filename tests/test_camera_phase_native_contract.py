from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native" / "camera_phase"
BUILD_SCRIPT = ROOT / "tools" / "build_camera_phase_native_wsl.sh"


def _read(path: Path) -> str:
    assert path.is_file(), f"required native camera-phase file is missing: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "relative",
    [
        "CMakeLists.txt",
        "include/flydrones/camera_phase_native.hpp",
        "src/camera_phase_native.cc",
        "src/main.cc",
        "tests/camera_phase_native_test.cc",
    ],
)
def test_native_project_contains_only_declared_source_files(relative: str):
    _read(NATIVE / relative)
    assert not (NATIVE / "vendor").exists()
    assert not (NATIVE / "third_party").exists()


def test_cmake_contract_is_cxx17_and_uses_only_installed_dependencies():
    cmake = _read(NATIVE / "CMakeLists.txt")
    assert "flydrones_camera_phase_native" in cmake
    assert re.search(r"CXX_STANDARD\s+17\b", cmake)
    assert "CXX_STANDARD_REQUIRED ON" in cmake
    packages = set(re.findall(r"find_package\(\s*([^\s\)]+)", cmake))
    assert packages == {"gz-transport13", "gz-msgs10", "Threads"}
    assert "FetchContent" not in cmake
    assert "ExternalProject" not in cmake
    assert "add_subdirectory" not in cmake


def test_header_exposes_frozen_schedule_queue_and_lifecycle_interfaces():
    header = _read(NATIVE / "include" / "flydrones" / "camera_phase_native.hpp")
    for token in (
        "struct TriggerSlot",
        "class TriggerScheduler",
        "std::vector<TriggerSlot> Advance(std::int64_t simNs)",
        "struct EventRecord",
        "class BoundedEventQueue",
        "bool TryPush(EventRecord event)",
        "enum class LifecycleState",
    ):
        assert token in header
    assert "std::vector<std::uint8_t>" not in header
    assert "std::string payload" not in header


def test_callbacks_are_metadata_only_and_never_access_image_payload():
    implementation = _read(NATIVE / "src" / "camera_phase_native.cc")
    assert "ByteSizeLong()" in implementation
    assert not re.search(r"\b(?:image|msg|message)\s*\.\s*data\s*\(", implementation)
    assert not re.search(r"->\s*data\s*\(", implementation)
    assert "image_payload_bytes_seen" in implementation
    for field in (
        "source_sha256",
        "executable_sha256",
        "gz_transport_version",
        "gz_msgs_version",
    ):
        assert field in implementation


def test_cli_contract_has_both_modes_all_options_and_stable_exit_codes():
    main = _read(NATIVE / "src" / "main.cc")
    for token in (
        "observe",
        "schedule-observe",
        "--vehicle-count",
        "--subscriber-count",
        "--output",
        "--ready-marker",
        "--completion-marker",
        "--duration-s",
        "--poll-interval-ms",
        "--flush-interval-ms",
        "--completion-drain-ms",
        "--observe-triggers",
        "--stop-after-trigger-count",
    ):
        assert token in main

    header = _read(NATIVE / "include" / "flydrones" / "camera_phase_native.hpp")
    implementation = _read(NATIVE / "src" / "camera_phase_native.cc")
    assert "bool observeTriggers{true}" in header
    assert "if (options.observeTriggers)" in implementation
    for token in (
        "kComplete = 0",
        "kIntegrityRejected = 2",
        "kRuntimeFailure = 3",
        "kSchedulerFailure = 4",
        "kInvalidCli = 64",
    ):
        assert token in main


def test_build_script_is_out_of_tree_and_checks_exact_pkg_config_dependencies():
    script = _read(BUILD_SCRIPT)
    assert "build/native-camera-phase" in script
    assert "cmake -S" in script and "-B" in script
    assert "gz-transport13" in script
    assert "gz-msgs10" in script
    assert "sha256sum" in script
    assert "native/camera_phase/build" not in script


@pytest.mark.skipif(os.name != "posix", reason="script refusal is exercised inside WSL in CI")
def test_build_script_refuses_missing_pkg_config_packages(tmp_path: Path):
    fake_pkg_config = tmp_path / "pkg-config"
    fake_pkg_config.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_pkg_config.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    result = subprocess.run(
        ["bash", str(BUILD_SCRIPT), "--check-dependencies"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "missing required pkg-config package" in result.stderr
