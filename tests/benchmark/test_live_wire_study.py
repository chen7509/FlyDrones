"""Prospective manifest checks with real files and explicitly synthetic assets.

Tiny fixture binaries are never executed and do not qualify installed resources.
"""

import builtins
import copy
import hashlib
import importlib.util
import socket
import subprocess
from pathlib import Path

import pytest

from tests.benchmark.live_wire_study_fixture import fixture, write
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot


def agent_fixture(tmp_path):
    """Pure v2 fixture: fake bytes never become an executable file-adapter input."""
    from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256

    manifest, docs, _ = fixture(tmp_path, staged_wire=True)
    manifest["schema"] = "live-wire-study-v2"
    manifest["study_id"] = "agent-development-v12"
    manifest["simulation_seed"] = 27602
    docs["execution"]["simulation_seed"] = 27602
    docs["wire_config"]["session_id"] = manifest["study_id"] + ".clock"
    wire_path = Path(manifest["files"]["wire_config"]["requested"])
    write(wire_path, docs["wire_config"])
    manifest["files"]["wire_config"] = file_record(wire_path)
    docs["execution"]["wire"] = dict(path=str(wire_path), resolved=str(wire_path.resolve()),
                                       bytes=manifest["files"]["wire_config"]["bytes"],
                                       sha256=manifest["files"]["wire_config"]["sha256"],
                                       configuration=copy.deepcopy(docs["wire_config"]))
    manifest["command"][manifest["command"].index("--simulation-seed") + 1] = "27602"
    config = tmp_path / "agent-runtime.json"
    bundle = tmp_path / "bundle.tar.gz"
    binary = tmp_path / "MicroXRCEAgent"
    library_dir = tmp_path / "agent-lib"
    library_dir.mkdir()
    libraries = [library_dir / name for name in sorted(LIBRARY_SHA256)]
    for path in [bundle, binary, *libraries]:
        path.write_bytes(b"synthetic fixture, never executed")
    write(config, dict(schema="capture-agent-runtime-v1", bundle=str(bundle), binary=str(binary),
                       lib_dir=str(library_dir), port=18888))
    selected = [str(config), str(bundle), str(binary), *(str(path) for path in libraries)]
    hashes = [BUNDLE_SHA256, AGENT_SHA256, *(LIBRARY_SHA256[path.name] for path in libraries)]
    docs["binding"]["inventory"]["runtime-root:agent"] = [str(binary)]
    docs["binding"]["inventory"]["runtime:agent-dependencies"] = [str(config), str(bundle),
                                                                       *(str(path) for path in libraries)]
    docs["binding"]["runtime_maps"]["owned_roles"]["agent"] = ["ready", "prestop"]
    docs["binding"]["baseline"] = snapshot(docs["binding"]["inventory"])
    docs["binding"]["baseline"]["files"] = [row for row in docs["binding"]["baseline"]["files"]
                                             if row["requested"] != str(wire_path)]
    docs["binding"]["baseline"]["files"].append(dict(role="policy", **manifest["files"]["wire_config"]))
    for row in docs["binding"]["baseline"]["files"]:
        if row["requested"] in [str(bundle), str(binary), *(str(path) for path in libraries)]:
            row["sha256"] = ({str(bundle): BUNDLE_SHA256, str(binary): AGENT_SHA256,
                              **{str(path): LIBRARY_SHA256[path.name] for path in libraries}})[row["requested"]]
    binding_path = Path(manifest["files"]["binding"]["requested"])
    write(binding_path, docs["binding"])
    manifest["files"]["binding"] = file_record(binding_path)
    manifest["files"]["agent_config"] = file_record(config)
    docs["execution"]["agent"] = dict(
        schema="capture-agent-runtime-record-v1", declaration=str(config),
        declaration_sha256=manifest["files"]["agent_config"]["sha256"],
        configuration=dict(schema="capture-agent-runtime-v1", bundle=str(bundle), binary=str(binary),
                           lib_dir=str(library_dir), port=18888),
        selected_paths=selected,
        files=[dict(path=path, resolved=next(row["resolved"] for row in docs["binding"]["baseline"]["files"]
                                             if row["requested"] == path),
                    bytes=next(row["bytes"] for row in docs["binding"]["baseline"]["files"]
                               if row["requested"] == path), sha256=sha,
                    device=next(row["identity"]["device"] for row in docs["binding"]["baseline"]["files"]
                                if row["requested"] == path),
                    inode=next(row["identity"]["inode"] for row in docs["binding"]["baseline"]["files"]
                               if row["requested"] == path))
               for path, sha in zip(selected[1:], hashes)],
        authority=False, typed_dds_provenance=False, fusion_qualified=False,
    )
    manifest["command"] += ["--agent-runtime-config", str(config)]
    return manifest, docs


