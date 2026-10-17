"""Inert v4 preparation/study/runtime integration, never a target dispatcher."""

import builtins
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("prepare_calibration_capture_v4", "calibration_capture_study_v4")


@pytest.mark.parametrize("name", MODULES)
@pytest.mark.parametrize("main", [False, True])
def test_inert_module_body_before_any_import_or_io(name, main, monkeypatch):
    source = (ROOT / "tools/benchmark" / f"{name}.py").read_text()
    calls = []
    original = builtins.__import__

    def trap(module, *args, **kwargs):
        if module == "sys":
            return sys
        calls.append(module)
        raise AssertionError("nonprimitive import " + module)

    def no_io(*args, **kwargs):
        raise AssertionError("unexpected IO")

    namespace = dict(__name__="__main__" if main else "fixture", __file__=str(ROOT / "tools/benchmark" / f"{name}.py"))
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", no_io)
        patch.setattr(builtins, "__import__", trap)
        if main:
            with pytest.raises(SystemExit):
                exec(compile(source, namespace["__file__"], "exec"), namespace)
        else:
            exec(compile(source, namespace["__file__"], "exec"), namespace)
    assert not calls and original is builtins.__import__


@pytest.mark.parametrize(
    "name,function", [("prepare_calibration_capture_v4", "prepare_v4"), ("calibration_capture_study_v4", "publish_study_v4")]
)
@pytest.mark.parametrize("ticket", [None, {}, {"schema": "static-sdk-ticket-reference-v4", "nonce": "a" * 64}])
def test_invalid_ticket_refuses_before_deferred_effects(name, function, ticket, monkeypatch):
    module = importlib.import_module("tools.benchmark." + name)

    def trap(*args, **kwargs):
        raise AssertionError("deferred effect before admission")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", trap)
        patch.setattr(builtins, "__import__", trap)
        with pytest.raises(ValueError):
            getattr(module, function)(ticket)


def test_runtime_v4_api_is_real_and_guard_installed():
    import subprocess

    from tools.benchmark import calibration_capture_study_v4 as study

    assert subprocess.Popen._execute_child.__name__ == "denied"
    assert callable(study.audit_v4_preparation) and callable(study.verify_study_v4)


