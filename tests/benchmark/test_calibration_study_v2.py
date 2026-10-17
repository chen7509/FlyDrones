"""V2 real producer/routing/join behavior with static protocol fixtures only."""

import importlib
import json
from pathlib import Path

import pytest


def api():
    return importlib.import_module("tools.benchmark.prepare_calibration_capture_v2")


def test_runtime_entries_never_promote_historical_leaf_candidates():
    m = api()
    catalog = {
        "inventory": {
            "runtime-root:physics": ["/physics.so"],
            "runtime-root:openvins": ["/old-vio"],
            "runtime-root:native-reference": ["/old-ref"],
            "runtime-root:python-old": ["/old-python.so"],
            "runtime:dependencies": ["/leaf.so", "/renderer.so"],
        }
    }
    entries, candidates = m.select_entries(catalog, ["/model.so"], ["/python", "/current.so"], ["/Agent"], "/resolver")
    assert candidates == ["/leaf.so", "/renderer.so"]
    assert set(p for rows in entries.values() for p in rows) == {
        "/physics.so",
        "/model.so",
        "/python",
        "/current.so",
        "/Agent",
        "/resolver",
        m.RENDERER,
    }
    assert "/leaf.so" not in [p for rows in entries.values() for p in rows]
    assert "/old-vio" not in [p for rows in entries.values() for p in rows]


def test_v2_path_is_literal_and_arbitrary_study_refuses_before_reads(tmp_path):
    m = importlib.import_module("tools.benchmark.calibration_capture_study_v2")
    arbitrary = tmp_path / "study.json"
    arbitrary.write_text("{}")
    with pytest.raises(ValueError, match="fixed"):
        m.verify_study_v2(arbitrary, "a" * 64)
    from tools.benchmark.calibration_capture_study import verify_study

    with pytest.raises(ValueError, match="fixed"):
        verify_study(arbitrary, "a" * 64)


@pytest.mark.parametrize("fault", ["extra", "bytes"])
def test_agent_cache_reused_without_extract_or_write(tmp_path, monkeypatch, fault):
    import hashlib

    from tools.benchmark import agent_capture_runtime as pins
    from tools.benchmark.declared_runtime_snapshot import file_record

    m = api()
    folder = tmp_path / "old"
    (folder / "bin").mkdir(parents=True)
    (folder / "lib").mkdir()
    binary = folder / "bin/MicroXRCEAgent"
    binary.write_bytes(b"fixture-agent")
    library = folder / "lib/fixture.so"
    library.write_bytes(b"fixture-library")
    bundle = tmp_path / "archive.tar.gz"
    bundle.write_bytes(b"not-opened-by-cache-reader")
    monkeypatch.setattr(pins, "AGENT_SHA256", hashlib.sha256(binary.read_bytes()).hexdigest())
    monkeypatch.setattr(pins, "LIBRARY_SHA256", {"fixture.so": hashlib.sha256(library.read_bytes()).hexdigest()})
    monkeypatch.setattr(pins, "BUNDLE_SHA256", hashlib.sha256(bundle.read_bytes()).hexdigest())
    config = {
        "schema": "capture-agent-runtime-v1",
        "binary": str(binary),
        "lib_dir": str(library.parent),
        "bundle": str(bundle),
        "port": 18888,
    }
    deployment = {
        "members": [
            {"member": "bin/MicroXRCEAgent", "deployed": file_record(binary)},
            {"member": "lib/fixture.so", "deployed": file_record(library)},
        ],
        "bundle": file_record(bundle),
    }
    before = {p: p.read_bytes() for p in [binary, library, bundle]}
    assert m.reuse_agent_cache(config, deployment)["executed"] is False
    assert before == {p: p.read_bytes() for p in before}
    if fault == "extra":
        (library.parent / "extra.so").write_bytes(b"unbound")
    else:
        library.write_bytes(b"different")
    with pytest.raises(ValueError, match="cache"):
        m.reuse_agent_cache(config, deployment)


