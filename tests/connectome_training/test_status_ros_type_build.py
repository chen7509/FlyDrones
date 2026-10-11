"""One-shot status type build admission tests; never run Docker here."""

import json
from types import SimpleNamespace

import pytest

from tools.connectome import run_status_ros_type_build as build


def test_run_profile_pins_derived_source_and_bounded_command():
    profile = build._profile()
    assert profile["source_profile_sha256"] == (
        "fe0bf2e072f0bebb63fe10fe1dc387af664146c768a05e06a5a5eab36efc9654"
    )
    assert profile["command"].startswith("MAKEFLAGS=-j1 colcon build --base-paths src")
    assert profile["image_id"].startswith("sha256:a4dae62b38bc01a01d084be7b68db83ec804fef")
    assert profile["cpus"] == 1
    assert profile["memory_mib"] == profile["memory_swap_mib"] == 768
    assert profile["pids_limit"] == 128
    assert profile["network"] == "none"
    assert profile["minimum_host_free_kib"] == 900_000
    assert profile["timeout_seconds"] == 3600
    assert profile["run_count_limit"] == 1


@pytest.mark.parametrize("broken", [
    "docker_exit", "timed_out", "source_after_verified", "installed_status_sha256",
    "generated_idl_sha256", "generated_struct_sha256", "generated_type_support_sha256",
    "generated_type_support_library_sha256",
    "owned_container_remaining", "daemon_id_after", "launch_error",
])
def test_status_type_qualification_fails_closed(broken):
    candidate = {
        "build_started": True,
        "docker_exit": 0,
        "timed_out": False,
        "launch_error": None,
        "source_after_verified": True,
        "installed_status_sha256": build.PX4_STATUS_SHA256,
        "generated_idl_sha256": "a" * 64,
        "generated_struct_sha256": "b" * 64,
        "generated_type_support_sha256": "c" * 64,
        "generated_type_support_library_sha256": "d" * 64,
        "owned_container_remaining": "",
        "container_inspection_error": None,
        "daemon_id_before": "fixed-daemon",
        "daemon_id_after": "fixed-daemon",
    }
    assert build._qualifies(candidate)
    candidate[broken] = {
        "docker_exit": 1, "timed_out": True, "source_after_verified": False,
        "installed_status_sha256": "0" * 64,
        "generated_idl_sha256": None, "generated_struct_sha256": None,
        "generated_type_support_sha256": None,
        "generated_type_support_library_sha256": None,
        "owned_container_remaining": "unexpected", "daemon_id_after": "other",
        "launch_error": "unavailable",
    }[broken]
    assert not build._qualifies(candidate)


def test_preflight_refuses_low_memory_and_records_observation(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "RESULT", tmp_path)
    monkeypatch.setattr(build, "SOURCE", tmp_path)
    (tmp_path / "build-source-profile.json").write_bytes(b"profile")
    monkeypatch.setattr(build, "_hash", lambda _: build.SOURCE_PROFILE_SHA256)
    monkeypatch.setattr(build.psutil, "virtual_memory", lambda: SimpleNamespace(
        available=899_999 * 1024,
    ))
    monkeypatch.setattr(build.psutil, "process_iter", lambda *args, **kwargs: [])
    monkeypatch.setattr(build, "_wsl_competitors", lambda: [])
    monkeypatch.setattr(build.subprocess, "run", lambda args, **kwargs: SimpleNamespace(
        stdout=(build.IMAGE_ID if args[:3] == ["docker", "image", "inspect"]
                else "fixed-daemon" if args[:2] == ["docker", "info"] else ""),
        returncode=0,
    ))
    with pytest.raises(RuntimeError, match="preflight refused"):
        build._preflight()
    observed = json.loads((tmp_path / "preflight.json").read_bytes())
    assert observed["free_kib"] == 899_999
    assert observed["running_containers"] == []


def test_existing_result_refuses_without_launch(tmp_path, monkeypatch):
    result = tmp_path / "result"
    result.mkdir()
    monkeypatch.setattr(build, "RESULT", result)
    with pytest.raises(FileExistsError):
        build.main()
    assert list(result.iterdir()) == []


def test_generated_artifact_read_failure_retains_failed_result(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "build-source-profile.json").write_text(json.dumps({
        "schema": build.STATUS_OVERLAY_SCHEMA,
        "build_started": False,
        "build_command": build.BUILD_COMMAND_V2,
    }), encoding="utf-8")
    (source / "src").mkdir()
    (source / "build-source-profile.sha256").write_text("fixed")
    (source / "parent-build-source-profile.json").write_text("{}")
    result = tmp_path / "result"
    monkeypatch.setattr(build, "SOURCE", source)
    monkeypatch.setattr(build, "RESULT", result)
    monkeypatch.setattr(build, "WORKSPACE", result / "workspace-v1")
    monkeypatch.setattr(build, "_hash", lambda path: build.SOURCE_PROFILE_SHA256)
    monkeypatch.setattr(build, "verify_workspace", lambda _: {
        "file_count": 260, "git_commit": build.PINNED_COMMIT, "verified": True,
    })
    monkeypatch.setattr(build, "_preflight", lambda: {"daemon_id": "fixed-daemon"})
    monkeypatch.setattr(build.subprocess, "Popen", lambda *args, **kwargs:
                        SimpleNamespace(wait=lambda timeout: 0))
    monkeypatch.setattr(build, "_docker_output", lambda *args:
                        "fixed-daemon" if args[0] == "info" else "")
    monkeypatch.setattr(build, "_artifact_hash", lambda _: (_ for _ in ()).throw(
        OSError("generated artifact unreadable")
    ))
    assert build.main() == 1
    recorded = json.loads((result / "result.json").read_bytes())
    assert recorded["status"] == "build_failed"
    assert "generated artifact unreadable" in recorded["postflight_error"]


