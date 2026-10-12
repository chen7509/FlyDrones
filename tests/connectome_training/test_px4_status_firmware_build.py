"""Admission is fail closed and never grants live or training authority."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.connectome.run_px4_status_firmware_build import audit_build_admission

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
