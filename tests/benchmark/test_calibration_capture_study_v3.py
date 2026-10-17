"""Production preparation/runtime joins with explicit external SDK protocols."""

import copy
import importlib
import json
from pathlib import Path

import pytest
from test_native_entry_context_v3 import fixture, produce


def joined(tmp_path, monkeypatch):
    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    bill = produce(m, p, c, e, tmp_path / "bill")
    study = importlib.import_module("tools.benchmark.calibration_capture_study_v3")
    from tools.benchmark import calibration_capture_study as shared
    from tools.benchmark.declared_runtime_snapshot import file_record

    folder = tmp_path / "frozen"
    folder.mkdir()
    sdk = folder / "sdk"
    sdk.mkdir()
    context = sdk / "python-context.json"
    context.write_text(json.dumps(c))
    # Real retained query files produced by discover(), located at its actual output.
    billpath = tmp_path / "bill/entry-bill.json"
    records = [dict(r, role="graph:dependencies") for r in bill["files"]]
    records += [
        dict(file_record(x), role=role)
        for role, x in [("runtime:python-extension-context", context), ("runtime:entry-context-bill", billpath)]
    ]
    records += [
        dict(file_record(x), role="runtime:entry-context-artifacts") for x in sorted((tmp_path / "bill").glob("query-*.json"))
    ]
    binding = {
        "schema": "capture-resource-binding-v4",
        "capture_profile": "target-bearing-raw-v1",
        "inventory": {
            "runtime:python-extension-context": [str(context)],
            "graph:dependencies": [r["requested"] for r in bill["files"]],
            "runtime:entry-context-artifacts": [str(p) for p in sorted((tmp_path / "bill").glob("query-*.json"))],
        },
        "baseline": {"files": records},
    }
    prep = dict(
        schema="raw-static-sdk-preparation-v3",
        entry_bill_sha256=study.digest(billpath),
        python_context_file_sha256=study.digest(context),
        python_context_sha256=m.context_digest(c),
        query_clocks=[],
        queries=[],
    )
    monkeypatch.setattr(study, "FOLDER", folder)
    monkeypatch.setattr(shared, "audit_preparation_at", lambda *a: {"raw_graph_records_consistent": True})
    monkeypatch.setattr(
        study,
        "agent_runtime_record",
        lambda *a: {"configuration": {"binary": "/agent/bin/MicroXRCEAgent", "lib_dir": bill["agent_lib"]}, "selected_paths": []},
    )
    return study, m, c, bill, billpath, binding, prep


