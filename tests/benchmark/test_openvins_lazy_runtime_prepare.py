import hashlib
import json
from pathlib import Path

import pytest

from tools.benchmark.declared_runtime_snapshot import file_record, snapshot
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy

PASS = {
    "schema": "openvins-lazy-runtime-closure-audit-v1",
    "failures": [],
    "lazy_mapping_qualified": True,
    "runtime_closure_qualified": False,
    "estimator_health_qualified": False,
    "physical_execution_qualified": False,
    "fusion_eligible": False,
    "flight_ready": False,
    "scope": "one first-IMU lazy allocator mapping only",
}


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def frozen_record(path):
    return file_record(Path(path).resolve())


def source_package(tmp_path):
    source = tmp_path / "preflight"
    source.mkdir()
    runtime = tmp_path / "runtime.bin"
    shadow = tmp_path / "online_probe"
    config = tmp_path / "config.yaml"
    reference = tmp_path / "reference.so"
    for path in (runtime, shadow, config, reference):
        path.write_bytes(path.name.encode())
    policy = source / "trajectory-gauge-policy.json"
    write_json(policy, trajectory_gauge_policy())
    inventory = {"runtime:test": [str(runtime.resolve())],
                 "runtime:trajectory-gauge-policy": [str(policy.resolve())]}
    environment = {"HOME": "/home/test", "GZ_PARTITION": None, "SDF_PATH": ""}
    binding = {"schema": "capture-resource-binding-v3", "inventory": inventory,
               "baseline": snapshot(inventory), "environment": environment,
               "graph": {"environment": {}}, "generated": {}, "runtime_maps": {}}
    contract = {
        "schema": "capture-execution-v3", "wall_budget_s": 300, "supervisor_s": 300,
        "simulation_duration_ns": 25_000_000_000, "physics_step_ns": 1_000_000,
        "imu_hz": 250, "rgbd_hz": 10, "rgbd_size": [160, 120], "estimator_run": True,
        "profiles": {"motion_profile": "supported-ready-v1", "physics_trace_profile": "substep-ready-v1",
                     "reference_fault_profile": None, "source_fanout_profile": "ready-shadow-heartbeat-v1"},
        "inputs": {"shadow_binary": str(shadow.resolve()), "shadow_config": str(config.resolve()),
                   "reference_module": str(reference.resolve())},
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "launch_environment": environment,
        "trajectory_gauge_policy": {"path": str(policy.absolute()), "resolved": str(policy.resolve()),
                                    "bytes": policy.stat().st_size,
                                    "sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
                                    "schema": "trajectory-gauge-policy-v1"},
    }
    write_json(source / "runtime-binding-v3.json", binding)
    write_json(source / "execution-contract.json", contract)
    write_json(source / "study-manifest.json", {
        "schema": "supported-heartbeat-gauge-preflight-v1", "prepare_only": True,
        "execution_contract": contract, "runtime_binding": str((source / "runtime-binding-v3.json").resolve()),
        "trajectory_gauge_policy": str(policy.resolve()), "physical_run_completed": False,
        "runtime_mapping_coverage_verified": False,
        "vio_accuracy_qualified": False, "estimator_health_qualified": False,
        "runtime_closure_qualified": False, "fusion_eligible": False, "flight_ready": False,
    })
    write_json(source / "preflight-audit-prelaunch.json", {
        "schema": "supported-heartbeat-gauge-preflight-audit-v1", "failures": [],
        "preflight_qualified": True, "physical_run_completed": False,
        "vio_accuracy_qualified": False, "estimator_health_qualified": False,
        "runtime_closure_qualified": False, "fusion_eligible": False, "flight_ready": False,
    })
    return source


def lazy_package(tmp_path):
    root = tmp_path / "lazy"
    probe = root / "probe"
    probe.mkdir(parents=True)
    binary = tmp_path / "online_probe"
    config = tmp_path / "estimator_config.yaml"
    tbb = tmp_path / "libtbb.so.12.11"
    allocator = tmp_path / "libtbbmalloc.so.2.11"
    source = tmp_path / "allocator.cpp"
    license_file = tmp_path / "LICENSE.txt"
    package = tmp_path / "libtbbmalloc2.deb"
    for path in (binary, config, tbb, allocator, source, license_file):
        path.write_bytes(path.name.encode())
    package.write_bytes(b"package")
    files = {name: frozen_record(path) for name, path in {
        "binary": binary, "config": config, "tbb": tbb, "allocator": allocator,
        "allocator_source": source, "license": license_file,
    }.items()}
    mapping = {"path": str(allocator.resolve()), "device": "08:30", "inode": allocator.stat().st_ino}
    write_json(root / "provenance.json", {
        "schema": "openvins-lazy-runtime-provenance-v1", "files": files,
        "package_relation": {"source": "onetbb", "version": "2021.11.0-2ubuntu2",
                             "tbb_package": "libtbb12", "allocator_package": "libtbbmalloc2"},
        "upstream": {"commit": "8b829acc65569019edb896c5150d427f288e8aba", "license": "Apache-2.0"},
        "predicted_mapping": {"resolved": str(allocator.resolve()), "identity": files["allocator"]},
        "ordinary_elf_closure_contains_allocator": False, "lazy_mapping_qualified": False,
        "runtime_closure_qualified": False, "estimator_health_qualified": False,
        "physical_execution_qualified": False, "fusion_eligible": False, "flight_ready": False,
    })
    names = ("states.jsonl", "fast.jsonl", "native.log", "native-requests.jsonl",
             "native-acks.jsonl", "native-session.json", "maps-before.json", "maps-after.json")
    for name in names:
        (probe / name).write_text("", encoding="utf-8")
    write_json(probe / "probe-result.json", {
        "schema": "openvins-lazy-runtime-probe-v1", "probe_qualified": True,
        "lazy_mapping_qualified": True, "added": [mapping], "removed": [],
        "runtime_closure_qualified": False, "estimator_health_qualified": False,
        "physical_execution_qualified": False, "fusion_eligible": False, "flight_ready": False,
    })
    audit_path = tmp_path / "audit-v3.json"
    write_json(audit_path, PASS)
    return root, audit_path, package, allocator