def test_v2_preparation_binds_actual_bill_digest_and_baseline(tmp_path, monkeypatch):
    m = importlib.import_module("tools.benchmark.calibration_capture_study_v2")
    from tools.benchmark import calibration_capture_study as shared

    monkeypatch.setattr(shared, "audit_preparation_at", lambda *a: {"raw_graph_records_consistent": True}, raising=False)
    p = tmp_path / "bill.json"
    p.write_bytes(b"actual-bill-bytes")
    import hashlib

    called = []
    monkeypatch.setattr(
        m,
        "agent_runtime_record",
        lambda *a: {"configuration": {"binary": "/agent/bin/MicroXRCEAgent", "lib_dir": "/agent/lib"}, "selected_paths": []},
        raising=False,
    )
    bill = {"agent_paths": [], "agent_lib": "/agent/lib"}
    monkeypatch.setattr(
        m,
        "audit_entry_bill",
        lambda bill, baseline: called.append((bill, baseline)) or {"entry_trace_consistent": True},
        raising=False,
    )
    from tools.benchmark.declared_runtime_snapshot import file_record

    baseline = [dict(file_record(p), role="bill")]
    binding = {"baseline": {"files": baseline}}
    preparation = {
        "schema": "raw-static-sdk-preparation-v2",
        "query_clocks": [],
        "queries": [],
        "entry_bill_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    }
    assert m.audit_v2_preparation(binding, preparation, p, bill)["entry_trace_consistent"] is True
    assert called == [(bill, baseline)]
    binding["baseline"]["files"] = []
    with pytest.raises(ValueError, match="bill"):
        m.audit_v2_preparation(binding, preparation, p, {})
    binding["baseline"]["files"] = baseline
    preparation["entry_bill_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="bill"):
        m.audit_v2_preparation(binding, preparation, p, {})


def test_fixed_profile_registry_routes_v2_without_global_mutation(monkeypatch):
    from tools.benchmark import calibration_capture_study as shared

    m = importlib.import_module("tools.benchmark.calibration_capture_study_v2")
    before = shared.FOLDER
    seen = []
    monkeypatch.setattr(
        m, "verify_study_v2", lambda p, s, require_absent=True: seen.append((p, s, require_absent)) or {"v2": True}
    )
    assert shared.verify_study(m.FOLDER / "study.json", "frozen", require_absent=False) == {"v2": True}
    assert shared.FOLDER == before and seen == [(m.FOLDER / "study.json", "frozen", False)]


def test_agent_loader_context_must_match_bound_execution_selection(tmp_path, monkeypatch):
    m = importlib.import_module("tools.benchmark.calibration_capture_study_v2")
    import hashlib

    from tools.benchmark import calibration_capture_study as shared
    from tools.benchmark.declared_runtime_snapshot import file_record

    p = tmp_path / "bill.json"
    p.write_bytes(b"bill")
    monkeypatch.setattr(shared, "audit_preparation_at", lambda *a: {"raw_graph_records_consistent": True})
    monkeypatch.setattr(m, "audit_entry_bill", lambda *a: {"entry_trace_consistent": True})
    monkeypatch.setattr(
        m,
        "agent_runtime_record",
        lambda *a: {
            "configuration": {"binary": "/agent/bin/MicroXRCEAgent", "lib_dir": "/agent/lib"},
            "selected_paths": ["/agent/runtime.json", "/bundle.tar.gz", "/agent/bin/MicroXRCEAgent", "/agent/lib/selected.so"],
        },
        raising=False,
    )
    binding = {"baseline": {"files": [dict(file_record(p), role="bill")]}}
    prep = {
        "schema": "raw-static-sdk-preparation-v2",
        "query_clocks": [],
        "queries": [],
        "entry_bill_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    }
    bill = {"agent_paths": ["/agent/bin/MicroXRCEAgent", "/agent/lib/selected.so"], "agent_lib": "/agent/lib"}
    assert m.audit_v2_preparation(binding, prep, p, bill)["entry_trace_consistent"] is True
    bill["agent_lib"] = "/unbound/lib"
    with pytest.raises(ValueError, match="Agent"):
        m.audit_v2_preparation(binding, prep, p, bill)


def test_actual_prepare_v2_pipeline_reaches_real_binding_role_guard(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace

    from tools.benchmark import audit_live_wire_resources, bound_resource_graph
    from tools.benchmark import calibration_capture_contract as scene_api
    from tools.benchmark import calibration_capture_study_v2 as study
    from tools.benchmark import native_resource_client as sdk
    from tools.benchmark import runtime_resource_binding as binding_api

    m = api()
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

    def record(path):
        path = Path(path)
        data = path.read_bytes() if path.is_file() else b"fixture-unavailable-native-input"
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

    def bill(*args):
        target = args[-1]
        target.mkdir()
        (target / "entry-bill.json").write_text("{}")
        return {"files": [record(dependency)], "entries": [{"selected": [str(dependency)]}]}

    monkeypatch.setattr(m, "discover_entry_dependencies", bill)
    monkeypatch.setattr(m, "licenses", lambda *a: [])
    monkeypatch.setattr(binding_api, "validate_response", lambda *a: None)
    monkeypatch.setattr(bound_resource_graph, "build_graph", lambda *a: {"documents": []})
    monkeypatch.setattr(
        audit_live_wire_resources, "audit_resource_graph_records", lambda **k: {"raw_graph_records_consistent": True}
    )
    monkeypatch.setattr(study, "audit_v2_preparation", lambda *a: {"entry_trace_consistent": True})
    monkeypatch.setattr(m, "publish_study_v2", lambda: {"fixture_only": True, "qualification": False})
    # External SDK/scene/procfs/source inventories are explicit protocol stubs.
    # The real producer must pass the REAL binding validator role/membership gate.
    result = m.prepare_v2("fixture-scope")
    assert result == {"fixture_only": True, "qualification": False}
    binding = json.loads((out / "frozen/runtime-binding-v4.json").read_text())
    assert binding["inventory"]["graph:dependencies"] == [str(dependency)]
    assert json.loads((out / "sdk-inside-after.json").read_text())["elapsed_ns"] >= 0


def test_paired_clock_hash_failure_keeps_primary_sdk_error(tmp_path, monkeypatch):
    m = api()

    class BadRaw:
        def is_file(self):
            return True

        def read_bytes(self):
            raise OSError("fixture raw hash failure")

    monkeypatch.setattr(m, "Path", lambda *a: BadRaw())

    def fail():
        raise ValueError("primary-sdk")

    with pytest.raises(ValueError, match="primary-sdk"):
        m.timed(fail, tmp_path / "clock.json", {"raw_query_path": "fixture"})
    saved = json.loads((tmp_path / "clock.json").read_text())
    assert "primary-sdk" in saved["error"] and "raw_query_error" in saved


def test_sdk_clock_raw_join_refuses_changed_local_elapsed(tmp_path, monkeypatch):
    m = importlib.import_module("tools.benchmark.calibration_capture_study_v2")
    producer = api()
    folder = tmp_path / "frozen"
    queries = folder / "graph-queries"
    queries.mkdir(parents=True)
    raw = queries / "resource-query-0000.json"
    import time

    def native_query():
        start = time.monotonic()
        raw.write_text(
            json.dumps({"command": ["/resolver", "context"], "started_monotonic": start, "ended_monotonic": time.monotonic()})
        )

    clock = queries / "local-clock-0000.json"
    producer.timed(native_query, clock, {"argv": ["/resolver", "context"], "raw_query_path": str(raw)})
    monkeypatch.setattr(m, "FOLDER", folder)
    prep = {"query_clocks": [json.loads(clock.read_text())], "queries": [json.loads(raw.read_text())]}
    m.audit_query_clocks(prep)
    import copy

    invented = copy.deepcopy(prep)
    invented["query_clocks"][0].update(start_monotonic_ns=0, end_monotonic_ns=1, elapsed_ns=1)
    with pytest.raises(ValueError, match="clock"):
        m.audit_query_clocks(invented)
    prep["query_clocks"][0]["elapsed_ns"] += 1
    with pytest.raises(ValueError, match="clock"):
        m.audit_query_clocks(prep)


def test_package_query_failure_retains_partial_output_when_postpin_fails(tmp_path, monkeypatch):
    m = api()
    before = {"requested": "/usr/bin/dpkg-query", "sha256": "a" * 64}
    calls = []

    def record(path):
        calls.append(path)
        if len(calls) > 1:
            raise OSError("fixture postpin unreadable")
        return before

    monkeypatch.setattr(m, "file_record", record)
    monkeypatch.setattr(
        m,
        "_run_tool",
        lambda *a: {
            "exit": 2,
            "error": "fixture timeout primary",
            "stdout_hex": b"partial package output".hex(),
            "stderr_hex": "",
            "output_limit_exceeded": False,
            "reader_complete": True,
        },
    )
    with pytest.raises(ValueError, match="license query"):
        m.licenses([], tmp_path)
    row = json.loads((tmp_path / "package-owner-query.json").read_text())
    assert "timeout primary" in row["error"] and "postpin_error" in row
    assert bytes.fromhex(row["stdout_hex"]) == b"partial package output"


def test_package_query_writer_failure_retains_row_in_fallback(tmp_path, monkeypatch):
    m = api()
    before = {"requested": "/usr/bin/dpkg-query", "sha256": "a" * 64}
    monkeypatch.setattr(m, "file_record", lambda p: before)
    monkeypatch.setattr(
        m,
        "_run_tool",
        lambda *a: {
            "exit": 2,
            "error": "primary query timeout",
            "stdout_hex": b"partial output".hex(),
            "stderr_hex": "",
            "output_limit_exceeded": False,
            "reader_complete": True,
        },
    )
    real_write = m.write_manifest

    def write(path, row):
        if path.name == "package-owner-query.json":
            raise OSError("fixture first row writer failure")
        real_write(path, row)

    monkeypatch.setattr(m, "write_manifest", write)
    with pytest.raises(ValueError, match="license query"):
        m.licenses([], tmp_path)
    row = json.loads((tmp_path / "installed-license-query-failure.json").read_text())
    assert bytes.fromhex(row["stdout_hex"]) == b"partial output"
    assert "writer failure" in row["persistence_error"] and row["error"] == "primary query timeout"
