"""Independent read-only audit of the Agent-inclusive offline study."""
# ruff: noqa: E402

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256
from tools.benchmark.execute_openvins_health_physical_run import prepare_live_wire_execution
from tools.benchmark.live_wire_study import validate_live_wire_study_files

HERE = Path(__file__).resolve().parent
STUDY = HERE / "study-v12-retry2"
OLD_ZIP = ROOT / "evidence/live-wire-v11-startup-preparation-dev-1701.zip"
OLD_ZIP_SHA = "ea31808ff8b835a851a84c12f6fd65329fac05170fe8ceef411a8167565e9b26"


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit():
    assert sha(OLD_ZIP) == OLD_ZIP_SHA
    source = HERE / "study-v11"
    with zipfile.ZipFile(OLD_ZIP) as archive:
        assert archive.testzip() is None
        for name in ("runtime-binding-v3.json", "execution-contract.json", "study-manifest.json",
                     "wire-config.json", "trajectory-gauge-policy.json"):
            member = (source / name).relative_to(ROOT).as_posix()
            assert archive.read(member) == (source / name).read_bytes()
    manifest = read(STUDY / "study-manifest.json")
    binding = read(STUDY / "runtime-binding-v3.json")
    execution = read(STUDY / "execution-contract.json")
    result = read(STUDY / "preparation-result.json")
    version = read(HERE / "committed-source-v12-retry2.json")
    assert manifest["schema"] == "live-wire-study-v2"
    assert manifest["study_id"] == "live-wire-agent-dev-1701-v12-retry2"
    assert manifest["producer_commit"] == result["producer_commit"] == version["head"]
    assert manifest["simulation_seed"] == execution["simulation_seed"] == 27602
    assert manifest["live_activation_authorized"] is False
    assert execution["simulation_duration_ns"] == 25_000_000_000
    assert execution["physics_step_ns"] == 1_000_000
    assert execution["imu_hz"] == 250 and execution["rgbd_hz"] == 10
    assert execution["rgbd_size"] == [160, 120]
    assert result["original_declared_files"] == 619
    assert result["prepared_declared_files"] == len(binding["baseline"]["files"]) == 640
    assert result["selected_agent_files"] == 16
    assert binding["runtime_maps"]["owned_roles"]["agent"] == ["ready", "prestop"]
    config = execution["agent"]["configuration"]
    assert config["port"] == 18888
    selected = execution["agent"]["selected_paths"]
    assert selected[0] == manifest["files"]["agent_config"]["requested"]
    assert selected[1] == config["bundle"] and selected[2] == config["binary"]
    assert selected[3:] == [str(Path(config["lib_dir"]) / name) for name in sorted(LIBRARY_SHA256)]
    assert binding["inventory"]["runtime-root:agent"] == [config["binary"]]
    assert set(binding["inventory"]["runtime:agent-selected"]) == set(selected) - {config["binary"]}
    by_path = {row["requested"]: row for row in binding["baseline"]["files"]}
    expected_sha = [BUNDLE_SHA256, AGENT_SHA256, *(LIBRARY_SHA256[name] for name in sorted(LIBRARY_SHA256))]
    assert [by_path[path]["sha256"] for path in selected[1:]] == expected_sha
    assert [entry["sha256"] for entry in execution["agent"]["files"]] == expected_sha
    assert execution["agent"]["typed_dds_provenance"] is False
    assert manifest["command"][-2:] == ["--agent-runtime-config", selected[0]]
    drift = read(STUDY / "source-drift.json")["changes"]
    assert len(drift) == 5 and all(row["accepted_committed_source"] is True for row in drift)
    for row in drift:
        rel = Path(row["path"]).relative_to(ROOT).as_posix()
        assert sha(ROOT / rel) == row["after"] == version["source_sha256"][rel]
    assert set(result["mutation_refusals"]) == {
        "seed", "startup_command", "auditor_hash", "clock_scope", "lazy_leaf_missing",
        "agent_missing_role", "agent_config_missing",
    }
    for key in ("installed_capture_run", "native_estimator_run", "physical_run", "network_enabled",
                "live_activation_available", "live_qualified", "fusion_eligible", "runtime_closure_qualified"):
        assert result[key] is False, key
    assert validate_live_wire_study_files(STUDY / "study-manifest.json")["files_verified"] is True
    assert prepare_live_wire_execution(STUDY / "study-manifest.json") == read(STUDY / "executor-binding.json")
    assert all(not Path(path).exists() for path in manifest["outputs"].values())
    for failed in (HERE / "study-v12", HERE / "study-v12-retry"):
        assert read(failed / "prepare-failed.json")["physical_run"] is False
    return dict(status="offline_agent_study_verified", files=640, agent_files=16,
                negative_cases=7, preserved_preparation_failures=2, physical_run=False,
                fusion_qualified=False)


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True))