@pytest.fixture
def entry_fixture(tmp_path, monkeypatch):
    # Reuse only the explicit inert fixture, not the prior suite or any v3 code.
    import importlib.util

    spec = importlib.util.spec_from_file_location("inert_entry_fixture", ROOT / "tests/benchmark/test_native_entry_context_v4.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = module.setup.__wrapped__(tmp_path, monkeypatch)
    state.fs.add("/sdk/resolver")
    state.entries["resolver"] = ["/sdk/resolver"]
    bill = module.produce(state)
    return state, bill


def test_entry_evidence_observes_independent_witness_and_exact_artifacts(entry_fixture, tmp_path, monkeypatch):
    from tools.benchmark import calibration_capture_pipeline_v4 as p

    state, bill = entry_fixture
    monkeypatch.setattr(p, "current_pid", lambda: state.context["pid"])
    evidence = p.capture_entry_evidence(bill, state.context, tmp_path / "evidence")
    assert len(evidence["baseline"]["files"]) == len(bill["files"])
    assert evidence["baseline"]["provenance"]["method"] == "independent-owned-descriptor-stream-v4"
    assert evidence["table"]["paths"] == bill["selected_paths"]
    assert len(evidence["transport"]["items"]) == len(bill["queries"]) + 2
    assert p.audit_entry_evidence(evidence["paths"], bill, state.context)["entry_path_context_consistent"]


@pytest.mark.parametrize("mutation", ["self", "table", "context", "artifact", "baseline", "terminal"])
def test_actual_entry_join_rejects_changed_evidence(entry_fixture, tmp_path, mutation, monkeypatch):
    import json

    from tools.benchmark import calibration_capture_pipeline_v4 as p

    state, bill = entry_fixture
    monkeypatch.setattr(p, "current_pid", lambda: state.context["pid"])
    e = p.capture_entry_evidence(bill, state.context, tmp_path / "evidence")
    path = e["paths"][
        {
            "self": "baseline",
            "table": "table",
            "context": "context",
            "artifact": "transport",
            "baseline": "baseline",
            "terminal": "transport",
        }[mutation]
    ]
    value = json.loads(Path(path).read_bytes())
    if mutation == "self":
        value["files"] = value["files"][1:]
    elif mutation == "table":
        value["paths"] = value["paths"][:-1]
    elif mutation == "context":
        value["dlopen_flags"] += 1
    elif mutation == "artifact":
        value["items"][0]["sha256"] = "0" * 64
    elif mutation == "baseline":
        value["provenance"]["method"] = "copied-from-bill"
    else:
        value["items"] = [r for r in value["items"] if not r["source"].endswith("entry-bill-terminal.json")]
    Path(path).write_text(json.dumps(value))
    with pytest.raises(ValueError):
        p.audit_entry_evidence(e["paths"], bill, state.context)


@pytest.mark.parametrize("function", ["prepare", "publish"])
def test_impl_cannot_bypass_missing_bootstrap(function, monkeypatch):
    from tools.benchmark import calibration_capture_pipeline_v4 as p

    monkeypatch.delitem(sys.modules, "tools.benchmark.static_v4_bootstrap", raising=False)
    with pytest.raises(ValueError):
        getattr(p, function)({}, {})


def test_runtime_only_requires_actual_modules_and_validates_mapped_aliases(entry_fixture, monkeypatch):
    from tools.benchmark import calibration_capture_pipeline_v4 as p

    state, bill = entry_fixture
    monkeypatch.setattr(p, "current_pid", lambda: state.context["pid"])

    def mapping(file):
        i = file["identity"]
        device = f"{i['device'] >> 8:02x}:{i['device'] & 255:02x}"
        return f"1000-2000 r-xp 00000000 {device} {i['inode']} {file['resolved']}\n"

    raw = "".join(mapping(r) for r in [state.context["interpreter"], *[m["origin"] for m in state.context["modules"]]])
    result = p.audit_runtime_context(
        state.context,
        state.context,
        raw,
        "postimports",
        table=dict(schema="loader-selected-path-table-v4", paths=bill["selected_paths"]),
    )
    assert result["pid"] == state.context["pid"] and not result["runtime_import_verified"]


def test_fixed_v4_verifier_refuses_arbitrary_study_path(tmp_path):
    from tools.benchmark.calibration_capture_study_v4 import verify_study_v4

    with pytest.raises(ValueError):
        verify_study_v4(tmp_path / "study.json", "0" * 64)


def test_terminal_transport_retains_original_posix_reference_on_windows(monkeypatch):
    import hashlib

    from tools.benchmark import native_entry_context_v4 as e

    bill = dict(aggregate_path="/sdk/entry-bill.json", completion_path="/sdk/entry-bill-terminal.json")
    data = e._bytes(bill)
    terminal = e._bytes(
        dict(
            schema="native-entry-context-terminal-v4",
            aggregate_path=bill["aggregate_path"],
            aggregate_bytes=len(data),
            aggregate_sha256=hashlib.sha256(data).hexdigest(),
        )
    )
    values = {bill["aggregate_path"]: data, bill["completion_path"]: terminal}
    calls = []

    def read(ref, limit):
        calls.append(ref["query_path"])
        value = values[ref["query_path"]]
        assert len(value) <= limit and hashlib.sha256(value).hexdigest() == ref["query_sha256"]
        return value

    monkeypatch.setattr(e, "_audit_content_v4", lambda *args, **kwargs: None)  # explicit semantic protocol;terminal only
    e.audit_entry_context_bill_v4(bill, baseline_files=[], python_context={}, artifact_reader=read)
    assert calls == [bill["completion_path"], bill["aggregate_path"]]


@pytest.fixture
def bound_evidence(entry_fixture, tmp_path, monkeypatch):
    from tools.benchmark import calibration_capture_pipeline_v4 as p

    state, bill = entry_fixture
    monkeypatch.setattr(p, "current_pid", lambda: state.context["pid"])
    evidence = p.capture_entry_evidence(bill, state.context, tmp_path / "binding-evidence")
    inventory = {role: [str(evidence["paths"][name])] for name, role in p.EVIDENCE_ROLES.items()}
    required = {r["file"]["resolved"] for r in bill["entries"]} | {r["canonical_path"] for r in bill["selected_paths"]}
    inventory["graph:dependencies"] = sorted(required - {"/sdk/resolver"})
    inventory["graph:resolver"] = ["/sdk/resolver"]
    inventory["runtime:project-source"] = [str(Path(state.m.__file__).absolute())]
    rows = []
    for name, role in p.EVIDENCE_ROLES.items():
        rows.append(dict(p.file_record(evidence["paths"][name]), role=role))
    rows.append(dict(p.file_record(state.m.__file__), role="runtime:project-source"))
    for file in bill["files"]:
        rows.append(
            dict(
                {k: v for k, v in file.items() if k != "byte_witness"},
                role="graph:resolver"
                if file["requested"] == "/sdk/resolver"
                else "graph:dependencies"
                if file["requested"] in required
                else "runtime:other",
            )
        )
    binding = dict(
        schema="capture-resource-binding-v4",
        capture_profile="target-bearing-raw-v1",
        inventory=inventory,
        baseline=dict(schema="declared-files-v1", files=rows),
    )
    return p, state, bill, binding


def test_actual_binding_canonical_self_and_context_join(bound_evidence):
    p, state, bill, binding = bound_evidence
    assert p.validate_evidence_binding(binding, bill)["entry_path_context_consistent"]


def test_actual_loaded_inventory_reserves_observer_source_role(bound_evidence):
    p, state, bill, binding = bound_evidence
    owner = p.InputInventory()
    p.add_loaded_code(owner.add, [state.m.__file__])
    path = str(Path(state.m.__file__).absolute())
    role = next(role for role, paths in owner.inventory.items() if path in paths)
    assert role == "runtime:project-source"
    observer = next(r for r in binding["baseline"]["files"] if r["requested"] == path)
    observer["role"] = role
    assert p.validate_evidence_binding(binding, bill)["entry_path_context_consistent"]


@pytest.mark.parametrize("mutation", ["zero-self", "alias-canonical", "observer-role", "legacy-role"])
def test_binding_membership_omissions_and_conflicting_roles_refuse(bound_evidence, mutation):
    p, state, bill, binding = bound_evidence
    if mutation == "zero-self":
        binding["inventory"]["graph:dependencies"].remove(bill["entries"][1]["file"]["resolved"])
    elif mutation == "alias-canonical":
        binding["baseline"]["files"] = [
            r for r in binding["baseline"]["files"] if r["requested"] != bill["selected_paths"][0]["canonical_path"]
        ]
    elif mutation == "observer-role":
        next(r for r in binding["baseline"]["files"] if r["requested"] == str(Path(state.m.__file__).absolute()))["role"] = (
            "runtime:other"
        )
    else:
        binding["inventory"]["runtime:python-extension-context"] = ["/wrong/legacy.json"]
    with pytest.raises(ValueError):
        p.validate_evidence_binding(binding, bill)


def test_actual_raw_execution_handoff_binds_v4_and_ordinary_avoids_read(bound_evidence, tmp_path, monkeypatch):
    from tools.benchmark import (
        calibration_capture_contract as raw,
    )
    from tools.benchmark import (
        capture_contract as contract,
    )
    from tools.benchmark import (
        capture_disarmed_sensors as capture,
    )

    p, state, bill, binding = bound_evidence
    args = capture.parse_capture_args(["--output", str(tmp_path / "capture")])
    args.capture_profile = "target-bearing-raw-v1"
    args.runtime_binding = tmp_path / "binding.json"
    args.runtime_binding.write_text("{}")
    args.execution_contract = tmp_path / "execution.json"
    args.wire_config = tmp_path / "wire.json"
    monkeypatch.setattr(
        contract, "wire_configuration_record", lambda _: dict(configuration=dict(schema="capture-wire-startup-v2"))
    )
    monkeypatch.setattr(contract, "read_declaration", lambda _: binding)
    monkeypatch.setattr(raw, "raw_graph", lambda _: dict(prepared_input="inert protocol"))
    result = contract.execution_contract(args, {"PATH": "/usr/bin:/bin"})
    assert result["python_extension_context"]["schema"] == "bound-python-extension-context-v4"
    assert result["python_extension_context"]["loader_selected_paths_sha256"] == p.digest(
        p.declared_context(binding)["evidence"]["table"]
    )
    args.capture_profile = None

    def no_read(_):
        raise AssertionError("ordinary profile read v4 binding")

    monkeypatch.setattr(contract, "read_declaration", no_read)
    assert "python_extension_context" not in contract.execution_contract(args, {"PATH": "/usr/bin:/bin"})


@pytest.mark.parametrize("bad", [False, True])
def test_shared_runtime_phase_advances_only_with_actual_same_sdk_context(entry_fixture, tmp_path, monkeypatch, bad):
    import copy

    from tools.benchmark import calibration_capture_pipeline_v4 as p
    from tools.benchmark import runtime_resource_binding as runtime

    state, bill = entry_fixture
    monkeypatch.setattr(p, "current_pid", lambda: state.context["pid"])
    current = copy.deepcopy(state.context)
    if bad:
        current["modules"][0]["spec_origin"] = "/wrong/origin"
    monkeypatch.setattr(state.m, "collect_python_context", lambda: current)
    monkeypatch.setattr(runtime.os, "major", lambda device: device >> 8, raising=False)
    monkeypatch.setattr(runtime.os, "minor", lambda device: device & 255, raising=False)
    raw = "".join(
        f"1000-2000 r-xp 0 {r['identity']['device'] >> 8:02x}:{r['identity']['device'] & 255:02x} {r['identity']['inode']} {r['resolved']}\n"
        for r in [state.context["interpreter"], *[m["origin"] for m in state.context["modules"]]]
    )
    obj = runtime.RuntimeBinding.__new__(runtime.RuntimeBinding)
    obj.pre_recorded = True
    obj.errors = []
    obj.closed = False
    obj.required_self = ["postimports", "postfinalize", "postfirststep"]
    obj.completed_self = []
    obj.phases = []
    obj.python_context = state.context
    obj.python_loader_table = dict(schema="loader-selected-path-table-v4", paths=bill["selected_paths"])
    obj.before = dict(files=bill["files"])
    obj.map_reader = lambda: raw
    obj.output = tmp_path
    if bad:
        with pytest.raises(ValueError):
            obj.observe("postimports")
        assert obj.errors and not obj.completed_self
        with pytest.raises(ValueError):
            obj.observe("postimports")
    else:
        obj.observe("postimports")
        assert obj.completed_self == ["postimports"]
    record = (tmp_path / "runtime-python-context-postimports.json").read_text()
    assert "observed_context" in record


def test_sdk_terminal_is_after_successful_scope_finalization(monkeypatch):
    from tools.benchmark import calibration_capture_pipeline_v4 as p
    from tools.benchmark import prepare_calibration_capture_v4 as public

    ticket = {"inert": "reference protocol"}
    state = dict(schema="revalidated-static-sdk-context-v4", sdk_pid=p.current_pid(), ticket=ticket)
    calls = []
    monkeypatch.setattr(public, "_authorize", lambda _: state)

    def work(*_):
        calls.extend(["work", "finally-scope"])
        return {"declared_runtime_graph_frozen": False}

    def finish(*_):
        calls.append("terminal")
        return {"declared_runtime_graph_frozen": True}

    monkeypatch.setattr(p, "_prepare_sdk", work)
    monkeypatch.setattr(p, "_finish_sdk", finish, raising=False)
    assert p.prepare(ticket, state)["declared_runtime_graph_frozen"]
    assert calls == ["work", "finally-scope", "terminal"]


def test_independent_baseline_failure_keeps_observed_prefix(entry_fixture, tmp_path, monkeypatch):
    import json

    from tools.benchmark import calibration_capture_pipeline_v4 as p

    state, bill = entry_fixture
    original = state.m._file_witness
    calls = []

    def fail(path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("independent descriptor observer failed")
        return original(path)

    monkeypatch.setattr(state.m, "_file_witness", fail)
    with pytest.raises(OSError, match="independent descriptor") as caught:
        p.capture_entry_evidence(bill, state.context, tmp_path / "failed-evidence")
    record = json.loads((tmp_path / "failed-evidence/evidence-failure.json").read_bytes())
    assert len(record["baseline_files"]) == 1 and record["complete"] is False and record["error"]
    assert caught.value.partial_evidence["baseline_files"] == record["baseline_files"]


def test_retained_posix_graph_replay_uses_explicit_path_semantics():
    import importlib.util
    from pathlib import PurePosixPath

    from tools.benchmark.audit_live_wire_resources import audit_resource_graph_records

    spec = importlib.util.spec_from_file_location(
        "retained_graph_fixture", ROOT / "tests/benchmark/test_live_wire_resource_graph.py"
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    value = fixture.fixture(PurePosixPath("/fixture/sdk"))
    result = audit_resource_graph_records(**value, path_factory=PurePosixPath)
    assert result["raw_graph_records_consistent"] and not result["current_sdk_executed"]


@pytest.fixture
def finished_records(monkeypatch):
    """Finished semantic contract only: explicit bill/graph backends are inert.

    Actual Task2 evidence and original graph replay have separate tests above.
    These native pins are protocol metadata, not actual descriptor observations.
    """
    import copy
    import hashlib
    import json
    from pathlib import PurePosixPath as P
    from types import SimpleNamespace

    from tools.benchmark import audit_live_wire_resources as graph
    from tools.benchmark import calibration_capture_contract as raw
    from tools.benchmark import calibration_capture_pipeline_v4 as p
    from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256

    def sha(data):
        return hashlib.sha256(data).hexdigest()

    def pin(path, data=b"protocol", override=None):
        identity = dict(device=1, inode=1, mode=33188, size=len(data), mtime_ns=1, ctime_ns=1)
        return dict(
            requested=path,
            resolved=path,
            links=[],
            identity=identity,
            path_identity=dict(identity),
            bytes=len(data),
            sha256=override or sha(data),
        )

    root = "/fixture/sdk"
    folder = P(root) / "results/target-bearing-runtime-freeze-v4-dev-1701/frozen-study-v4"
    source = P(root) / "results/target-bearing-scene-production-dev-1701/actual-scene-v3"
    registry = p.native_registry(root, "/usr/bin/python3")
    values = {r: b"protocol-source" for r in registry}
    values["logger_topics"] = (ROOT / "config/px4/source-diagnostic-v1/logger_topics.txt").read_bytes()
    values["logger_profile"] = (ROOT / "config/px4/source-diagnostic-v1/profile.json").read_bytes()
    manifest = dict(files={"scene-load.json": dict(bytes=3, sha256=sha(b"xxx"))})
    values["scene_manifest"] = p.entry._bytes(manifest)
    monkeypatch.setattr(raw, "SCENE_MANIFEST_SHA", sha(values["scene_manifest"]))
    load = dict(geometry={}, design={}, qualification=dict(p.QUALIFICATION))
    values["scene_load"] = p.entry._bytes(load)
    manifest["files"]["scene-load.json"] = dict(bytes=len(values["scene_load"]), sha256=sha(values["scene_load"]))
    values["scene_manifest"] = p.entry._bytes(manifest)
    monkeypatch.setattr(raw, "SCENE_MANIFEST_SHA", sha(values["scene_manifest"]))
    scene = dict(
        schema="target-bearing-scene-selection-v1",
        path=str(source),
        manifest_sha256=sha(values["scene_manifest"]),
        files=dict(
            manifest["files"],
            **{"manifest.json": dict(bytes=len(values["scene_manifest"]), sha256=sha(values["scene_manifest"]))},
        ),
        **load,
    )
    context = dict(pid=123, interpreter=pin("/usr/bin/python3"))
    values["context"] = p.entry._bytes(context)
    agent = dict(
        schema="capture-agent-runtime-v1", bundle="/cache/bundle", binary="/cache/Agent", lib_dir="/cache/lib", port=18888
    )
    values["agent"] = p.entry._bytes(agent)
    values["wire"] = p.entry._bytes(
        dict(schema="capture-wire-startup-v2", session_id="inert", sim_origin_ns=0, remote_origin_ns=1, startup_max_wall_ns=100)
    )
    baseline = dict(
        schema="independent-entry-baseline-v4",
        files=[],
        provenance=dict(
            method="independent-owned-descriptor-stream-v4",
            pid=123,
            observer_code_sha256=sha(values["dependency_code"]),
            started_monotonic_ns=1,
            ended_monotonic_ns=2,
        ),
    )
    values["baseline"] = p.entry._bytes(baseline)
    bill = dict(
        files=[],
        entries=[],
        selected_paths=[],
        agent_paths=[agent["binary"], *[str(P(agent["lib_dir"]) / n) for n in sorted(LIBRARY_SHA256)]],
        agent_lib=agent["lib_dir"],
    )
    values["entry_bill"] = p.entry._bytes(bill)
    values["transport"] = p.entry._bytes(dict(schema="entry-artifact-transport-v4", items=[]))
    table = dict(
        schema="loader-selected-path-table-v4",
        paths=[],
        context_sha256=p.entry.context_digest(context),
        baseline_sha256=sha(values["baseline"]),
        bill_sha256=sha(values["entry_bill"]),
        transport_sha256=sha(values["transport"]),
    )
    values["table"] = p.entry._bytes(table)
    extra = [pin(agent["bundle"], override=BUNDLE_SHA256), pin(agent["binary"], override=AGENT_SHA256)]
    extra += [pin(str(P(agent["lib_dir"]) / n), override=v) for n, v in sorted(LIBRARY_SHA256.items())]
    for name, r in scene["files"].items():
        for prefix in (source, folder / "capture-input-v1"):
            extra.append(pin(str(prefix / name), b"0" * r["bytes"], r["sha256"]))
    binding = dict(
        schema="capture-resource-binding-v4",
        capture_profile="target-bearing-raw-v1",
        inventory={role: [registry[name]] for name, role in p.EVIDENCE_ROLES.items()},
        environment={"PATH": "/usr/bin:/bin"},
        graph={"environment": {"PATH": "/usr/bin:/bin"}},
        calibration_scene=scene,
        baseline=dict(files=[dict(pin(registry["dependency_code"], values["dependency_code"]), role="runtime:project-source")]),
    )
    preparation = dict(
        schema="raw-static-sdk-preparation-v4",
        sdk_pid=123,
        sdk_ticket={"inert": "reference"},
        pre={"files": []},
        after_queries={},
        graph={},
        context={},
        queries=[],
        documents_hex={},
        audit={"inert": True},
    )
    monkeypatch.setattr(p, "canonical_membership", lambda *_: None)
    monkeypatch.setattr(p.entry, "audit_entry_context_bill_v4", lambda *_, **__: None)
    monkeypatch.setattr(graph, "audit_resource_graph_records", lambda **_: {"inert": True})

    def refresh():
        values["baseline"] = p.entry._bytes(baseline)
        table["baseline_sha256"] = sha(values["baseline"])
        values["table"] = p.entry._bytes(table)
        # Recompute context reference after the changed table, even for negative cases.
        if "execution" in values:
            execution = json.loads(values["execution"])
            if "python_extension_context" in execution:
                execution["python_extension_context"]["loader_selected_paths_sha256"] = sha(values["table"])
                execution["python_extension_context"]["loader_selected_paths_semantic_sha256"] = p.entry.context_digest(table)
            values["execution"] = p.entry._bytes(execution)
        values["binding"] = p.entry._bytes(binding)
        preparation.update(
            binding_sha256=sha(values["binding"]),
            execution_sha256=sha(values["execution"]),
            entry_bill_sha256=sha(values["entry_bill"]),
        )
        values["preparation"] = p.entry._bytes(preparation)
        rows = {r: dict(role=r, source=pin(path, values[r]), member=r + ".bin") for r, path in registry.items()}
        study = dict(
            schema="target-bearing-frozen-raw-study-v4",
            qualification=dict(p.QUALIFICATION),
            files={r: v["source"] for r, v in rows.items()},
        )
        values["study"] = p.entry._bytes(study)
        studysha = sha(values["study"])
        rows["study"] = dict(role="study", source=pin(str(folder / "study.json"), values["study"]), member="study.bin")
        native = {r["source"]["requested"]: r["source"] for r in rows.values()}
        native.update({r["requested"]: r for r in extra})
        native.update({r["requested"]: {k: v for k, v in r.items() if k != "role"} for r in binding["baseline"]["files"]})
        terminal = p.entry._bytes(
            dict(
                study_sha256=studysha,
                sdk_pid=123,
                ticket_sha256=p.entry.context_digest(preparation["sdk_ticket"]),
                preparation_sha256=sha(values["preparation"]),
            )
        )
        index = dict(schema="finished-static-artifacts-v4", files=list(rows.values()), sdk_terminal_sha256=sha(terminal))
        identity = dict(
            schema="validated-static-prepost-receipts-v4",
            source_root=root,
            files=list(native.values()),
            study_sha256=studysha,
            index_sha256=sha(p.entry._bytes(index)),
            sdk_exit=0,
        )
        return identity, studysha, index, copy.deepcopy(values), terminal, lambda *_: b""

    rows = {r: dict(source=pin(path, values[r])) for r, path in registry.items()}
    native = {r["requested"]: r for r in extra}
    values["execution"] = p.entry._bytes(p.expected_finished_execution(root, binding, values, rows, native))
    return SimpleNamespace(p=p, values=values, registry=registry, baseline=baseline, refresh=refresh)


def test_finished_semantic_contract_accepts_inert_complete_records(finished_records):
    f = finished_records
    assert f.p.audit_finished_records(*f.refresh())["transported_finished_metadata"]


@pytest.mark.parametrize("mutation", ["remove", "extra", "path"])
def test_finished_exact_registry_rejects_coordinated_changes(finished_records, mutation):
    f = finished_records
    if mutation == "remove":
        f.registry.pop("dispatcher")
    elif mutation == "extra":
        f.registry["other"] = "/fixture/sdk/other"
        f.values["other"] = b"other"
    else:
        f.registry["dispatcher"] = "/fixture/sdk/alternate-dispatcher.py"
    with pytest.raises(ValueError, match="registry"):
        f.p.audit_finished_records(*f.refresh())


@pytest.mark.parametrize(
    "mutation", ["owned_ulog_source", "record_depth_payload", "logger_diagnostic", "launch_environment", "unexpected"]
)
def test_finished_exact_execution_rejects_refreshed_semantic_changes(finished_records, mutation):
    import json

    f = finished_records
    execution = json.loads(f.values["execution"])
    if mutation == "launch_environment":
        execution[mutation]["PATH"] = "/altered"
    elif mutation == "unexpected":
        execution["unexpected"] = True
    else:
        execution.pop(mutation)
    f.values["execution"] = f.p.entry._bytes(execution)
    with pytest.raises(ValueError, match="execution contract"):
        f.p.audit_finished_records(*f.refresh())


@pytest.mark.parametrize("mutation", ["absent", "method", "pid", "source", "clock"])
def test_finished_independent_provenance_rejects_coordinated_changes(finished_records, mutation):
    f = finished_records
    if mutation == "absent":
        f.baseline.pop("provenance")
    else:
        key, value = {
            "method": ("method", "copied-from-bill"),
            "pid": ("pid", 456),
            "source": ("observer_code_sha256", "0" * 64),
            "clock": ("ended_monotonic_ns", 0),
        }[mutation]
        f.baseline["provenance"][key] = value
    with pytest.raises(ValueError, match="provenance"):
        f.p.audit_finished_records(*f.refresh())


def test_matching_ticket_shape_has_no_authority_before_deferred_import(monkeypatch):
    from tools.benchmark import prepare_calibration_capture_v4 as public

    monkeypatch.delitem(sys.modules, "tools.benchmark.static_v4_bootstrap", raising=False)
    ticket = dict(
        schema="static-sdk-ticket-reference-v4",
        nonce="a" * 64,
        unit="inert.scope",
        InvocationID="b" * 32,
        ControlGroup="/inert",
        claim_sha256="c" * 64,
        recipe_sha256="d" * 64,
        preidentity_sha256="e" * 64,
        sdk_start_sha256="f" * 64,
    )

    def trap(*args, **kwargs):
        raise AssertionError("deferred effect")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", trap)
        patch.setattr(builtins, "__import__", trap)
        with pytest.raises(ValueError, match="already loaded literal bootstrap"):
            public.prepare_v4(ticket)


def test_retained_record_provider_cannot_change_ordinary_contract(tmp_path):
    from tools.benchmark.capture_contract import execution_contract
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    args = parse_capture_args(["--output", str(tmp_path)])
    with pytest.raises(ValueError, match="explicit raw profile"):
        execution_contract(args, record_provider=object())