def test_real_v3_auditor_binds_context_bill_and_zero_selection_self(tmp_path, monkeypatch):
    s, m, c, bill, path, binding, prep = joined(tmp_path, monkeypatch)
    assert s.audit_v3_preparation(binding, prep, path, bill)["entry_trace_consistent"]
    expected = copy.deepcopy(binding)
    target = c["modules"][0]["origin"]["requested"]
    binding["inventory"]["graph:dependencies"].remove(target)
    with pytest.raises(ValueError, match="dependenc|self|entry"):
        s.audit_v3_preparation(binding, prep, path, bill)
    binding = expected
    prep["python_context_file_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="context"):
        s.audit_v3_preparation(binding, prep, path, bill)


def test_v3_auditor_refuses_changed_actual_query_artifact(tmp_path, monkeypatch):
    s, m, c, bill, path, binding, prep = joined(tmp_path, monkeypatch)
    q = path.parent / "query-0001.json"
    q.write_text("{}")
    with pytest.raises(ValueError, match="query|artifact"):
        s.audit_v3_preparation(binding, prep, path, bill)


def test_v3_auditor_rejects_arbitrary_bill_role(tmp_path, monkeypatch):
    s, m, c, bill, path, binding, prep = joined(tmp_path, monkeypatch)
    for r in binding["baseline"]["files"]:
        if r["requested"] == str(path):
            r["role"] = "unrelated"
    with pytest.raises(ValueError, match="bill"):
        s.audit_v3_preparation(binding, prep, path, bill)


def test_v3_auditor_does_not_accept_different_bill_object_than_bound_bytes(tmp_path, monkeypatch):
    from tools.benchmark.declared_runtime_snapshot import file_record

    s, m, c, bill, path, binding, prep = joined(tmp_path, monkeypatch)
    path.write_text("{}")
    prep["entry_bill_sha256"] = s.digest(path)
    binding["baseline"]["files"] = [
        dict(file_record(path), role=r["role"]) if r["requested"] == str(path) else r for r in binding["baseline"]["files"]
    ]
    with pytest.raises(ValueError, match="bill"):
        s.audit_v3_preparation(binding, prep, path, bill)


def test_explicit_v3_registry_does_not_mutate_old_paths(monkeypatch):
    from tools.benchmark import calibration_capture_study as shared

    s = importlib.import_module("tools.benchmark.calibration_capture_study_v3")
    old = shared.FOLDER
    monkeypatch.setattr(s, "verify_study_v3", lambda p, h, require_absent=True: {"v3": True, "absent": require_absent})
    assert shared.verify_study(s.FOLDER / "study.json", "sha", require_absent=False) == {"v3": True, "absent": False}
    assert shared.FOLDER == old


@pytest.mark.parametrize("fault", ["missing", "origin", "abi", "map", "pid"])
def test_runtime_module_witness_refuses_without_forced_import(tmp_path, monkeypatch, fault):
    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    from tools.benchmark.owned_runtime_maps import _device_parts

    current = copy.deepcopy(c)
    current["pid"] = m.os.getpid()
    row = c["modules"][0]["origin"]
    major, minor = _device_parts(row["identity"]["device"])
    from tools.benchmark import owned_runtime_maps

    # Explicit external maps-reader protocol on Windows, not Linux parse evidence.
    monkeypatch.setattr(
        owned_runtime_maps,
        "parse_maps",
        lambda text: [dict(path=row["resolved"], device=f"{major:x}:{minor:x}", inode=row["identity"]["inode"])] if text else [],
    )
    raw = f"1000-2000 r-xp 0000 {major:x}:{minor:x} {row['identity']['inode']} {row['resolved']}\n"
    if fault == "missing":
        current["modules"] = []
    if fault == "origin":
        current["modules"][0]["spec_origin"] = str(p["unused.so"])
    if fault == "abi":
        current["dlopen_flags"] += 1
    if fault == "map":
        raw = ""
    if fault == "pid":
        current["pid"] += 1
    monkeypatch.setattr(m, "collect_python_context", lambda: current)
    with pytest.raises(ValueError):
        m.audit_python_runtime(c, raw, "postimports")


def test_shared_runtime_observe_records_python_context_and_latches(tmp_path, monkeypatch):
    from tools.benchmark import runtime_resource_binding as runtime

    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    binding = object.__new__(runtime.RuntimeBinding)
    binding.pre_recorded = True
    binding.errors = []
    binding.closed = False
    binding.required_self = ["postimports"]
    binding.completed_self = []
    binding.python_context = c
    binding.output = tmp_path
    binding.map_reader = lambda: ""
    monkeypatch.setattr(binding, "_observe", lambda phase, raw: {"ordinary_maps": True})
    monkeypatch.setattr(m, "collect_python_context", lambda: dict(c, pid=m.os.getpid(), modules=[]))
    with pytest.raises(ValueError):
        binding.observe("postimports")
    assert binding.errors and binding.completed_self == []
    saved = json.loads((tmp_path / "runtime-python-context-postimports.json").read_bytes())
    assert saved["error"] and saved["runtime_import_verified"] is False
    assert saved["observed_context"]["modules"] == []


def test_runtime_same_sdk_process_origin_and_mapping_is_phase_only(tmp_path, monkeypatch):
    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    from tools.benchmark.owned_runtime_maps import _device_parts

    current = copy.deepcopy(c)
    current["pid"] = m.os.getpid()
    row = c["modules"][0]["origin"]
    major, minor = _device_parts(row["identity"]["device"])
    from tools.benchmark import owned_runtime_maps

    monkeypatch.setattr(
        owned_runtime_maps,
        "parse_maps",
        lambda text: [dict(path=row["resolved"], device=f"{major:x}:{minor:x}", inode=row["identity"]["inode"])] if text else [],
    )
    raw = f"1000-2000 r-xp 0000 {major:x}:{minor:x} {row['identity']['inode']} {row['resolved']}\n"
    monkeypatch.setattr(m, "collect_python_context", lambda: current)
    proof = m.audit_python_runtime(c, raw, "postimports")
    assert proof["pid"] == m.os.getpid() and proof["module_origins_consistent"]
    assert proof["runtime_import_verified"] is False and proof["symbols_resolved"] is False
    assert proof["observed_context"] == current


def test_real_execution_contract_selects_bound_context_file(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tools.benchmark import calibration_capture_contract as scene_api
    from tools.benchmark import capture_contract as contract

    s, m, c, bill, path, binding, prep = joined(tmp_path, monkeypatch)
    bound = tmp_path / "binding.json"
    bound.write_text(json.dumps(binding))
    monkeypatch.setattr(contract, "wire_configuration_record", lambda p: {"configuration": {"schema": "capture-wire-startup-v2"}})
    monkeypatch.setattr(scene_api, "raw_graph", lambda a: {"fixture_external_scene": True})
    args = SimpleNamespace(
        reference_fault_profile=None,
        shadow_binary=None,
        shadow_config=None,
        reference_module=None,
        motion_profile="target-bearing-multiaxis-v1",
        physics_trace_profile="substep-calibration-v1",
        source_fanout_profile=None,
        execution_contract=tmp_path / "execution.json",
        runtime_binding=bound,
        wire_config=tmp_path / "wire.json",
        capture_profile="target-bearing-raw-v1",
    )
    args.reference_sha256 = None
    result = contract.execution_contract(args, {"PATH": "/usr/bin:/bin"})
    assert result["python_extension_context"] == m.declared_python_context(binding)
    context = Path(binding["inventory"]["runtime:python-extension-context"][0])
    context.write_text("{}")
    with pytest.raises(ValueError, match="context"):
        contract.execution_contract(args, {"PATH": "/usr/bin:/bin"})


def test_actual_prepare_v3_pipeline_keeps_empty_selection_self_and_context(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace

    from tools.benchmark import audit_live_wire_resources, bound_resource_graph
    from tools.benchmark import calibration_capture_contract as scene_api
    from tools.benchmark import calibration_capture_study_v3 as study
    from tools.benchmark import native_resource_client as sdk
    from tools.benchmark import runtime_resource_binding as binding_api

    m = importlib.import_module("tools.benchmark.prepare_calibration_capture_v3")
    root = tmp_path / "project"
    root.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    old = tmp_path / "old"
    old.mkdir()
    cg = tmp_path / "cgroup"
    cg.mkdir()
    for name, value in {
        "memory.max": "536870912",
        "memory.swap.max": "0",
        "cpu.max": "100000 100000",
        "pids.max": "64",
        "memory.events": "oom 0",
        "memory.peak": "123",
    }.items():
        (cg / name).write_text(value)
    source = root / "source"
    source.mkdir()
    (source / "world.sdf").write_bytes(b"fixture-world")
    resolver = root / "resolver"
    resolver.write_bytes(b"fixture-resolver")
    graph_source = root / "tools/benchmark/native/resource_resolver.cc"
    graph_source.parent.mkdir(parents=True)
    graph_source.write_bytes(b"fixture-native-source")
    material = root / "gazebo.material"
    material.write_bytes(b"fixture-material")
    configuration = {
        "schema": "capture-agent-runtime-v1",
        "binary": str(root / "bin/MicroXRCEAgent"),
        "lib_dir": str(root / "lib"),
        "bundle": str(root / "bundle"),
        "port": 18888,
    }
    (old / "agent-runtime.json").write_text(json.dumps(configuration))
    (old / "agent-deployment.json").write_text("{}")
    catalog = root / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "inventory": {"graph:resolver": [str(resolver)], "runtime:dependencies": []},
                "baseline": {
                    "files": [
                        {"role": "graph:resolver", "sha256": hashlib.sha256(resolver.read_bytes()).hexdigest()},
                        {"role": "graph:source", "sha256": hashlib.sha256(graph_source.read_bytes()).hexdigest()},
                    ]
                },
            }
        )
    )
    agent = root / "historical-agent.json"
    agent.write_text("{}")
    for key, value in {
        "ROOT": root,
        "FOLDER": out / "frozen",
        "V1_FOLDER": old,
        "SOURCE": source,
        "CATALOG": catalog,
        "AGENT": agent,
    }.items():
        monkeypatch.setattr(m, key, value)
    monkeypatch.setattr(m, "scope_before", lambda *a: cg)
    monkeypatch.setattr(m, "reuse_agent_cache", lambda *a: {"executed": False})
    monkeypatch.setattr(m, "arguments", lambda *a: SimpleNamespace())
    monkeypatch.setattr(
        m,
        "execution_contract",
        lambda *a: {
            "agent": {"configuration": configuration, "selected_paths": [configuration["binary"]]},
            "logger_diagnostic": {"source_paths": []},
        },
    )
    sha = hashlib.sha256(b"fixture-world").hexdigest()
    selected = {"path": str(source), "files": {"world.sdf": {"bytes": 13, "sha256": sha}}}
    monkeypatch.setattr(scene_api, "scene_record", lambda *a: selected)
    monkeypatch.setattr(
        scene_api, "copy_scene", lambda source, destination: (destination / "world.sdf").write_bytes(b"fixture-world")
    )

    class Client:
        def __init__(self, *a):
            self.output = a[-1]

        def query(self, *args):
            return {"classic_material": str(material)} if args == ("installation",) else {}

    monkeypatch.setattr(sdk, "QueryClient", Client)
    monkeypatch.setattr(m, "required_plugins", lambda *a: [])

    from tools.benchmark.declared_runtime_snapshot import file_record as real_record

    def record(path):
        path = Path(path)
        if path.is_file():
            return real_record(path)
        data = b"fixture-unavailable-native-input"
        return {
            "requested": str(path),
            "resolved": str(path.absolute()),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    monkeypatch.setattr(m, "file_record", record)

    def snapshot(inventory):
        return {
            "schema": "declared-files-v1",
            "files": [dict(record(p), role=role) for role, paths in inventory.items() for p in paths],
        }

    monkeypatch.setattr(m, "snapshot", snapshot)
    dependency = root / "lib-dependency.so"
    dependency.write_bytes(b"fixture-dependency")

    context = dict(
        schema="python-extension-context-v1",
        pid=123,
        interpreter=record("/usr/bin/python3"),
        implementation="cpython",
        version="fixture3.12.3",
        version_info=[3, 12, 3],
        soabi="cpython-312-x86_64-linux-gnu",
        ext_suffix=".cpython-312-x86_64-linux-gnu.so",
        dlopen_flags=2,
        modules=[],
    )
    monkeypatch.setattr(m, "collect_python_context", lambda: context)

    def bill(*args):
        target = args[-1]
        target.mkdir()
        (target / "entry-bill.json").write_text("{}")
        return {"files": [record(dependency)], "entries": [{"file": record(dependency), "selected": []}]}

    monkeypatch.setattr(m, "discover_entry_context", bill)
    monkeypatch.setattr(m, "licenses", lambda *a: [])
    monkeypatch.setattr(binding_api, "validate_response", lambda *a: None)
    monkeypatch.setattr(bound_resource_graph, "build_graph", lambda *a: {"documents": []})
    monkeypatch.setattr(
        audit_live_wire_resources, "audit_resource_graph_records", lambda **k: {"raw_graph_records_consistent": True}
    )
    monkeypatch.setattr(study, "audit_v3_preparation", lambda *a: {"entry_trace_consistent": True})
    monkeypatch.setattr(m, "publish_study_v3", lambda: {"fixture_only": True, "qualification": False})
    # External SDK/scene/procfs/source inventories are explicit protocol stubs.
    # The real producer must pass the REAL binding validator role/membership gate.
    result = m.prepare_v3("fixture-scope")
    assert result == {"fixture_only": True, "qualification": False}
    binding = json.loads((out / "frozen/runtime-binding-v4.json").read_text())
    assert binding["inventory"]["graph:dependencies"] == [str(dependency)]
    assert binding["inventory"]["runtime:python-extension-context"] == [str(out / "frozen/sdk/python-context.json")]
    assert binding["inventory"]["runtime:entry-context-bill"] == [str(out / "frozen/sdk/entry-dependencies/entry-bill.json")]
    prep = json.loads((out / "frozen/preparation.json").read_bytes())
    assert prep["schema"] == "raw-static-sdk-preparation-v3" and prep["python_context_sha256"] == m.context_digest(context)
    assert json.loads((out / "frozen/wire-config.json").read_bytes())["schema"] == "capture-wire-startup-v2"
    assert json.loads((out / "sdk-inside-after.json").read_text())["elapsed_ns"] >= 0


def test_legacy_contract_does_not_read_binding_for_new_raw_context(tmp_path):
    from tools.benchmark import capture_contract as contract
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    args = parse_capture_args(["--output", str(tmp_path / "capture")])
    bound = tmp_path / "binding.json"
    bound.write_text("not a binding document")
    args.runtime_binding = bound
    assert "python_extension_context" not in contract.execution_contract(args)
