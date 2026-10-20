"""Fail-closed source facts for the isolated PX4 status firmware candidate."""

import json
from pathlib import Path

import pytest

from flydrones.connectome_training.px4_status_firmware import (
    audit_firmware_source_facts,
    collect_firmware_source_facts,
    parse_submodule_status,
)

ROOT = Path(__file__).resolve().parents[2]
PROFILE = json.loads((ROOT / "configs/px4/estimator-status-firmware-profile.json").read_text())
TOPIC = "src/modules/uxrce_dds_client/dds_topics.yaml"


def prepared_facts() -> dict:
    hashes = dict(PROFILE["source_sha256"])
    hashes[TOPIC] = PROFILE["candidate_yaml_sha256"]
    return {
        "root": PROFILE["isolated_root"],
        "root_canonical": True,
        "candidate_canonical": True,
        "result_path": PROFILE["build_result_path"],
        "result_parent_canonical": True,
        "result_path_exists": False,
        "commit": PROFILE["px4_commit"],
        "namespace": "",
        "stage": "candidate",
        "tracked_status": [" M " + TOPIC],
        "source_sha256": hashes,
        "candidate_sha256": PROFILE["candidate_yaml_sha256"],
        "submodules": {name: {"commit": commit, "state": "initialized"}
                       for name, commit in PROFILE["required_sitl_submodules"].items()},
    }


def test_exact_isolated_candidate_is_only_source_prepared() -> None:
    result = audit_firmware_source_facts(PROFILE, prepared_facts())
    assert result["source_prepared"] is True
    assert result["errors"] == []
    assert result["firmware_compiled_verified"] is False
    assert result["live_source_authenticated"] is False
    assert result["training_eligible"] is False


@pytest.mark.parametrize("change,expected", [
    ({"commit": "0" * 40}, "px4_commit_mismatch"),
    ({"tracked_status": [" M src/modules/sensors/vehicle_imu/VehicleIMU.cpp"]},
     "tracked_changes_unexpected"),
    ({"tracked_status": []}, "tracked_changes_unexpected"),
])
def test_commit_or_unrelated_worktree_change_refuses(change: dict, expected: str) -> None:
    facts = prepared_facts()
    facts.update(change)
    result = audit_firmware_source_facts(PROFILE, facts)
    assert result["source_prepared"] is False
    assert expected in result["errors"]


@pytest.mark.parametrize("change,expected", [
    ({"namespace": "uav_1"}, "dds_namespace_unexpected"),
    ({"candidate_sha256": "0" * 64}, "candidate_yaml_mismatch"),
    ({"root_canonical": False}, "source_path_alias"),
    ({"candidate_canonical": False}, "candidate_path_alias"),
    ({"result_path_exists": True}, "result_path_reused"),
    ({"result_path": "/tmp/other"}, "result_path_mismatch"),
    ({"result_parent_canonical": False}, "result_path_alias"),
])
def test_wrong_source_namespace_or_path_refuses(change: dict, expected: str) -> None:
    facts = prepared_facts()
    facts.update(change)
    result = audit_firmware_source_facts(PROFILE, facts)
    assert result["source_prepared"] is False
    assert expected in result["errors"]


def test_missing_required_submodule_refuses_without_relabeling_other_modules() -> None:
    facts = prepared_facts()
    name = "src/modules/uxrce_dds_client/Micro-XRCE-DDS-Client"
    facts["submodules"][name]["state"] = "missing"
    result = audit_firmware_source_facts(PROFILE, facts)
    assert result["source_prepared"] is False
    assert "submodule_unavailable:" + name in result["errors"]
    assert result["firmware_compiled_verified"] is False


def test_unexpected_source_hash_refuses_even_with_expected_status() -> None:
    facts = prepared_facts()
    facts["source_sha256"]["msg/EstimatorStatus.msg"] = "f" * 64
    result = audit_firmware_source_facts(PROFILE, facts)
    assert result["source_prepared"] is False
    assert "source_hash_mismatch:msg/EstimatorStatus.msg" in result["errors"]


def test_submodule_status_parser_distinguishes_missing_and_drift() -> None:
    raw = (
        " 711aef423edd1820347b866d1e4164832df35d04 "
        "src/modules/uxrce_dds_client/Micro-XRCE-DDS-Client (heads/main)\n"
        "-b6127f4ec20de867e215fb5f78ae88b80f371909 Tools/simulation/gz\n"
        "+33af200d25ec6f0925b49b1ba82bbf1294ea5f72 "
        "src/modules/mavlink/mavlink (heads/other)\n"
    )
    found = parse_submodule_status(raw)
    assert found["src/modules/uxrce_dds_client/Micro-XRCE-DDS-Client"]["state"] == "initialized"
    assert found["Tools/simulation/gz"]["state"] == "missing"
    assert found["src/modules/mavlink/mavlink"]["state"] == "modified"


def test_collector_records_real_files_and_missing_modules(tmp_path, monkeypatch) -> None:
    from flydrones.connectome_training import px4_status_firmware as module

    root = tmp_path / "px4"
    root.mkdir()
    for name in PROFILE["source_sha256"]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
    candidate = tmp_path / "candidate.yaml"
    candidate.write_bytes(b"fixed candidate")
    expected = {
        ("rev-parse", "HEAD"): PROFILE["px4_commit"] + "\n",
        ("status", "--porcelain=v1", "--untracked-files=no"): "",
        ("submodule", "status"): "-" + PROFILE["required_sitl_submodules"]["Tools/simulation/gz"]
        + " Tools/simulation/gz\n",
    }
    monkeypatch.setattr(module, "_run_git", lambda _root, *args: expected[args])
    facts = collect_firmware_source_facts(root, candidate, tmp_path / "new-result", stage="base")
    assert facts["root_canonical"] is True
    assert facts["candidate_canonical"] is True
    assert facts["result_path_exists"] is False
    assert facts["submodules"]["Tools/simulation/gz"]["state"] == "missing"
    assert facts["source_sha256"][TOPIC] != PROFILE["source_sha256"][TOPIC]


def test_cli_refuses_to_claim_preparation_for_missing_submodule(tmp_path, monkeypatch, capsys) -> None:
    from flydrones.connectome_training import px4_status_firmware as module

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(PROFILE))
    facts = prepared_facts()
    facts["submodules"]["Tools/simulation/gz"]["state"] = "missing"
    monkeypatch.setattr(module, "collect_firmware_source_facts", lambda *_args, **_kwargs: facts)
    exit_code = module.main([
        "--profile", str(profile_path), "--root", PROFILE["isolated_root"],
        "--candidate", str(tmp_path / "candidate"),
        "--result-path", str(tmp_path / "result"), "--stage", "candidate",
    ])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["facts"] == facts
    assert output["audit"]["source_prepared"] is False