def test_source_copy_refuses_preexisting_build_output(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "src").mkdir()
    (source / "build-source-profile.json").write_text(json.dumps({
        "schema": build.STATUS_OVERLAY_SCHEMA,
        "build_started": False,
        "build_command": build.BUILD_COMMAND_V2,
    }), encoding="utf-8")
    (source / "build-source-profile.sha256").write_text("fixed")
    (source / "parent-build-source-profile.json").write_text("{}")
    (source / "install").mkdir()
    (source / "install" / "fake-generated.txt").write_text("old")
    result = tmp_path / "result"
    monkeypatch.setattr(build, "SOURCE", source)
    monkeypatch.setattr(build, "RESULT", result)
    monkeypatch.setattr(build, "WORKSPACE", result / "workspace-v1")
    monkeypatch.setattr(build, "_hash", lambda path: build.SOURCE_PROFILE_SHA256)
    monkeypatch.setattr(build, "verify_workspace", lambda _: {
        "file_count": 260, "git_commit": build.PINNED_COMMIT, "verified": True,
    })
    monkeypatch.setattr(build, "_preflight", lambda: (_ for _ in ()).throw(
        AssertionError("preflight must not run")))
    with pytest.raises(RuntimeError, match="source.*layout|source.*output"):
        build.main()
    assert not (result / "launch.json").exists()


def test_preflight_refuses_wsl_competitor(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "RESULT", tmp_path)
    monkeypatch.setattr(build, "SOURCE", tmp_path)
    (tmp_path / "build-source-profile.json").write_bytes(b"profile")
    monkeypatch.setattr(build, "_hash", lambda _: build.SOURCE_PROFILE_SHA256)
    monkeypatch.setattr(build.psutil, "virtual_memory", lambda: SimpleNamespace(
        available=1_000_000 * 1024,
    ))
    monkeypatch.setattr(build.psutil, "process_iter", lambda *args, **kwargs: [])
    monkeypatch.setattr(build, "_wsl_competitors", lambda: [{
        "distro": "Ubuntu", "pid": 42, "name": "px4", "command": "px4 -d",
    }])
    monkeypatch.setattr(build.subprocess, "run", lambda args, **kwargs: SimpleNamespace(
        stdout=(build.IMAGE_ID if args[:3] == ["docker", "image", "inspect"]
                else "fixed-daemon" if args[:2] == ["docker", "info"] else ""),
        returncode=0,
    ))
    with pytest.raises(RuntimeError, match="preflight refused"):
        build._preflight()
    observed = json.loads((tmp_path / "preflight.json").read_bytes())
    assert observed["wsl_competing_processes"][0]["pid"] == 42


def test_gazebo_server_names_are_competitors():
    assert build._is_competitor("gz-sim-server", "/usr/bin/gz-sim-server")
    assert build._is_competitor("gz-sim-gui", "/usr/bin/gz-sim-gui")
    assert build._is_competitor("bash", "bash -lc gz sim -r test.sdf")
    assert build._is_competitor("gz.exe", "gz sim -r test.sdf")
    assert not build._is_competitor("dockerd", "/usr/bin/dockerd")


def test_wsl_gazebo_server_is_observed(monkeypatch):
    responses = iter([
        SimpleNamespace(stdout="Ubuntu\r\n".encode("utf-16-le")),
        SimpleNamespace(stdout=b"  42 gz-sim-server /usr/bin/gz-sim-server -r test.sdf\n"),
    ])
    monkeypatch.setattr(build.subprocess, "run", lambda *args, **kwargs: next(responses))
    assert build._wsl_competitors() == [{
        "distro": "Ubuntu", "pid": 42, "name": "gz-sim-server",
        "command": "/usr/bin/gz-sim-server -r test.sdf",
    }]


def test_preflight_refuses_inaccessible_host_process_field(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "RESULT", tmp_path)
    monkeypatch.setattr(build, "SOURCE", tmp_path)
    (tmp_path / "build-source-profile.json").write_bytes(b"profile")
    monkeypatch.setattr(build, "_hash", lambda _: build.SOURCE_PROFILE_SHA256)
    monkeypatch.setattr(build.psutil, "virtual_memory", lambda: SimpleNamespace(
        available=1_000_000 * 1024,
    ))
    monkeypatch.setattr(build.psutil, "process_iter", lambda *args, **kwargs: [
        SimpleNamespace(pid=98765, info={"name": "powershell.exe", "cmdline": None}),
    ])
    monkeypatch.setattr(build, "_wsl_competitors", lambda: [])
    monkeypatch.setattr(build.subprocess, "run", lambda args, **kwargs: SimpleNamespace(
        stdout=(build.IMAGE_ID if args[:3] == ["docker", "image", "inspect"]
                else "fixed-daemon" if args[:2] == ["docker", "info"] else ""),
        returncode=0,
    ))
    with pytest.raises(RuntimeError, match="preflight refused"):
        build._preflight()
    observed = json.loads((tmp_path / "preflight.json").read_bytes())
    assert observed["process_observation_errors"][0]["pid"] == 98765