def logger_fixture(tmp_path):
    """v3 pure fixture: logger bytes are real; synthetic Agent is never run."""
    from tools.benchmark.px4_logger_runtime import PROFILE_RELATIVE, profile_record

    manifest, docs = agent_fixture(tmp_path)
    root = Path(__file__).resolve().parents[2]
    logger = profile_record(root / PROFILE_RELATIVE)
    topics, declaration = map(Path, logger["source_paths"])
    manifest["schema"] = "live-wire-study-v3"
    manifest["study_id"] = "logger-development-v13"
    manifest["simulation_seed"] = 27603
    docs["execution"]["simulation_seed"] = 27603
    docs["execution"]["logger_diagnostic"] = logger
    docs["wire_config"]["session_id"] = manifest["study_id"] + ".clock"
    wire_path = Path(manifest["files"]["wire_config"]["requested"])
    write(wire_path, docs["wire_config"])
    manifest["files"]["wire_config"] = file_record(wire_path)
    docs["execution"]["wire"] = dict(path=str(wire_path), resolved=str(wire_path.resolve()),
                                       bytes=manifest["files"]["wire_config"]["bytes"],
                                       sha256=manifest["files"]["wire_config"]["sha256"],
                                       configuration=copy.deepcopy(docs["wire_config"]))
    for row in docs["binding"]["baseline"]["files"]:
        if row["requested"] == str(wire_path):
            row.update(manifest["files"]["wire_config"])
    docs["binding"]["inventory"]["runtime:logger-diagnostic"] = [str(topics), str(declaration)]
    for path in (topics, declaration):
        docs["binding"]["baseline"]["files"].append(dict(role="runtime:logger-diagnostic", **file_record(path)))
    for role, path in (("logger_topics", topics), ("logger_profile", declaration)):
        manifest["files"][role] = file_record(path)
    manifest["command"][manifest["command"].index("--simulation-seed") + 1] = "27603"
    manifest["command"] += ["--logger-diagnostic-profile", "source-diagnostic-v1"]
    return manifest, docs


def test_pure_logger_study_binds_changed_load_without_granting_authority(tmp_path, monkeypatch):
    manifest, docs = logger_fixture(tmp_path)

    def forbidden(*_a, **_k):
        raise AssertionError("pure v3 validation performed I/O")

    with monkeypatch.context() as m:
        m.setattr(Path, "open", forbidden)
        m.setattr(Path, "stat", forbidden)
        m.setattr(subprocess, "Popen", forbidden)
        m.setattr(socket, "socket", forbidden)
        result = api().validate_live_wire_study(manifest, **docs)
    assert result["document_validated"] is True
    assert result["live_qualified"] is False and result["fusion_qualified"] is False


