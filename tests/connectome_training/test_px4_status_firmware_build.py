"""Admission is fail closed and never grants live or training authority."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.connectome.run_px4_status_firmware_build import (
    BUILD_SCOPE_UNIT,
    audit_build_admission,
    audit_build_tree,
    audit_owned_scope_cleanup,
    audit_toolchain_snapshot,
    audit_two_phase_dispatch,
    build_scope_command,
    execute_once,
)


def test_build_tree_rejects_untracked_and_ignored_cache() -> None:
    assert audit_build_tree(" M src/modules/uxrce_dds_client/dds_topics.yaml\n", False, False)[
        "build_tree_verified"] is True
    assert audit_build_tree(" M src/modules/uxrce_dds_client/dds_topics.yaml\n?? surprise\n",
                            False, False)["build_tree_verified"] is False
    assert audit_build_tree(" M src/modules/uxrce_dds_client/dds_topics.yaml\n!! build/\n",
                            False, False)["build_tree_verified"] is False
    assert audit_build_tree(" M src/modules/uxrce_dds_client/dds_topics.yaml\n",
                            True, False)["build_tree_verified"] is False


def test_toolchain_snapshot_requires_every_pinned_file_and_module() -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    expected = {"files": dict(module.EXPECTED_TOOLCHAIN_FILES),
                "modules": deepcopy(module.EXPECTED_TOOLCHAIN_MODULES)}
    assert audit_toolchain_snapshot(expected)["toolchain_verified"] is True
    missing = deepcopy(expected)
    missing["files"].pop("/usr/bin/gcc")
    assert "toolchain_files_mismatch" in audit_toolchain_snapshot(missing)["errors"]
    drift = deepcopy(expected)
    drift["modules"]["em"]["sha256"] = "0" * 64
    assert "toolchain_modules_mismatch" in audit_toolchain_snapshot(drift)["errors"]

ROOT = Path(__file__).resolve().parents[2]
PROFILE = json.loads((ROOT / "configs/px4/estimator-status-firmware-build-profile.json").read_text())


def ready_facts() -> dict:
    return {
        "source_profile_sha256": PROFILE["source_profile_sha256"],
        "source_auditor_sha256": PROFILE["source_auditor_sha256"],
        "prepared_source_audit_sha256": PROFILE["prepared_source_audit_sha256"],
        "source_prepared": True,
        "result_path": PROFILE["build_result_path"],
        "result_path_exists": False,
        "command": PROFILE["command"],
        "windows_available_bytes": 5 * 1024**3,
        "wsl_available_bytes": 5 * 1024**3,
        "disk_free_bytes": 20 * 1024**3,
        "competitors": [],
        "process_scan_complete": True,
        "scope_observed_inside": True,
        "scope_memory_max_bytes": PROFILE["scope_memory_max_bytes"],
        "scope_cpu_max": PROFILE["scope_cpu_max"],
        "timeout_seconds": PROFILE["timeout_seconds"],
        "run_count": 0,
    }


def test_ready_facts_grant_admission_only() -> None:
    audit = audit_build_admission(PROFILE, ready_facts())
    assert audit["build_admitted"] is True
    assert audit["build_dispatched"] is False
    assert audit["firmware_compiled_verified"] is False
    assert audit["live_source_authenticated"] is False
    assert audit["training_eligible"] is False


@pytest.mark.parametrize("change,error", [
    ({"windows_available_bytes": 4 * 1024**3 - 1}, "windows_memory_low"),
    ({"wsl_available_bytes": 4 * 1024**3 - 1}, "wsl_memory_low"),
    ({"disk_free_bytes": 15 * 1024**3 - 1}, "disk_low"),
    ({"competitors": [{"pid": 123, "name": "pytest"}]}, "competitor_present"),
    ({"process_scan_complete": False}, "process_scan_incomplete"),
    ({"command": ["make", "px4_sitl", "gz_x500"]}, "build_command_mismatch"),
    ({"timeout_seconds": 7200}, "timeout_mismatch"),
    ({"scope_observed_inside": False}, "scope_unverified"),
    ({"scope_memory_max_bytes": 0}, "scope_memory_mismatch"),
    ({"scope_cpu_max": "max 100000"}, "scope_cpu_mismatch"),
    ({"result_path_exists": True}, "result_path_reused"),
    ({"result_path": "/tmp/other"}, "result_path_mismatch"),
    ({"run_count": 1}, "run_count_exhausted"),
    ({"source_prepared": False}, "source_not_prepared"),
    ({"prepared_source_audit_sha256": "0" * 64}, "source_audit_mismatch"),
    ({"source_auditor_sha256": "0" * 64}, "source_auditor_mismatch"),
])
def test_bad_admission_fact_refuses(change: dict, error: str) -> None:
    facts = ready_facts()
    facts.update(change)
    audit = audit_build_admission(PROFILE, facts)
    assert audit["build_admitted"] is False
    assert error in audit["errors"]
    assert audit["build_dispatched"] is False


def test_matching_tampered_profile_and_facts_cannot_replace_frozen_source() -> None:
    profile = dict(PROFILE)
    facts = ready_facts()
    profile["source_profile_sha256"] = "f" * 64
    facts["source_profile_sha256"] = "f" * 64
    audit = audit_build_admission(profile, facts)
    assert audit["build_admitted"] is False
    assert "profile_contract_mismatch" in audit["errors"]


def test_admission_cli_records_refusal_without_dispatch(tmp_path, monkeypatch, capsys) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(PROFILE))
    facts = ready_facts()
    facts["windows_available_bytes"] = 2 * 1024**3
    monkeypatch.setattr(module, "collect_admission_facts", lambda _profile: facts)
    exit_code = module.main(["--admission-only", "--profile", str(profile_path)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["facts"] == facts
    assert output["audit"]["errors"] == ["windows_memory_low"]
    assert output["audit"]["build_dispatched"] is False


def test_execute_cli_refuses_before_dispatch_when_resource_gate_closed(
    tmp_path, monkeypatch, capsys,
) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(PROFILE))
    facts = ready_facts()
    facts["windows_available_bytes"] = 2 * 1024**3
    monkeypatch.setattr(module, "collect_admission_facts", lambda _profile: facts)
    monkeypatch.setattr(module, "_dispatch_approved", lambda *_args: (_ for _ in ()).throw(
        AssertionError("dispatch must not be reached")
    ))
    exit_code = module.main(["--execute-once", "--profile", str(profile_path)])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert result["build_dispatched"] is False
    assert result["first_audit"]["errors"] == ["windows_memory_low"]


def test_process_scan_treats_opaque_system_process_differently_from_launcher(monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    def process(pid: int, name: str):
        return SimpleNamespace(pid=pid, info={"name": name, "cmdline": None})

    monkeypatch.setattr(module.os, "getpid", lambda: 999)
    monkeypatch.setattr(module.psutil, "process_iter", lambda _fields: [process(1, "svchost.exe")])
    monkeypatch.setattr(module, "_wsl", lambda *_args: SimpleNamespace(stdout="2 bash /bin/bash\n"))
    competitors, complete = module._process_facts()
    assert competitors == []
    assert complete is True

    monkeypatch.setattr(module.psutil, "process_iter", lambda _fields: [process(3, "python.exe")])
    _, complete = module._process_facts()
    assert complete is False

    monkeypatch.setattr(module.psutil, "process_iter", lambda _fields: [
        SimpleNamespace(pid=4, info={"name": "python.exe", "cmdline": []}),
    ])
    _, complete = module._process_facts()
    assert complete is False


@pytest.mark.parametrize("name,command", [
    ("make", "make -j1 px4_sitl_default"),
    ("systemd-run", "systemd-run --scope make -j1 px4_sitl_default"),
    ("bash", "bash -lc ninja px4_sitl_default"),
])
def test_existing_px4_build_is_competitor(name: str, command: str) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    assert module._is_competitor(name, command) is True


def clean_scope_facts() -> dict:
    return {
        "unit": BUILD_SCOPE_UNIT,
        "during": {
            "load_state": "loaded", "active_state": "active",
            "control_group": "/user.slice/user-1000.slice/app.slice/"
                             + BUILD_SCOPE_UNIT,
            "invocation_id": "a" * 32,
        },
        "cgroup_members_during": ["47531"],
        "cgroup_read_exit": 0,
        "post": {"load_state": "not-found", "active_state": "inactive",
                 "control_group": ""},
        "cgroup_exists_after": False,
        "cgroup_after_test_exit": 1,
        "launcher_alive_after": False,
    }


def test_released_owned_scope_is_narrow_cleanup_evidence() -> None:
    audit = audit_owned_scope_cleanup(clean_scope_facts())
    assert audit["owned_scope_released"] is True
    assert audit["graceful_scope_exit"] is True
    assert audit["all_descendants_proven_exited"] is False


def test_named_probe_unit_can_be_audited_without_claiming_build_cleanup() -> None:
    facts = clean_scope_facts()
    facts["unit"] = "flydrones-px4-status-lifecycle-v2.scope"
    facts["during"]["control_group"] = facts["during"]["control_group"].replace(
        BUILD_SCOPE_UNIT, "flydrones-px4-status-lifecycle-v2.scope"
    )
    audit = audit_owned_scope_cleanup(
        facts, expected_unit="flydrones-px4-status-lifecycle-v2.scope"
    )
    assert audit["owned_scope_released"] is True
    assert audit["all_descendants_proven_exited"] is False


def test_failed_unit_after_explicit_owned_stop_can_still_release_cgroup() -> None:
    facts = clean_scope_facts()
    facts["unit"] = "flydrones-px4-status-timeout-probe-v1.scope"
    facts["during"]["control_group"] = facts["during"]["control_group"].replace(
        BUILD_SCOPE_UNIT, "flydrones-px4-status-timeout-probe-v1.scope"
    )
    facts["post"] = {"load_state": "loaded", "active_state": "failed", "control_group": ""}
    facts["stop_exit"] = 0
    audit = audit_owned_scope_cleanup(
        facts, expected_unit="flydrones-px4-status-timeout-probe-v1.scope"
    )
    assert audit["owned_scope_released"] is True
    assert audit["graceful_scope_exit"] is False
    assert audit["all_descendants_proven_exited"] is False


def test_failed_unit_without_recorded_stop_is_ambiguous() -> None:
    facts = clean_scope_facts()
    facts["post"] = {"load_state": "loaded", "active_state": "failed", "control_group": ""}
    audit = audit_owned_scope_cleanup(facts)
    assert audit["owned_scope_released"] is False


def test_failed_unit_with_recorded_owned_kill_and_empty_cgroup_is_released() -> None:
    facts = clean_scope_facts()
    facts["post"] = {"load_state": "loaded", "active_state": "failed", "control_group": ""}
    facts["kill_exit"] = 0
    audit = audit_owned_scope_cleanup(facts)
    assert audit["owned_scope_released"] is True
    assert audit["graceful_scope_exit"] is False


def test_failed_stop_attempts_kill_on_exact_owned_unit(monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    called = []

    def fake_wsl(*args, **_kwargs):
        called.append(args)
        return SimpleNamespace(returncode=1 if "stop" in args else 0)

    monkeypatch.setattr(module, "_wsl", fake_wsl)
    monkeypatch.setattr(module, "_show_build_unit", lambda: clean_scope_facts()["during"])
    result = module._stop_owned_scope("a" * 32)
    assert result["stop_exit"] == 1
    assert result["kill_exit"] == 0
    assert called == [
        ("systemctl", "--user", "stop", module.BUILD_SCOPE_UNIT),
        ("systemctl", "--user", "kill", "--signal=SIGKILL", module.BUILD_SCOPE_UNIT),
    ]


def test_changed_invocation_is_never_stopped(monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    state = dict(clean_scope_facts()["during"], invocation_id="b" * 32)
    monkeypatch.setattr(module, "_show_build_unit", lambda: state)
    monkeypatch.setattr(module, "_wsl", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("foreign scope must not be stopped")
    ))
    result = module._stop_owned_scope("a" * 32)
    assert result["stop_exit"] is None
    assert "scope_invocation_changed" in result["errors"]


def test_unsampled_scope_is_never_stopped(monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    monkeypatch.setattr(module, "_show_build_unit", lambda: (_ for _ in ()).throw(
        AssertionError("no inspection needed without ownership evidence")
    ))
    assert module._stop_owned_scope(None)["errors"] == ["scope_invocation_not_bound"]


def test_final_record_io_failure_remains_visible_to_caller(tmp_path, monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    monkeypatch.setattr(module, "_write_exclusive", lambda *_args: (_ for _ in ()).throw(
        OSError("volume full")
    ))
    record = {"errors": [], "build_exit_code": 0, "owned_scope_released": True}
    module._persist_final_result(tmp_path / "dispatch-result.json", record)
    assert record["final_record_persisted"] is False
    assert "final_record_write_failed" in record["errors"][0]


def test_launcher_invocation_record_requires_exact_unit_and_single_id(tmp_path) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    path = tmp_path / "stderr.bin"
    line = ("Running as unit: " + module.BUILD_SCOPE_UNIT
            + "; invocation ID: " + "a" * 32 + "\n")
    path.write_text(line, encoding="ascii")
    assert module._recorded_launcher_invocation_id(path) == "a" * 32
    path.write_text(line + line, encoding="ascii")
    assert module._recorded_launcher_invocation_id(path) is None
    path.write_text(line.replace(module.BUILD_SCOPE_UNIT, "someone-else.scope"),
                    encoding="ascii")
    assert module._recorded_launcher_invocation_id(path) is None


def test_replaced_scope_after_stop_is_never_killed(monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    states = iter([clean_scope_facts()["during"],
                   dict(clean_scope_facts()["during"], invocation_id="b" * 32)])
    monkeypatch.setattr(module, "_show_build_unit", lambda: next(states))
    calls = []

    def fake_wsl(*args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(module, "_wsl", fake_wsl)
    result = module._stop_owned_scope("a" * 32)
    assert "scope_replaced_before_kill" in result["errors"]
    assert calls == [("systemctl", "--user", "stop", module.BUILD_SCOPE_UNIT)]


def test_scope_command_is_exactly_build_only_and_blocks_git_fetch() -> None:
    command = build_scope_command()
    assert command[:4] == ["wsl.exe", "--distribution", "Ubuntu", "--exec"]
    assert command[4:7] == ["/usr/bin/systemd-run", "--user", "--scope"]
    assert "--unit=" + BUILD_SCOPE_UNIT.removesuffix(".scope") in command
    assert "/usr/bin/make" in command
    assert "/usr/bin/timeout" in command
    assert "PATH=/usr/bin:/bin" in command
    assert "--property=MemoryMax=4G" in command
    assert "--property=CPUQuota=100%" in command
    assert "--working-directory=/home/yuchen7509/px4-status-worktrees/firmware-v1" in command
    assert command[-3:] == ["/usr/bin/make", "-j1", "px4_sitl_default"]
    assert command[command.index("/usr/bin/env") + 1] == "-i"
    assert "PX4_UXRCE_DDS_NS" not in " ".join(command)
    assert "GIT_CONFIG_VALUE_0=never" in command
    assert "CCACHE_DISABLE=1" in command
    assert command[-7:-3] == ["/usr/bin/timeout", "--signal=TERM", "--kill-after=10s", "5400s"]
    assert all("gz_x500" not in item and "px4_sitl " not in item for item in command)


def test_two_phase_dispatch_requires_both_fresh_admissions() -> None:
    first = ready_facts()
    second = ready_facts()
    first["source_observation"] = {"facts": {"commit": PROFILE["isolated_root"],
                                             "source_sha256": {"yaml": "abc"}}}
    second["source_observation"] = first["source_observation"]
    assert audit_two_phase_dispatch(PROFILE, first, second)["dispatch_permitted"] is True
    second["windows_available_bytes"] = 3 * 1024**3
    audit = audit_two_phase_dispatch(PROFILE, first, second)
    assert audit["dispatch_permitted"] is False
    assert "second_admission_refused" in audit["errors"]


def test_two_phase_dispatch_rejects_source_drift_even_if_individual_gates_pass() -> None:
    first = ready_facts()
    second = ready_facts()
    first["source_observation"] = {"facts": {"source_sha256": {"yaml": "abc"}}}
    second["source_observation"] = {"facts": {"source_sha256": {"yaml": "def"}}}
    audit = audit_two_phase_dispatch(PROFILE, first, second)
    assert audit["dispatch_permitted"] is False
    assert "source_changed_between_admissions" in audit["errors"]


def test_execute_once_never_calls_dispatch_after_first_refusal() -> None:
    first = ready_facts()
    first["windows_available_bytes"] = 2 * 1024**3
    calls = []

    def collect(_profile):
        calls.append("collect")
        return first

    def dispatch(*_args):
        calls.append("dispatch")
        raise AssertionError("must not dispatch")

    result = execute_once(PROFILE, collect=collect, dispatch=dispatch)
    assert calls == ["collect"]
    assert result["build_dispatched"] is False


def test_execute_once_rechecks_and_dispatches_only_on_two_matching_passes() -> None:
    first = ready_facts()
    first["source_observation"] = {"facts": {"source_sha256": {"yaml": "abc"}}}
    second = json.loads(json.dumps(first))
    samples = iter([first, second])
    calls = []

    def dispatch(_profile, before, after):
        calls.append((before, after))
        return {"build_dispatched": True, "firmware_compiled_verified": False}

    result = execute_once(PROFILE, collect=lambda _profile: next(samples), dispatch=dispatch)
    assert len(calls) == 1
    assert result["build_dispatched"] is True
    assert result["firmware_compiled_verified"] is False

    second["source_observation"]["facts"]["source_sha256"]["yaml"] = "changed"
    samples = iter([first, second])
    calls.clear()
    result = execute_once(PROFILE, collect=lambda _profile: next(samples), dispatch=dispatch)
    assert calls == []
    assert result["build_dispatched"] is False


def test_dispatch_refuses_reused_evidence_directory_before_touching_wsl(tmp_path, monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    monkeypatch.setattr(module, "BUILD_EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(module, "_wsl", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("WSL must not be contacted for reused evidence")
    ))
    with pytest.raises(FileExistsError):
        module._dispatch_approved(PROFILE, ready_facts(), ready_facts())


def test_dispatch_refuses_toolchain_drift_before_creating_evidence(tmp_path, monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    path = tmp_path / "fresh"
    monkeypatch.setattr(module, "BUILD_EVIDENCE_DIR", path)
    facts = ready_facts()
    facts["source_observation"] = {"facts": {"source": "same"}}
    monkeypatch.setattr(module, "_show_build_unit", lambda: {
        "load_state": "not-found", "active_state": "inactive", "control_group": "",
    })
    monkeypatch.setattr(module, "_wsl", lambda *_args, **_kwargs: SimpleNamespace(returncode=1))
    monkeypatch.setattr(module, "_toolchain_snapshot", lambda: {"files": {}, "modules": {}})
    with pytest.raises(RuntimeError, match="toolchain"):
        module._dispatch_approved(PROFILE, facts, deepcopy(facts))
    assert not path.exists()


def test_synthetic_scope_lifecycle_preserves_logs_and_never_qualifies_binary(
    tmp_path, monkeypatch,
) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    first = ready_facts()
    first["source_observation"] = {"facts": {"source_sha256": {"yaml": "same"}}}
    second = json.loads(json.dumps(first))
    states = iter([
        {"load_state": "not-found", "active_state": "inactive", "control_group": ""},
        clean_scope_facts()["during"],
        clean_scope_facts()["post"],
        clean_scope_facts()["post"],
    ])
    monkeypatch.setattr(module, "BUILD_EVIDENCE_DIR", tmp_path / "fresh")
    monkeypatch.setattr(module, "_toolchain_snapshot", lambda: {
        "files": dict(module.EXPECTED_TOOLCHAIN_FILES),
        "modules": deepcopy(module.EXPECTED_TOOLCHAIN_MODULES),
    })
    monkeypatch.setattr(module, "_build_tree_snapshot", lambda: {
        "status": " M src/modules/uxrce_dds_client/dds_topics.yaml\n",
        "build_exists": False, "build_symlink": False,
    })
    monkeypatch.setattr(module, "_show_build_unit", lambda: next(states))
    monkeypatch.setattr(module, "_read_cgroup", lambda _group: {
        "path": "/sys/fs/cgroup/user.slice/" + BUILD_SCOPE_UNIT,
        "members": ["47531"], "memory_max": 4 * 1024**3,
        "cpu_max": "100000 100000", "memory_peak_bytes": 1024,
    })
    monkeypatch.setattr(module, "_wsl", lambda *args, **_kwargs: SimpleNamespace(
        returncode=1 if args[:2] in {("test", "-e"), ("test", "-L")} else 0,
        stdout="",
    ))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    class FakeProcess:
        pid = 9876
        returncode = None
        polls = 0

        def poll(self):
            self.polls += 1
            if self.polls == 1:
                return None
            self.returncode = 0
            return 0

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    result = module._dispatch_approved(PROFILE, first, second)
    assert result["build_dispatched"] is True
    assert result["build_exit_code"] == 0
    assert result["owned_scope_released"] is True
    assert result.get("firmware_compiled_verified", False) is False
    assert (tmp_path / "fresh" / "preflight.json").is_file()
    assert (tmp_path / "fresh" / "dispatch-result.json").is_file()


def test_synthetic_wall_timeout_stops_only_named_scope(tmp_path, monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    first = ready_facts()
    first["source_observation"] = {"facts": {"yaml": "same"}}
    second = json.loads(json.dumps(first))
    states = iter([
        {"load_state": "not-found", "active_state": "inactive", "control_group": ""},
        clean_scope_facts()["during"],
        clean_scope_facts()["during"],
        clean_scope_facts()["during"],
        clean_scope_facts()["during"],
        {"load_state": "loaded", "active_state": "failed", "control_group": ""},
    ])
    monkeypatch.setattr(module, "BUILD_EVIDENCE_DIR", tmp_path / "fresh")
    monkeypatch.setattr(module, "_toolchain_snapshot", lambda: {
        "files": dict(module.EXPECTED_TOOLCHAIN_FILES),
        "modules": deepcopy(module.EXPECTED_TOOLCHAIN_MODULES),
    })
    monkeypatch.setattr(module, "_build_tree_snapshot", lambda: {
        "status": " M src/modules/uxrce_dds_client/dds_topics.yaml\n",
        "build_exists": False, "build_symlink": False,
    })
    monkeypatch.setattr(module, "_show_build_unit", lambda: next(states))
    monkeypatch.setattr(module, "_read_cgroup", lambda _group: {
        "path": "/sys/fs/cgroup/user.slice/" + BUILD_SCOPE_UNIT,
        "members": ["47531"], "memory_max": 4 * 1024**3,
        "cpu_max": "100000 100000", "memory_peak_bytes": 1024,
    })
    commands = []

    def fake_wsl(*args, **_kwargs):
        commands.append(args)
        return SimpleNamespace(
            returncode=1 if args[:2] in {("test", "-e"), ("test", "-L")} else 0,
            stdout="",
        )

    monkeypatch.setattr(module, "_wsl", fake_wsl)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    times = iter([0, 1, 5401, 5402])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))

    class FakeProcess:
        pid = 9876
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            self.returncode = 9
            return 9

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    result = module._dispatch_approved(PROFILE, first, second)
    assert result["timed_out"] is True
    assert "wall_timeout" in result["errors"]
    assert result["owned_scope_released"] is True
    assert result.get("firmware_compiled_verified", False) is False
    assert ("systemctl", "--user", "stop", module.BUILD_SCOPE_UNIT) in commands


def test_exited_launcher_with_live_scope_still_stops_owned_scope(tmp_path, monkeypatch) -> None:
    from tools.connectome import run_px4_status_firmware_build as module

    facts = ready_facts()
    facts["source_observation"] = {"facts": {"yaml": "same"}}
    states = iter([
        {"load_state": "not-found", "active_state": "inactive", "control_group": ""},
        clean_scope_facts()["during"],  # final check despite launcher already exiting
        clean_scope_facts()["during"],  # identity check immediately before stop
        clean_scope_facts()["during"],  # after stop; still active until KILL
        {"load_state": "loaded", "active_state": "failed", "control_group": ""},
    ])
    monkeypatch.setattr(module, "BUILD_EVIDENCE_DIR", tmp_path / "fresh")
    monkeypatch.setattr(module, "_show_build_unit", lambda: next(states))
    monkeypatch.setattr(module, "_recorded_launcher_invocation_id", lambda _path: "a" * 32)
    monkeypatch.setattr(module, "_toolchain_snapshot", lambda: {
        "files": dict(module.EXPECTED_TOOLCHAIN_FILES),
        "modules": deepcopy(module.EXPECTED_TOOLCHAIN_MODULES),
    })
    monkeypatch.setattr(module, "_build_tree_snapshot", lambda: {
        "status": " M src/modules/uxrce_dds_client/dds_topics.yaml\n",
        "build_exists": False, "build_symlink": False,
    })
    commands = []

    def fake_wsl(*args, **_kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=1 if args[:2] in {("test", "-e"), ("test", "-L")}
                               else 0, stdout="")

    monkeypatch.setattr(module, "_wsl", fake_wsl)

    class ExitedLauncher:
        pid = 9876
        returncode = 1

        def poll(self):
            return 1

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: ExitedLauncher())
    result = module._dispatch_approved(PROFILE, facts, deepcopy(facts))
    assert ("systemctl", "--user", "stop", module.BUILD_SCOPE_UNIT) in commands
    assert result["build_dispatched"] is True
    assert result["build_exit_code"] == 1
    assert "scope_still_active_after_launcher_or_abort" in result["errors"]
    assert result.get("firmware_compiled_verified") is not True


@pytest.mark.parametrize("exit_code,expected_error,timed_out", [
    (0, None, False),
    (1, "build_exit_nonzero:1", False),
    (124, "build_exit_124_possible_timeout", False),
    (137, "build_exit_137_possible_sigkill", False),
])
def test_inner_timeout_exit_cannot_be_called_success(
    exit_code: int, expected_error: str | None, timed_out: bool,
) -> None:
    from tools.connectome.run_px4_status_firmware_build import classify_build_exit

    error, observed_timeout = classify_build_exit(exit_code)
    assert error == expected_error
    assert observed_timeout is timed_out


@pytest.mark.parametrize("change,error", [
    ({"unit": "someone-else.scope"}, "unit_mismatch"),
    ({"cgroup_members_during": []}, "during_members_missing"),
    ({"cgroup_read_exit": 1}, "during_members_missing"),
    ({"cgroup_exists_after": True}, "cgroup_still_exists"),
    ({"cgroup_after_test_exit": 2}, "cgroup_post_unknown"),
    ({"launcher_alive_after": True}, "launcher_still_alive"),
    ({"post": {"load_state": "loaded", "active_state": "active",
               "control_group": "/user.slice/other"}}, "unit_post_active_or_unknown"),
])
def test_ambiguous_or_wrong_owned_cleanup_refuses(change: dict, error: str) -> None:
    facts = clean_scope_facts()
    facts.update(change)
    audit = audit_owned_scope_cleanup(facts)
    assert audit["owned_scope_released"] is False
    assert error in audit["errors"]
