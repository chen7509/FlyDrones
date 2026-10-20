"""A successful launcher exit cannot by itself qualify a PX4 binary."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from tools.connectome import audit_px4_status_firmware_binary as audit_module
from tools.connectome.audit_px4_status_firmware_binary import audit_binary_facts
from tools.connectome.run_px4_status_firmware_build import (
    EXPECTED_TOOLCHAIN_FILES,
    EXPECTED_TOOLCHAIN_MODULES,
    build_scope_command,
)


def test_binary_auditor_requires_a_real_artifact_collector() -> None:
    assert importlib.util.find_spec("tools.connectome.audit_px4_status_firmware_binary") is not None


ROOT = Path(__file__).resolve().parents[2]
BUILD = json.loads((ROOT / "configs/px4/estimator-status-firmware-build-profile.json").read_text())
SOURCE = json.loads((ROOT / "configs/px4/estimator-status-firmware-profile.json").read_text())
HEX = "a" * 64
RUNNER = ROOT / "tools/connectome/run_px4_status_firmware_build.py"
PINNED = {"files": dict(EXPECTED_TOOLCHAIN_FILES),
          "modules": deepcopy(EXPECTED_TOOLCHAIN_MODULES)}


def qualified_fixture() -> dict:
    selected = dict(SOURCE["source_sha256"])
    selected["src/modules/uxrce_dds_client/dds_topics.yaml"] = SOURCE["candidate_yaml_sha256"]
    return {
        "preflight": {
            "profile": BUILD, "command": build_scope_command(),
            "two_phase": {"dispatch_permitted": True},
            "build_tree_audit": {"build_tree_verified": True},
            "build_tree_before": {"build_exists": False},
            "toolchain_audit": {"toolchain_verified": True},
            "toolchain_before": deepcopy(PINNED),
            "runner_sha256": hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
        },
        "dispatch": {
            "build_dispatched": True, "build_exit_code": 0, "launcher_pid": 1234,
            "owned_scope_released": True, "cleanup": {"graceful_scope_exit": True},
            "toolchain_unchanged": True,
            "toolchain_after": deepcopy(PINNED),
            "final_record_persisted": True, "timed_out": False, "errors": [],
        },
        "launch": {"command": build_scope_command(), "launcher_pid": 1234,
                   "unit": build_scope_command()[7].removeprefix("--unit=") + ".scope"},
        "source": {
            "root": BUILD["isolated_root"], "root_canonical": True,
            "result_path": BUILD["build_result_path"], "result_path_exists": True,
            "result_parent_canonical": True, "candidate_canonical": True,
            "stage": "candidate", "commit": SOURCE["px4_commit"],
            "tracked_status": [" M src/modules/uxrce_dds_client/dds_topics.yaml"],
            "namespace": "", "source_sha256": selected,
            "candidate_sha256": SOURCE["candidate_yaml_sha256"],
            "submodules": {name: {"commit": commit, "state": "initialized"}
                           for name, commit in SOURCE["required_sitl_submodules"].items()},
        },
        "header": {"sha256": HEX, "size": 54527},
        "binary": {"sha256": "b" * 64, "size": 57000000},
        "binary_elf_magic": "7f454c46", "readelf_notes": "Build ID: 1234567890abcdef",
        "binary_query": "bin/px4:\n  input: LINK\n    | src/modules/uxrce_dds_client/libmodules__uxrce_dds_client.a\n",
        "archive_query": "src/modules/uxrce_dds_client/libmodules__uxrce_dds_client.a:\n  input: ARCHIVE\n    src/modules/uxrce_dds_client/CMakeFiles/modules__uxrce_dds_client.dir/uxrce_dds_client.cpp.o\n",
        "object_deps": "src/modules/uxrce_dds_client/CMakeFiles/modules__uxrce_dds_client.dir/uxrce_dds_client.cpp.o: #deps 2, deps mtime 1 (VALID)\n    /x/src/modules/uxrce_dds_client/dds_topics.h\n",
        "archive_members": "uxrce_dds_client.cpp.o\n",
        "archive_member_sha256": HEX,
        "ninja_log_text": (
            "# ninja log v5\n"
            "1\t2\t3\tsrc/modules/uxrce_dds_client/CMakeFiles/modules__uxrce_dds_client.dir/uxrce_dds_client.cpp.o\tabc\n"
            "3\t4\t5\tsrc/modules/uxrce_dds_client/libmodules__uxrce_dds_client.a\tdef\n"
            "4\t5\t6\tbin/px4\t123\n"
        ),
        "runner_sha256": hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
        "pinned_toolchain": deepcopy(PINNED),
        "source_profile_sha256": BUILD["source_profile_sha256"],
        "build_profile_sha256": "12990af3daa437772aae3d6440a3f209ab6c4b0c1af4bad8a6e85a5adf9bee3a",
        **{name: {"sha256": HEX, "size": 1} for name in
           ("ninja", "archive", "object", "stdout", "stderr", "ninja_log")},
    }


def test_complete_synthetic_chain_is_only_compilation_qualification() -> None:
    result = audit_binary_facts(BUILD, SOURCE, qualified_fixture(), expected_header_sha256=HEX)
    assert result["errors"] == []
    assert result["firmware_compiled_verified"] is True
    assert result["live_source_authenticated"] is False
    assert result["training_eligible"] is False


@pytest.mark.parametrize("path,value,error", [
    (("dispatch", "build_exit_code"), 1, "build_execution_unqualified"),
    (("dispatch", "final_record_persisted"), False, "build_execution_unqualified"),
    (("dispatch", "cleanup"), {}, "build_execution_unqualified"),
    (("preflight", "build_tree_before"), {"build_exists": True}, "preflight_unqualified"),
    (("header", "sha256"), "0" * 64, "generated_header_mismatch"),
    (("binary_query",), "bin/px4:\n", "compiled_dependency_chain_unverified"),
    (("object_deps",), "missing header\n", "compiled_dependency_chain_unverified"),
    (("source", "commit"), "0" * 40, "post_source_unqualified"),
])
def test_missing_or_forged_link_in_chain_refuses(path: tuple[str, ...], value, error: str) -> None:
    facts = qualified_fixture()
    target = facts
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert error in result["errors"]


def test_source_or_toolchain_drift_refuses() -> None:
    facts = deepcopy(qualified_fixture())
    facts["source"]["source_sha256"]["msg/EstimatorStatus.msg"] = "0" * 64
    facts["dispatch"]["toolchain_after"] = {"files": {"/usr/bin/gcc": "0" * 64}}
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert {"post_source_drift", "build_execution_unqualified"}.issubset(result["errors"])


def test_stale_ninja_dependency_record_does_not_qualify_binary() -> None:
    facts = qualified_fixture()
    facts["object_deps"] = facts["object_deps"].replace("(VALID)", "(STALE)")
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert "compiled_dependency_chain_unverified" in result["errors"]


def test_unbound_or_changed_source_profile_does_not_qualify_binary() -> None:
    facts = qualified_fixture()
    facts["source_profile_sha256"] = "0" * 64
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert "source_profile_unbound" in result["errors"]


def test_unbound_build_profile_does_not_qualify_binary() -> None:
    facts = qualified_fixture()
    facts["build_profile_sha256"] = "0" * 64
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert "build_profile_unbound" in result["errors"]


def test_readonly_cli_help_has_no_training_runtime_dependency() -> None:
    script = ROOT / "tools/connectome/audit_px4_status_firmware_binary.py"
    result = subprocess.run([sys.executable, "-I", "-S", str(script), "--help"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("section,key", [
    ("preflight", "profile"),
    ("preflight", "two_phase"),
    ("preflight", "build_tree_audit"),
    ("dispatch", "cleanup"),
])
def test_malformed_nested_build_record_refuses_without_exception(section: str, key: str) -> None:
    facts = qualified_fixture()
    facts[section][key] = None
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False


def test_toolchain_audit_boolean_cannot_hide_identical_wrong_snapshots() -> None:
    facts = qualified_fixture()
    wrong = deepcopy(PINNED)
    wrong["files"]["/usr/bin/gcc"] = "0" * 64
    facts["preflight"]["toolchain_before"] = wrong
    facts["dispatch"]["toolchain_after"] = deepcopy(wrong)
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert "toolchain_identity_unverified" in result["errors"]


def test_archive_member_must_match_object_bytes() -> None:
    facts = qualified_fixture()
    facts["archive_member_sha256"] = "0" * 64
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert "compiled_dependency_chain_unverified" in result["errors"]


def test_all_link_outputs_must_appear_once_in_fresh_ninja_log() -> None:
    facts = qualified_fixture()
    facts["ninja_log_text"] = facts["ninja_log_text"].replace("4\t5\t6\tbin/px4\t123\n", "")
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert "compiled_dependency_chain_unverified" in result["errors"]


def test_malformed_object_identity_refuses_without_exception() -> None:
    facts = qualified_fixture()
    facts["object"] = None
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert "compiled_dependency_chain_unverified" in result["errors"]


def test_wsl_attempt_directory_must_exist_and_match_profile() -> None:
    facts = qualified_fixture()
    facts["source"]["result_path_exists"] = False
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False
    assert "post_source_unqualified" in result["errors"]


@pytest.mark.parametrize("section,key,value", [
    ("preflight", "command", ["make", "-j1", "px4_sitl_default"]),
    ("launch", "launcher_pid", 9999),
    ("launch", "unit", "other.scope"),
    ("preflight", "runner_sha256", "0" * 64),
])
def test_launcher_and_runner_identity_must_match(section: str, key: str, value) -> None:
    facts = qualified_fixture()
    facts[section][key] = value
    result = audit_binary_facts(BUILD, SOURCE, facts, expected_header_sha256=HEX)
    assert result["firmware_compiled_verified"] is False


def test_cli_malformed_profile_key_is_structured_refusal(monkeypatch, capsys) -> None:
    def missing_key(*_args):
        raise KeyError("build_result_path")

    monkeypatch.setattr(audit_module, "collect_binary_facts", missing_key)
    code = audit_module.main([
        "--root", BUILD["isolated_root"], "--evidence", str(ROOT),
        "--build-profile", str(ROOT / "configs/px4/estimator-status-firmware-build-profile.json"),
        "--source-profile", str(ROOT / "configs/px4/estimator-status-firmware-profile.json"),
    ])
    assert code == 1
    audit = json.loads(capsys.readouterr().out)["audit"]
    assert audit["firmware_compiled_verified"] is False
    assert audit["errors"][0].startswith("audit_or_collection_error:KeyError:")