@pytest.mark.parametrize("change", [
    "missing_topics", "wrong_topics_hash", "wrong_profile_hash", "missing_inventory",
    "logger_selected", "wrong_env", "wrong_seed", "missing_option", "duplicate_option",
])
def test_pure_logger_study_refuses_missing_or_misbound_diagnostic(tmp_path, change):
    manifest, docs = logger_fixture(tmp_path)
    if change == "missing_topics":
        del manifest["files"]["logger_topics"]
    elif change == "wrong_topics_hash":
        docs["execution"]["logger_diagnostic"]["topics_sha256"] = "0" * 64
    elif change == "wrong_profile_hash":
        docs["execution"]["logger_diagnostic"]["declaration_sha256"] = "0" * 64
    elif change == "missing_inventory":
        del docs["binding"]["inventory"]["runtime:logger-diagnostic"]
    elif change == "logger_selected":
        docs["execution"]["logger_diagnostic"]["runtime_topic_selection_verified"] = True
    elif change == "wrong_env":
        docs["execution"]["logger_diagnostic"]["px4_environment_override"] = {"PX4_PARAM_SDLOG_PROFILE": "131"}
    elif change == "wrong_seed":
        manifest["simulation_seed"] = 27602
    elif change == "missing_option":
        del manifest["command"][-2:]
    elif change == "duplicate_option":
        manifest["command"] += ["--logger-diagnostic-profile", "source-diagnostic-v1"]
    with pytest.raises(ValueError):
        api().validate_live_wire_study(manifest, **docs)


def test_v2_rejects_diagnostic_logger_addition(tmp_path):
    manifest, docs = agent_fixture(tmp_path)
    docs["execution"]["logger_diagnostic"] = {"unapproved": True}
    manifest["command"] += ["--logger-diagnostic-profile", "source-diagnostic-v1"]
    with pytest.raises(ValueError):
        api().validate_live_wire_study(manifest, **docs)