def fake_auditor(_root):
    return dict(PASS)


def test_prepare_adds_exact_lazy_contract_and_never_launches(tmp_path, monkeypatch):
    from tools.benchmark import openvins_lazy_runtime_prepare as prepare

    source = source_package(tmp_path)
    lazy, audit_path, package, allocator = lazy_package(tmp_path)
    monkeypatch.setattr(prepare, "PACKAGE_ARCHIVE_SHA256", hashlib.sha256(package.read_bytes()).hexdigest())
    output = tmp_path / "prepared"
    manifest = prepare.prepare_study(
        output, source_study=source, lazy_study=lazy, lazy_audit=audit_path,
        package_archive=package, capture_script=Path("/study/capture.py"),
        python=Path("/usr/bin/python3"), resources=[], closure_auditor=fake_auditor,
        policy_validator=lambda doc: doc,
    )
    binding = json.loads((output / "runtime-binding-v3.json").read_text())
    contract = json.loads((output / "lazy-runtime-contract.json").read_text())
    assert manifest["schema"] == "openvins-lazy-runtime-prepare-v1"
    assert manifest["prepare_only"] is True
    assert contract["expected_mapping"]["path"] == str(allocator.resolve())
    assert contract["trigger"] == "first_acknowledged_imu"
    declared = {str(Path(path).resolve()) for paths in binding["inventory"].values() for path in paths}
    assert str(allocator.resolve()) in declared
    assert str((output / "lazy-runtime-contract.json").resolve()) in declared
    assert binding["baseline"]["files"] == snapshot(binding["inventory"])["files"]
    assert not (output / "capture-v1").exists()
    assert manifest["physical_execution_qualified"] is False
    assert manifest["runtime_closure_qualified"] is False


@pytest.mark.parametrize("failure", [
    "active", "existing", "audit", "stored-audit", "package", "source-claim", "lazy-overclaim",
])
def test_prepare_refuses_invalid_or_overclaimed_sources(tmp_path, monkeypatch, failure):
    from tools.benchmark import openvins_lazy_runtime_prepare as prepare

    source = source_package(tmp_path)
    lazy, audit_path, package, _ = lazy_package(tmp_path)
    monkeypatch.setattr(prepare, "PACKAGE_ARCHIVE_SHA256", hashlib.sha256(package.read_bytes()).hexdigest())
    resources = [{"pid": 1}] if failure == "active" else []
    output = tmp_path / "prepared"
    if failure == "existing":
        output.mkdir()
    elif failure == "stored-audit":
        row = json.loads(audit_path.read_text())
        row["scope"] = "changed"
        write_json(audit_path, row)
    elif failure == "package":
        package.write_bytes(b"changed")
    elif failure == "source-claim":
        path = source / "study-manifest.json"
        row = json.loads(path.read_text())
        row["fusion_eligible"] = True
        write_json(path, row)
    elif failure == "lazy-overclaim":
        path = lazy / "provenance.json"
        row = json.loads(path.read_text())
        row["runtime_closure_qualified"] = True
        write_json(path, row)
    def failed_auditor(_root):
        return {**PASS, "failures": ["bad"], "lazy_mapping_qualified": False}

    auditor = failed_auditor if failure == "audit" else fake_auditor
    with pytest.raises((ValueError, FileExistsError)):
        prepare.prepare_study(
            output, source_study=source, lazy_study=lazy, lazy_audit=audit_path,
            package_archive=package, capture_script=Path("/study/capture.py"),
            python=Path("/usr/bin/python3"), resources=resources, closure_auditor=auditor,
            policy_validator=lambda doc: doc,
        )


def test_lazy_source_rejects_missing_or_extra_probe_evidence(tmp_path, monkeypatch):
    from tools.benchmark import openvins_lazy_runtime_prepare as prepare

    lazy, audit_path, package, _ = lazy_package(tmp_path)
    monkeypatch.setattr(prepare, "PACKAGE_ARCHIVE_SHA256", hashlib.sha256(package.read_bytes()).hexdigest())
    (lazy / "probe" / "extra").write_text("x")
    with pytest.raises(ValueError, match="member"):
        prepare.validate_lazy_source(lazy, audit_path, package, closure_auditor=fake_auditor)