def test_v3_file_adapter_checks_current_canonical_profile(tmp_path):
    _, docs = logger_fixture(tmp_path)
    record = docs["execution"]["logger_diagnostic"]
    assert api()._canonical_logger_record(record) is None
    changed = copy.deepcopy(record)
    changed["topics_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="canonical logger"):
        api()._canonical_logger_record(changed)


def v3_file_fixture(tmp_path, monkeypatch):
    """Serialize v3 with synthetic Agent bytes whose test-only fixed hashes match."""
    from tools.benchmark import agent_capture_runtime

    manifest, docs = logger_fixture(tmp_path)
    config = docs["execution"]["agent"]["configuration"]
    binary, bundle, directory = Path(config["binary"]), Path(config["bundle"]), Path(config["lib_dir"])
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(agent_capture_runtime, "AGENT_SHA256", digest(binary))
    monkeypatch.setattr(agent_capture_runtime, "BUNDLE_SHA256", digest(bundle))
    monkeypatch.setattr(agent_capture_runtime, "LIBRARY_SHA256",
                        {name: digest(directory / name) for name in agent_capture_runtime.LIBRARY_SHA256})
    for row in docs["execution"]["agent"]["files"]:
        row["sha256"] = digest(Path(row["path"]))
    docs["binding"]["baseline"] = snapshot(docs["binding"]["inventory"])
    binding_path = Path(manifest["files"]["binding"]["requested"])
    execution_path = Path(manifest["files"]["execution"]["requested"])
    write(binding_path, docs["binding"])
    write(execution_path, docs["execution"])
    manifest["files"]["binding"] = file_record(binding_path)
    manifest["files"]["execution"] = file_record(execution_path)
    path = write(tmp_path / "v3-manifest.json", manifest)
    return path, manifest, docs


def test_v3_file_adapter_validates_exact_canonical_files(tmp_path, monkeypatch):
    from tools.benchmark.audit_live_wire_study import audit_live_wire_study

    path, manifest, _ = v3_file_fixture(tmp_path, monkeypatch)
    result = api().validate_live_wire_study_files(path)
    assert result["files_verified"] is True
    assert result["manifest"] == manifest
    assert result["live_qualified"] is False
    audit = audit_live_wire_study(path)
    assert audit["checks"]["documents"]["canonical_diagnostic_logger_source_verified"] is True
    assert audit["refusals"][0]["stage"] == "capture"
    assert any("vehicle_odometry ULog" in item for item in audit["unverified"])


def test_v3_file_adapter_refuses_self_consistent_logger_substitution(tmp_path, monkeypatch):
    from tools.benchmark.audit_live_wire_study import audit_live_wire_study

    path, manifest, docs = v3_file_fixture(tmp_path, monkeypatch)
    alternate = tmp_path / "alternate-logger"
    alternate.mkdir()
    old = list(map(Path, docs["execution"]["logger_diagnostic"]["source_paths"]))
    new = [alternate / item.name for item in old]
    for source, target in zip(old, new):
        target.write_bytes(source.read_bytes())
    docs["execution"]["logger_diagnostic"]["source_paths"] = list(map(str, new))
    docs["binding"]["inventory"]["runtime:logger-diagnostic"] = list(map(str, new))
    docs["binding"]["baseline"]["files"] = [row for row in docs["binding"]["baseline"]["files"]
                                                  if row["requested"] not in set(map(str, old))]
    for role, item in zip(("logger_topics", "logger_profile"), new):
        record = file_record(item)
        docs["binding"]["baseline"]["files"].append(dict(role="runtime:logger-diagnostic", **record))
        manifest["files"][role] = record
    for role, name in (("binding", "binding.json"), ("execution", "execution.json")):
        target = tmp_path / name
        write(target, docs[role])
        manifest["files"][role] = file_record(target)
    write(path, manifest)
    with pytest.raises(ValueError, match="canonical logger"):
        api().validate_live_wire_study_files(path)
    audit = audit_live_wire_study(path)
    assert audit["refusals"][0]["stage"] == "documents"
    assert "canonical logger" in audit["refusals"][0]["reason"]


def test_pure_agent_study_requires_exact_owned_selection(tmp_path):
    manifest, docs = agent_fixture(tmp_path)
    result = api().validate_live_wire_study(manifest, **docs)
    assert result["document_validated"] is True and result["live_qualified"] is False
    for change in ("missing_role", "wrong_library", "missing_config", "wrong_seed", "extra_command"):
        changed, payloads = copy.deepcopy(manifest), copy.deepcopy(docs)
        if change == "missing_role":
            del payloads["binding"]["runtime_maps"]["owned_roles"]["agent"]
        elif change == "wrong_library":
            payloads["execution"]["agent"]["files"][-1]["sha256"] = "0" * 64
        elif change == "missing_config":
            del changed["files"]["agent_config"]
        elif change == "wrong_seed":
            changed["simulation_seed"] = 27601
        else:
            changed["command"].append("--startup-preflight")
        with pytest.raises(ValueError):
            api().validate_live_wire_study(changed, **payloads)


def test_v1_rejects_agent_addition(tmp_path):
    manifest, docs, _ = fixture(tmp_path)
    docs["execution"]["agent"] = {"unapproved": True}
    with pytest.raises(ValueError):
        api().validate_live_wire_study(manifest, **docs)


def api():
    assert importlib.util.find_spec("tools.benchmark.live_wire_study") is not None, "study validator missing"
    from tools.benchmark import live_wire_study

    return live_wire_study


def test_pure_validates_without_reading_or_granting_live_authority(tmp_path, monkeypatch):
    module = api()
    manifest, documents, _ = fixture(tmp_path)

    def forbidden(*_a, **_k):
        raise AssertionError("pure validator performed I/O")

    with monkeypatch.context() as m:
        m.setattr(Path, "open", forbidden)
        m.setattr(Path, "stat", forbidden)
        m.setattr(subprocess, "Popen", forbidden)
        m.setattr(socket, "socket", forbidden)
        result = module.validate_live_wire_study(manifest, **documents)
    assert result["document_validated"] is True
    assert result["files_verified"] is False
    assert result["live_qualified"] is False and result["fusion_qualified"] is False
    result["manifest"]["command"].append("changed")
    assert manifest["command"][-1] != "changed"


def test_staged_startup_study_validates_files_without_granting_live_authority(tmp_path):
    manifest, _, path = fixture(tmp_path, staged_wire=True)
    result = api().validate_live_wire_study_files(path)
    assert result["files_verified"] is True
    assert result["manifest"] == manifest
    assert result["live_qualified"] is False and result["fusion_qualified"] is False
    assert all(not Path(p).exists() for p in manifest["outputs"].values())


@pytest.mark.parametrize("cap", [0, 60_000_000_001, True, 60.0])
def test_staged_startup_study_rejects_invalid_cap(tmp_path, cap):
    manifest, docs, _ = fixture(tmp_path, staged_wire=True)
    docs["wire_config"]["startup_max_wall_ns"] = cap
    docs["execution"]["wire"]["configuration"]["startup_max_wall_ns"] = cap
    with pytest.raises(ValueError, match="invalid startup wall cap"):
        api().validate_live_wire_study(manifest, **docs)


@pytest.mark.parametrize(
    "mutation",
    [
        "startup",
        "worker",
        "extra_command",
        "wrong_command_input",
        "missing_native",
        "missing_config",
        "missing_reference",
        "no_estimator",
        "wrong_load",
        "float_limit",
        "bool_seed",
        "heldout",
        "extra_authority",
        "grant",
        "clock_scope",
        "clock_origin",
        "clock_session",
        "loose_timeout",
        "remote_endpoint",
        "wrong_profile",
        "duplicate_output",
        "nested_output",
        "output_input_collision",
        "bad_hash",
        "missing_file_role",
        "missing_owned_native",
        "missing_baseline",
        "wrong_environment",
    ],
)
def test_refuses_incompatible_or_misbound_study(tmp_path, mutation):
    module = api()
    manifest, docs, _ = fixture(tmp_path)
    if mutation == "startup":
        manifest["command"].append("--startup-preflight")
    elif mutation == "worker":
        manifest["command"].append("--worker")
    elif mutation == "extra_command":
        manifest["command"] += ["--unknown", "ignored"]
    elif mutation == "wrong_command_input":
        manifest["command"][manifest["command"].index("--shadow-config") + 1] = "/wrong"
    elif mutation.startswith("missing_") and mutation in ("missing_native", "missing_config", "missing_reference"):
        field = {"missing_native": "shadow_binary", "missing_config": "shadow_config", "missing_reference": "reference_module"}[
            mutation
        ]
        docs["execution"]["inputs"][field] = None
    elif mutation == "no_estimator":
        docs["execution"]["estimator_run"] = False
    elif mutation == "wrong_load":
        docs["execution"]["imu_hz"] = 100
    elif mutation == "float_limit":
        manifest["limits"]["accepted_samples"] = 500.0
    elif mutation == "bool_seed":
        manifest["simulation_seed"] = True
    elif mutation == "heldout":
        manifest["role"] = "held-out"
    elif mutation == "extra_authority":
        manifest["network_authorized"] = True
    elif mutation == "grant":
        manifest["live_activation_authorized"] = True
    elif mutation == "clock_scope":
        manifest["clock_scope"] = "px4-request-echo"
    elif mutation == "clock_origin":
        docs["wire_config"]["remote_origin_ns"] = 123
    elif mutation == "clock_session":
        docs["wire_config"]["session_id"] = "other-session"
    elif mutation == "loose_timeout":
        manifest["limits"]["bootstrap_wall_ns"] *= 2
    elif mutation == "remote_endpoint":
        manifest["endpoint"]["peer_host"] = "192.168.1.2"
    elif mutation == "wrong_profile":
        docs["execution"]["profiles"]["motion_intent_profile"] = None
    elif mutation == "duplicate_output":
        manifest["outputs"]["audit"] = manifest["outputs"]["dispatch"]
    elif mutation == "nested_output":
        manifest["outputs"]["audit"] = str(Path(manifest["outputs"]["capture"]) / "audit.json")
    elif mutation == "output_input_collision":
        manifest["outputs"]["capture"] = str(tmp_path)
    elif mutation == "bad_hash":
        manifest["files"]["auditor"]["sha256"] = "bad"
    elif mutation == "missing_file_role":
        del manifest["files"]["auditor"]
    elif mutation == "missing_owned_native":
        del docs["binding"]["runtime_maps"]["owned_roles"]["openvins"]
    elif mutation == "missing_baseline":
        docs["binding"]["baseline"]["files"].pop()
    elif mutation == "wrong_environment":
        docs["execution"]["launch_environment"]["HOME"] = "different"
    with pytest.raises(ValueError):
        module.validate_live_wire_study(manifest, **docs)


def test_file_adapter_verifies_actual_bytes_and_has_no_runtime_effect(tmp_path, monkeypatch):
    module = api()
    manifest, _, path = fixture(tmp_path)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "gz" or name.startswith("gz."):
            raise AssertionError("runtime imported")
        return real_import(name, *args, **kwargs)

    def forbidden(*_a, **_k):
        raise AssertionError("runtime effect")

    with monkeypatch.context() as m:
        m.setattr(builtins, "__import__", guarded_import)
        m.setattr(subprocess, "Popen", forbidden)
        m.setattr(socket, "socket", forbidden)
        result = module.validate_live_wire_study_files(path)
    assert result["files_verified"] is True and result["live_qualified"] is False
    assert result["manifest"] == manifest
    assert all(not Path(p).exists() for p in manifest["outputs"].values())


@pytest.mark.parametrize("mutation", ["content", "missing", "native", "calibration", "duplicate_json", "existing_output"])
def test_file_adapter_refuses_drift_without_creating_output(tmp_path, mutation):
    module = api()
    manifest, docs, path = fixture(tmp_path)
    if mutation == "content":
        Path(manifest["files"]["wire_config"]["requested"]).write_text("{}")
    elif mutation == "missing":
        Path(manifest["files"]["auditor"]["requested"]).unlink()
    elif mutation == "native":
        Path(docs["execution"]["inputs"]["shadow_binary"]).write_text("drift")
    elif mutation == "calibration":
        (tmp_path / "kalibr_imu_chain.yaml").write_text("drift")
    elif mutation == "duplicate_json":
        path.write_text(path.read_text()[:-1] + ',"study_id":"other"}')
    elif mutation == "existing_output":
        Path(manifest["outputs"]["dispatch"]).write_text("old evidence")
    with pytest.raises((ValueError, FileNotFoundError)):
        module.validate_live_wire_study_files(path)
    assert not Path(manifest["outputs"]["capture"]).exists()
    if mutation == "existing_output":
        assert Path(manifest["outputs"]["dispatch"]).read_text() == "old evidence"


def test_output_created_during_final_dependency_read_is_refused(tmp_path, monkeypatch):
    module = api()
    manifest, _, path = fixture(tmp_path)
    real_snapshot = module.snapshot
    calls = 0

    def concurrent_output(inventory):
        nonlocal calls
        calls += 1
        result = real_snapshot(inventory)
        if calls == 2:
            Path(manifest["outputs"]["dispatch"]).write_text("other dispatch evidence")
        return result

    monkeypatch.setattr(module, "snapshot", concurrent_output)
    with pytest.raises(ValueError, match="output already exists"):
        module.validate_live_wire_study_files(path)
    assert Path(manifest["outputs"]["dispatch"]).read_text() == "other dispatch evidence"
    assert not Path(manifest["outputs"]["capture"]).exists()


def test_dependency_changed_during_final_read_is_refused(tmp_path, monkeypatch):
    module = api()
    _, docs, path = fixture(tmp_path)
    real_snapshot = module.snapshot
    calls = 0

    def concurrent_dependency(inventory):
        nonlocal calls
        calls += 1
        if calls == 2:
            Path(docs["execution"]["inputs"]["shadow_binary"]).write_text("changed concurrently")
        return real_snapshot(inventory)

    monkeypatch.setattr(module, "snapshot", concurrent_dependency)
    with pytest.raises(ValueError):
        module.validate_live_wire_study_files(path)


@pytest.mark.parametrize("omitted", ["kalibr_imu_chain.yaml", "kalibr_imucam_chain.yaml", "freeze.json"])
def test_self_consistent_inventory_missing_required_estimator_file_is_refused(tmp_path, omitted):
    module = api()
    manifest, docs, path = fixture(tmp_path)
    binding = docs["binding"]
    binding["inventory"]["config"].remove(str(tmp_path / omitted))
    binding["baseline"] = snapshot(binding["inventory"])
    binding_path = Path(manifest["files"]["binding"]["requested"])
    write(binding_path, binding)
    manifest["files"]["binding"] = file_record(binding_path)
    write(path, manifest)
    with pytest.raises(ValueError, match="complete frozen estimator configuration"):
        module.validate_live_wire_study_files(path)
