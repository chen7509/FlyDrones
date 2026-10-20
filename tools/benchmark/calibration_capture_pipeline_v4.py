"""Late imported v4 implementation; no dispatcher, simulator or CLI entry."""

# ruff: noqa: E402 -- direct-main denial precedes all normal imports
if __name__ == "__main__":
    raise SystemExit("direct pipeline entry denied")
import datetime
import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from tools.benchmark import native_entry_context_v4 as entry
from tools.benchmark.calibration_capture_study import SOURCE, arguments
from tools.benchmark.calibration_capture_study_v4 import publish_study_v4
from tools.benchmark.capture_contract import _typed_equal, execution_contract, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "results/target-bearing-runtime-freeze-v4-dev-1701/frozen-study-v4"
QUALIFICATION = dict(entry.QUALIFICATION)
EVIDENCE_ROLES = {
    "context": "runtime:python-extension-context-v4",
    "baseline": "runtime:entry-byte-witness-v4",
    "table": "graph:loader-selected-paths",
    "transport": "runtime:entry-context-artifacts-v4",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def current_pid():
    return os.getpid()


class InputInventory:
    """Unique-path ownership used by the actual SDK producer."""

    def __init__(self):
        self.inventory = {}
        self.used = set()

    def add(self, role, values):
        selected = []
        for value in values:
            path = str(Path(value).absolute())
            if path not in self.used:
                self.used.add(path)
                selected.append(path)
        if selected:
            self.inventory[role] = selected


def project_source_paths():
    return sorted(
        p
        for scope in (ROOT / "src/flydrones", ROOT / "tools/benchmark", ROOT / "tools/connectome")
        for p in scope.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def add_loaded_code(add, modules):
    add("runtime:project-source", project_source_paths())
    add("runtime:python-modules", modules)


def capture_entry_evidence(bill, context, output):
    output = Path(output)
    output.mkdir()
    state = dict(complete=False, error=None, baseline_files=[], transport_members=[])
    try:
        return _capture_entry_evidence(bill, context, output, state)
    except BaseException as exc:
        state["error"] = repr(exc)
        state["partial_observer"] = getattr(exc, "partial_file_witness", None)
        exc.partial_evidence = state
        try:
            write_manifest(output / "evidence-failure.json", state)
        except Exception as writer:
            exc.add_note("evidence failure writer secondary: " + repr(writer))
            try:
                entry._fallback(output / "evidence-failure-fallback.json", state)
            except Exception as other:
                exc.add_note("evidence fallback unavailable: " + repr(other))
        raise


def _capture_entry_evidence(bill, context, output, state):
    started = time.monotonic_ns()
    # Fresh descriptor reads, not copying the producer's byte witness.
    files = state["baseline_files"]
    for r in bill["files"]:
        files.append(entry._file_witness(r["requested"]))
    baseline = dict(
        schema="independent-entry-baseline-v4",
        files=files,
        provenance=dict(
            method="independent-owned-descriptor-stream-v4",
            pid=current_pid(),
            observer_code_sha256=digest(entry.__file__),
            started_monotonic_ns=started,
            ended_monotonic_ns=time.monotonic_ns(),
        ),
    )
    entry.audit_entry_context_bill_v4(bill, baseline_files=files, python_context=context)
    refs = [q["artifact"] for q in bill["queries"]]
    refs += [dict(query_path=bill[k], query_sha256=digest(bill[k])) for k in ("aggregate_path", "completion_path")]
    members = state["transport_members"]
    for number, ref in enumerate(refs):
        data = Path(ref["query_path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != ref["query_sha256"]:
            raise ValueError("transport source bytes changed")
        name = f"artifact-{number:04d}.bin"
        with (output / name).open("xb") as stream:
            if stream.write(data) != len(data):
                raise OSError("short transport write")
        members.append(dict(source=ref["query_path"], sha256=ref["query_sha256"], bytes=len(data), member=name))
    transport = dict(schema="entry-artifact-transport-v4", items=members)
    paths = {k: output / (k + ".json") for k in EVIDENCE_ROLES}
    write_manifest(paths["context"], context)
    write_manifest(paths["baseline"], baseline)
    write_manifest(paths["transport"], transport)
    table = dict(
        schema="loader-selected-path-table-v4",
        paths=bill["selected_paths"],
        context_sha256=entry.context_digest(context),
        baseline_sha256=digest(paths["baseline"]),
        transport_sha256=digest(paths["transport"]),
        bill_sha256=digest(bill["aggregate_path"]),
    )
    write_manifest(paths["table"], table)
    audit_entry_evidence(paths, bill, context)
    state["complete"] = True
    return dict(paths=paths, baseline=baseline, table=table, transport=transport)


def artifact_reader(index_path):
    index_path = Path(index_path)
    index = read_declaration(index_path)
    if set(index) != {"schema", "items"} or index["schema"] != "entry-artifact-transport-v4" or type(index["items"]) is not list:
        raise ValueError("exact artifact transport required")
    rows = {r["source"]: r for r in index["items"]}
    if len(rows) != len(index["items"]) or len(rows) > 1028:
        raise ValueError("transport duplicate/bound")
    names = set()
    for row in rows.values():
        if (
            set(row) != {"source", "sha256", "bytes", "member"}
            or type(row["member"]) is not str
            or row["member"] in names
            or not row["member"].startswith("artifact-")
            or Path(row["member"]).name != row["member"]
            or "/" in row["member"]
            or "\\" in row["member"]
        ):
            raise ValueError("transport member escapes or duplicates")
        names.add(row["member"])

    def read(ref, limit):
        row = rows.get(ref["query_path"])
        if row is None or row["sha256"] != ref["query_sha256"] or type(row["bytes"]) is not int or not 0 <= row["bytes"] <= limit:
            raise ValueError("exact transported source reference missing/different")
        with (index_path.parent / row["member"]).open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("transport bytes differ")
        return data

    return read


def audit_independent_baseline(baseline, bill, context, observer):
    """Pure procedure/membership join to a separately validated native source pin."""
    proof = baseline.get("provenance", {})
    if (
        set(baseline) != {"schema", "files", "provenance"}
        or baseline["schema"] != "independent-entry-baseline-v4"
        or set(proof) != {"method", "pid", "observer_code_sha256", "started_monotonic_ns", "ended_monotonic_ns"}
        or proof["method"] != "independent-owned-descriptor-stream-v4"
        or proof["pid"] != context["pid"]
        or proof["observer_code_sha256"] != observer["sha256"]
        or any(type(proof[k]) is not int or proof[k] < 0 for k in ("started_monotonic_ns", "ended_monotonic_ns"))
        or proof["ended_monotonic_ns"] < proof["started_monotonic_ns"]
    ):
        raise ValueError("independent descriptor observation provenance differs")
    # Exact membership also refuses removed self/canonical files.
    names = [r["requested"] for r in baseline["files"]]
    if len(names) != len(set(names)) or set(names) != {r["requested"] for r in bill["files"]}:
        raise ValueError("independent canonical/self membership differs")


def audit_entry_evidence(paths, bill, context):
    if set(paths) != set(EVIDENCE_ROLES):
        raise ValueError("exact evidence role set required")
    actual = read_declaration(paths["context"])
    if not _typed_equal(actual, context):
        raise ValueError("context artifact differs")
    baseline = read_declaration(paths["baseline"])
    audit_independent_baseline(baseline, bill, context, file_record(entry.__file__))
    reader = artifact_reader(paths["transport"])
    entry.audit_entry_context_bill_v4(bill, baseline_files=baseline["files"], python_context=context, artifact_reader=reader)
    table = read_declaration(paths["table"])
    expected = dict(
        schema="loader-selected-path-table-v4",
        paths=bill["selected_paths"],
        context_sha256=entry.context_digest(context),
        baseline_sha256=digest(paths["baseline"]),
        transport_sha256=digest(paths["transport"]),
        bill_sha256=hashlib.sha256(entry._bytes(bill)).hexdigest(),
    )
    if not _typed_equal(table, expected):
        raise ValueError("raw alias/table/bill/context joins differ")
    index = read_declaration(paths["transport"])
    expected_sources = {q["artifact"]["query_path"] for q in bill["queries"]} | {bill["aggregate_path"], bill["completion_path"]}
    if {r["source"] for r in index["items"]} != expected_sources:
        raise ValueError("transport extra/missing query/terminal")
    return dict(
        entry_path_context_consistent=True,
        context_sha256=entry.context_digest(context),
        loader_selected_paths_sha256=digest(paths["table"]),
        loader_selected_paths_semantic_sha256=entry.context_digest(table),
        independent_baseline_sha256=digest(paths["baseline"]),
        runtime_closure_qualified=False,
    )


def declared_context(binding):
    inventory = binding.get("inventory", {})
    if "graph:loader-selected-paths" not in inventory:
        return None
    if {"runtime:python-extension-context", "runtime:entry-context-bill"} & set(inventory):
        raise ValueError("conflicting legacy/v4 context roles")
    if binding.get("schema") != "capture-resource-binding-v4" or binding.get("capture_profile") != "target-bearing-raw-v1":
        raise ValueError("v4 context requires explicit raw binding")
    rows = {r["requested"]: r for r in binding["baseline"]["files"]}
    selected = {}
    for name, role in EVIDENCE_ROLES.items():
        values = inventory.get(role)
        if type(values) is not list or len(values) != 1:
            raise ValueError("one exact v4 evidence role required")
        actual = file_record(values[0])
        old = rows.get(values[0], {})
        if old.get("role") != role or not _typed_equal(actual, {k: v for k, v in old.items() if k != "role"}):
            raise ValueError("v4 evidence file baseline differs")
        selected[name] = values[0]
    context = read_declaration(selected["context"])
    entry.validate_python_context(context)
    return dict(
        schema="bound-python-extension-context-v4",
        file=file_record(selected["context"]),
        context_sha256=entry.context_digest(context),
        loader_selected_paths_sha256=digest(selected["table"]),
        loader_selected_paths_semantic_sha256=entry.context_digest(read_declaration(selected["table"])),
        evidence=selected,
    )


def audit_python_runtime(expected, raw_maps, phase, *, table=None):
    current = None
    try:
        current = entry.collect_python_context()
        return audit_runtime_context(expected, current, raw_maps, phase, table=table)
    except Exception as exc:
        exc.observed_python_context = current
        raise


def audit_runtime_context(expected, current, raw_maps, phase, *, table=None):
    from tools.benchmark.owned_runtime_maps import _device_parts, parse_maps

    if phase not in ("postimports", "postfinalize", "postfirststep"):
        raise ValueError("self SDK phase required")
    entry.validate_python_context(expected)
    entry.validate_python_context(current)
    if current["pid"] != current_pid():
        raise ValueError("actual SDK PID differs")
    for key in ("interpreter", "implementation", "version", "version_info", "soabi", "ext_suffix", "dlopen_flags"):
        if not _typed_equal(expected[key], current[key]):
            raise ValueError("SDK interpreter/ABI/flags differ")
    modules = {r["name"]: r for r in current["modules"]}
    maps = parse_maps(raw_maps)
    required = [expected["interpreter"]] + [r["origin"] for r in expected["modules"]]
    for module in expected["modules"]:
        if not _typed_equal(module, modules.get(module["name"])):
            raise ValueError("actual SDK module origin differs")
    if table is None or table.get("schema") != "loader-selected-path-table-v4":
        raise ValueError("bound loader table required")
    for file in required:
        if not any(
            row["path"] == file["resolved"]
            and row["inode"] == file["identity"]["inode"]
            and tuple(int(x, 16) for x in row["device"].split(":")) == _device_parts(file["identity"]["device"])
            for row in maps
        ):
            raise ValueError("required SDK canonical/module mapping missing/different")
    # Metadata-selected plugins need not be mapped yet. Validate those actually
    # present, without presenting trace selection as initialization evidence.
    for selected in table["paths"]:
        for mapped in maps:
            if mapped["path"] in (selected["canonical_path"], selected["raw_path"]):
                identity = selected["fd_before"]
                if mapped["inode"] != identity["inode"] or tuple(
                    int(x, 16) for x in mapped["device"].split(":")
                ) != _device_parts(identity["device"]):
                    raise ValueError("mapped loader alias canonical identity differs")
    return dict(
        phase=phase,
        pid=current["pid"],
        observed_context=current,
        static_context_pid=expected["pid"],
        context_sha256=entry.context_digest(expected),
        loader_selected_paths_semantic_sha256=entry.context_digest(table),
        runtime_import_verified=False,
        symbols_resolved=False,
        runtime_closure_qualified=False,
    )


def _state(ticket, state):
    if (
        type(state) is not dict
        or set(state) != {"schema", "sdk_pid", "ticket"}
        or state["schema"] != "revalidated-static-sdk-context-v4"
        or state["sdk_pid"] != current_pid()
        or not _typed_equal(state["ticket"], ticket)
    ):
        raise ValueError("same actual SDK PID/revalidated reference required")


def prepare(ticket, state=None):
    from tools.benchmark.prepare_calibration_capture_v4 import _authorize

    actual = _authorize(ticket)
    _state(ticket, actual)
    if state is not None and not _typed_equal(actual, state):
        raise ValueError("preparation admission changed")
    staged = _prepare_sdk(ticket, actual)
    return _finish_sdk(ticket, actual, staged)


def paths(python=None):
    from tools.benchmark import calibration_capture_study as shared

    selected = shared.study_paths(FOLDER)
    selected.update(
        study_code=ROOT / "tools/benchmark/calibration_capture_study_v4.py",
        producer_code=ROOT / "tools/benchmark/prepare_calibration_capture_v4.py",
        pipeline_code=Path(__file__),
        dependency_code=Path(entry.__file__),
        paths_code=ROOT / "tools/benchmark/native_loader_paths_v4.py",
        scene_manifest=SOURCE / "manifest.json",
        scene_load=SOURCE / "scene-load.json",
        logger_topics=ROOT / "config/px4/source-diagnostic-v1/logger_topics.txt",
        logger_profile=ROOT / "config/px4/source-diagnostic-v1/profile.json",
        entry_bill=FOLDER / "sdk/entry-dependencies/entry-bill.json",
    )
    selected.update({name: FOLDER / "sdk/entry-evidence" / (name + ".json") for name in EVIDENCE_ROLES})
    if python is None:
        python = read_declaration(selected["context"])["interpreter"]["requested"]
    selected["python"] = Path(python)
    return selected


def validate_evidence_binding(binding, bill):
    context_bound = declared_context(binding)
    if context_bound is None:
        raise ValueError("complete bound v4 path/context evidence required")
    evidence = context_bound["evidence"]
    context = read_declaration(evidence["context"])
    result = audit_entry_evidence(evidence, bill, context)
    baseline = {r["requested"]: r for r in binding["baseline"]["files"]}
    canonical_membership(binding, bill)
    # Independently observed descriptor procedure is bound to actual producer
    # code bytes in the same current source baseline, not only a SHA label.
    observer = baseline.get(str(Path(entry.__file__).absolute()), {})
    if observer.get("role") != "runtime:project-source" or not _typed_equal(
        {k: v for k, v in observer.items() if k != "role"}, file_record(entry.__file__)
    ):
        raise ValueError("independent witness observer code not in current baseline")
    return result


def canonical_membership(binding, bill):
    baseline = {r["requested"]: r for r in binding["baseline"]["files"]}
    if len(baseline) != len(binding["baseline"]["files"]):
        raise ValueError("duplicate canonical baseline member")
    resolver = binding["inventory"].get("graph:resolver", [])
    if len(resolver) != 1 or not any(
        r["source_role"] == "resolver" and r["file"]["requested"] == resolver[0] for r in bill["entries"]
    ):
        raise ValueError("exact actual resolver entry/root required")
    for canonical in bill["files"]:
        path = canonical["requested"]
        row = baseline.get(path, {})
        if not _typed_equal(
            {k: v for k, v in row.items() if k != "role"}, {k: v for k, v in canonical.items() if k != "byte_witness"}
        ):
            raise ValueError("canonical/self current baseline pin missing/different")
    required = {r["file"]["resolved"] for r in bill["entries"]} | {r["canonical_path"] for r in bill["selected_paths"]}
    required -= set(binding["inventory"].get("graph:resolver", []))
    if not required <= set(binding["inventory"].get("graph:dependencies", [])):
        raise ValueError("canonical/self graph dependency missing")


def validate_binding_v4(binding):
    role = "runtime:entry-context-bill-v4"
    values = binding.get("inventory", {}).get(role)
    if type(values) is not list or len(values) != 1:
        raise ValueError("exact v4 bill role required")
    actual = file_record(values[0])
    rows = [r for r in binding["baseline"]["files"] if r["role"] == role]
    if len(rows) != 1 or not _typed_equal({k: v for k, v in rows[0].items() if k != "role"}, actual):
        raise ValueError("v4 bill baseline bytes differ")
    return validate_evidence_binding(binding, read_declaration(values[0]))


def audit_preparation(binding, preparation, bill_path, bill):
    from tools.benchmark import calibration_capture_study as shared
    from tools.benchmark.agent_capture_runtime import agent_runtime_record

    fixed = FOLDER / "sdk/entry-dependencies/entry-bill.json"
    if Path(bill_path).absolute() != fixed or not _typed_equal(read_declaration(bill_path), bill):
        raise ValueError("literal actual v4 bill path/bytes differ")
    if preparation.get("schema") != "raw-static-sdk-preparation-v4" or preparation.get("entry_bill_sha256") != digest(bill_path):
        raise ValueError("v4 preparation bill/schema differs")
    result = validate_evidence_binding(binding, bill)
    context = declared_context(binding)
    if (
        preparation.get("python_context_file_sha256") != context["file"]["sha256"]
        or preparation.get("python_context_sha256") != context["context_sha256"]
        or not _typed_equal(preparation.get("entry_evidence"), result)
    ):
        raise ValueError("preparation evidence semantic/byte joins differ")
    bill_rows = [r for r in binding["baseline"]["files"] if r["role"] == "runtime:entry-context-bill-v4"]
    if len(bill_rows) != 1 or not _typed_equal({k: v for k, v in bill_rows[0].items() if k != "role"}, file_record(bill_path)):
        raise ValueError("bill missing from exact binding baseline")
    projected = {
        k: v
        for k, v in preparation.items()
        if k
        not in {
            "entry_bill_sha256",
            "python_context_file_sha256",
            "python_context_sha256",
            "query_clocks",
            "entry_evidence",
            "sdk_ticket",
            "sdk_pid",
        }
    }
    projected["schema"] = "raw-static-sdk-preparation-v1"
    graph = shared.audit_preparation_at(binding, projected, FOLDER)
    audit_query_clocks(preparation)
    agent = agent_runtime_record(FOLDER / "agent-runtime.json")
    config = agent["configuration"]
    expected = [p for p in agent["selected_paths"] if p == config["binary"] or Path(p).parent == Path(config["lib_dir"])]
    if bill["agent_paths"] != expected or bill["agent_lib"] != config["lib_dir"]:
        raise ValueError("actual Agent loader subset/context differs")
    if preparation.get("sdk_pid") != bill["python_context"]["pid"]:
        raise ValueError("preparation and bill SDK PID differ")
    return dict(graph, **result)


def _verify_contents(path, sha, *, require_absent=True):
    from tools.benchmark import calibration_capture_study as shared

    if Path(path).absolute() != FOLDER / "study.json":
        raise ValueError("literal v4 study required")
    return shared._verify_profile_study(
        path, sha, FOLDER, "target-bearing-frozen-raw-study-v4", paths(), require_absent=require_absent, v4=True
    )


def _sdk_receipt(ticket, sha, pid):
    after = read_declaration(FOLDER.parent / "sdk-inside-after.json")
    if (
        after.get("error") is not None
        or "counter_error" in after
        or after.get("limits")
        != {"memory.max": str(512 * 1024**2), "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "64"}
        or after.get("cgroup") != "/sys/fs/cgroup" + ticket["ControlGroup"]
    ):
        raise ValueError("SDK scope final observations unavailable/different")
    return dict(
        schema="raw-sdk-study-terminal-v4",
        study_sha256=sha,
        preparation_sha256=digest(FOLDER / "preparation.json"),
        scope_after_sha256=digest(FOLDER.parent / "sdk-inside-after.json"),
        sdk_pid=pid,
        ticket_sha256=entry.context_digest(ticket),
    )


def verify(path, sha, *, require_absent=True):
    if Path(path).absolute() != FOLDER / "study.json":
        raise ValueError("literal v4 study required")
    if os.name == "nt":
        return verify_finished_transport(path, sha, require_absent=require_absent)
    prep = read_declaration(FOLDER / "preparation.json")
    receipt = _sdk_receipt(prep["sdk_ticket"], sha, prep["sdk_pid"])
    if not _typed_equal(read_declaration(FOLDER / "sdk-complete.json"), receipt):
        raise ValueError("committed SDK terminal differs")
    return _verify_contents(path, sha, require_absent=require_absent)


def _finish_sdk(ticket, state, staged):
    from tools.benchmark.prepare_calibration_capture_v4 import _authorize

    actual = _authorize(ticket)
    _state(ticket, actual)
    if not _typed_equal(actual, state):
        raise ValueError("SDK terminal admission changed")
    if staged.get("study") != str(FOLDER / "study.json") or staged.get("sha256") != digest(FOLDER / "study.json"):
        raise ValueError("staged study bytes differ")
    prep = read_declaration(FOLDER / "preparation.json")
    if prep.get("sdk_pid") != current_pid() or not _typed_equal(prep.get("sdk_ticket"), ticket):
        raise ValueError("SDK terminal preparation PID/reference differs")
    receipt = _sdk_receipt(ticket, staged["sha256"], current_pid())
    prepared = FOLDER / "sdk-complete.prepared.json"
    write_manifest(prepared, receipt)
    if not _typed_equal(read_declaration(prepared), receipt):
        raise ValueError("SDK terminal readback differs")
    result = dict(staged, declared_runtime_graph_frozen=True, sdk_terminal_sha256=digest(prepared))
    write_finished_transport(receipt)
    entry._publish_completion(prepared, FOLDER / "sdk-complete.json")
    return result


def write_finished_transport(receipt):
    """Copy only finished metadata/command files, never whole installed libraries."""
    selected = paths()
    selected["study"] = FOLDER / "study.json"
    output = FOLDER / "finished-artifacts"
    output.mkdir()
    rows = []
    for role, path in selected.items():
        before = file_record(path)
        member = role + ".bin"
        with Path(path).open("rb") as source, (output / member).open("xb") as target:
            count = 0
            sha = hashlib.sha256()
            while data := source.read(65536):
                count += len(data)
                sha.update(data)
                if count > before["bytes"] or target.write(data) != len(data):
                    raise ValueError("finished transport changed/short write")
        if count != before["bytes"] or sha.hexdigest() != before["sha256"] or not _typed_equal(before, file_record(path)):
            raise ValueError("finished metadata transport source mutation")
        rows.append(dict(role=role, source=before, member=member))
    data = entry._bytes(receipt)
    with (output / "sdk_terminal.bin").open("xb") as stream:
        if stream.write(data) != len(data):
            raise OSError("short finished terminal transport")
    write_manifest(
        FOLDER / "finished-artifact-index.json",
        dict(schema="finished-static-artifacts-v4", files=rows, sdk_terminal_sha256=hashlib.sha256(data).hexdigest()),
    )


def verify_finished_transport(path, sha, *, require_absent=True):
    # Task4 implements receipt/current-source/child-exit revalidation. Missing
    # implementation fails closed; no caller-provided truthy identity record.
    import sys

    gate = sys.modules.get("tools.benchmark.static_v4_identity")
    expected = str(ROOT / "tools/benchmark/static_v4_identity.py").replace("\\", "/")
    if gate is None or getattr(gate, "__file__", "").replace("\\", "/") != expected:
        raise ValueError("Task4 finished pre/post identity receiver unavailable")
    validate = getattr(gate, "revalidate_finished_study", None)
    if not callable(validate):
        raise ValueError("actual finished receipt validation unavailable")
    identity = validate(str(path), sha, require_absent=require_absent)
    return audit_finished_transport(identity, sha)


def audit_finished_transport(identity, sha):
    if (
        type(identity) is not dict
        or set(identity) != {"schema", "files", "study_sha256", "index_sha256", "sdk_exit", "source_root"}
        or identity["schema"] != "validated-static-prepost-receipts-v4"
        or identity["sdk_exit"] != 0
        or identity["study_sha256"] != sha
        or identity["index_sha256"] != digest(FOLDER / "finished-artifact-index.json")
    ):
        raise ValueError("finished pre/post/exit receipt joins differ")
    native = {r["requested"]: r for r in identity["files"]}
    if len(native) != len(identity["files"]):
        raise ValueError("duplicate finished native pin")
    index = read_declaration(FOLDER / "finished-artifact-index.json")
    if set(index) != {"schema", "files", "sdk_terminal_sha256"} or index["schema"] != "finished-static-artifacts-v4":
        raise ValueError("finished index schema differs")
    rows = {r["role"]: r for r in index["files"]}
    values = {}
    if len(rows) != len(index["files"]):
        raise ValueError("finished role duplicate")
    for role, row in rows.items():
        if row.get("member") != role + ".bin" or "/" in role or "\\" in role or ":" in role:
            raise ValueError("finished member escape")
        source = row["source"]
        entry._validate_pin(source)
        if not _typed_equal(source, native.get(source["requested"])):
            raise ValueError("finished source absent/different receipt pin")
        local = FOLDER / "finished-artifacts" / row["member"]
        data = local.read_bytes()
        if len(data) != source["bytes"] or hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("finished local artifact bytes differ")
        values[role] = data
    terminal = (FOLDER / "finished-artifacts/sdk_terminal.bin").read_bytes()
    return audit_finished_records(
        identity, sha, index, values, terminal, artifact_reader(FOLDER / "sdk/entry-evidence/transport.json")
    )


def native_registry(source_root, python):
    """Literal native role paths, independent of the reviewing host's Path."""
    from pathlib import PurePosixPath as P

    entry._strict(source_root)
    entry._strict(python)
    root = P(source_root)
    folder = root / "results/target-bearing-runtime-freeze-v4-dev-1701/frozen-study-v4"
    code = {
        "collector": "capture_disarmed_sensors.py",
        "scope": "calibration_capture_scope.py",
        "dispatcher": "run_calibration_capture.py",
        "study_code": "calibration_capture_study_v4.py",
        "producer_code": "prepare_calibration_capture_v4.py",
        "pipeline_code": "calibration_capture_pipeline_v4.py",
        "dependency_code": "native_entry_context_v4.py",
        "paths_code": "native_loader_paths_v4.py",
    }
    result = {role: str(root / "tools/benchmark" / name) for role, name in code.items()}
    result.update(
        {
            role: str(folder / name)
            for role, name in dict(
                binding="runtime-binding-v4.json",
                execution="execution-contract.json",
                wire="wire-config.json",
                agent="agent-runtime.json",
                preparation="preparation.json",
                entry_bill="sdk/entry-dependencies/entry-bill.json",
            ).items()
        }
    )
    result.update({name: str(folder / "sdk/entry-evidence" / (name + ".json")) for name in EVIDENCE_ROLES})
    scene = root / "results/target-bearing-scene-production-dev-1701/actual-scene-v3"
    result.update(
        scene_manifest=str(scene / "manifest.json"),
        scene_load=str(scene / "scene-load.json"),
        python=python,
        logger_topics=str(root / "config/px4/source-diagnostic-v1/logger_topics.txt"),
        logger_profile=str(root / "config/px4/source-diagnostic-v1/profile.json"),
    )
    return result


class FinishedRecordProvider:
    """Offline reconstruction from retained bytes and native receipt pins only."""

    def __init__(self, binding, values, rows, native):
        self.binding, self.values, self.rows, self.native = binding, values, rows, native

    def input_path(self, path):
        return str(path)

    def file_identity(self, role):
        row = self.rows[role]["source"]
        return dict(path=row["requested"], resolved=row["resolved"], bytes=row["bytes"], sha256=row["sha256"])

    def wire_configuration_record(self, path):
        from tools.benchmark.capture_contract import validate_wire_configuration

        value = json.loads(self.values["wire"])
        validate_wire_configuration(value)
        return dict(self.file_identity("wire"), configuration=value)

    def agent_runtime_record(self, path):
        from pathlib import PurePosixPath as P

        from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256

        value = json.loads(self.values["agent"])
        if (
            set(value) != {"schema", "bundle", "binary", "lib_dir", "port"}
            or value["schema"] != "capture-agent-runtime-v1"
            or type(value["port"]) is not int
            or value["port"] != 18888
        ):
            raise ValueError("retained Agent configuration invalid")
        for name in ("bundle", "binary", "lib_dir"):
            entry._strict(value[name])
        required = {
            value["bundle"]: BUNDLE_SHA256,
            value["binary"]: AGENT_SHA256,
            **{str(P(value["lib_dir"]) / n): v for n, v in sorted(LIBRARY_SHA256.items())},
        }
        records = []
        for path, sha in required.items():
            pin = self.native.get(path, {})
            if pin.get("sha256") != sha:
                raise ValueError("retained Agent fixed file differs")
            records.append(
                dict(
                    path=path,
                    resolved=pin["resolved"],
                    bytes=pin["bytes"],
                    sha256=pin["sha256"],
                    device=pin["identity"]["device"],
                    inode=pin["identity"]["inode"],
                )
            )
        return dict(
            schema="capture-agent-runtime-record-v1",
            declaration=self.rows["agent"]["source"]["requested"],
            declaration_sha256=hashlib.sha256(self.values["agent"]).hexdigest(),
            configuration=value,
            selected_paths=[self.rows["agent"]["source"]["requested"], *required],
            files=records,
            authority=False,
            typed_dds_provenance=False,
            fusion_qualified=False,
        )

    def logger_profile_record(self):
        from tools.connectome.audit_px4_logger_diagnostic import profile

        topics = self.values["logger_topics"]
        declaration = self.values["logger_profile"]
        if not profile.audit_profile(topics, json.loads(declaration)).logger_file_candidate:
            raise ValueError("retained logger profile refused")
        return dict(
            schema="capture-px4-logger-profile-v1",
            profile_id="source-diagnostic-v1",
            source_paths=[self.rows[r]["source"]["requested"] for r in ("logger_topics", "logger_profile")],
            topics_sha256=hashlib.sha256(topics).hexdigest(),
            declaration_sha256=hashlib.sha256(declaration).hexdigest(),
            px4_environment_override={"PX4_PARAM_SDLOG_PROFILE": "0"},
            diagnostic_only=True,
            runtime_topic_selection_verified=False,
            dds_ulog_parity_verified=False,
            source_authenticated=False,
        )

    def raw_graph(self, args):
        from tools.benchmark.calibration_capture_contract import raw_graph_records

        source = self.binding["calibration_scene"]
        if source["path"] != str(args.calibration_scene):
            raise ValueError("finished source scene literal path differs")
        return raw_graph_records(args, source, dict(source, path=str(args.output)))

    def declared_context(self):
        context = json.loads(self.values["context"])
        table = json.loads(self.values["table"])
        return dict(
            schema="bound-python-extension-context-v4",
            file=self.rows["context"]["source"],
            context_sha256=entry.context_digest(context),
            loader_selected_paths_sha256=hashlib.sha256(self.values["table"]).hexdigest(),
            loader_selected_paths_semantic_sha256=entry.context_digest(table),
            evidence={name: self.rows[name]["source"]["requested"] for name in EVIDENCE_ROLES},
        )


def expected_finished_execution(source_root, binding, values, rows, native):
    from pathlib import PurePosixPath as P

    from tools.benchmark.capture_contract import derive_launch_environment

    # Parse only inert ordinary defaults, then assign native paths explicitly.
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    folder = P(source_root) / "results/target-bearing-runtime-freeze-v4-dev-1701/frozen-study-v4"
    args = parse_capture_args(["--output", "inert-parse-only"])
    args.output = folder / "capture-input-v1"
    args.capture_profile = "target-bearing-raw-v1"
    args.calibration_scene = P(source_root) / "results/target-bearing-scene-production-dev-1701/actual-scene-v3"
    args.prepared_scene = True
    args.execution_contract = folder / "execution-contract.json"
    args.runtime_binding = folder / "runtime-binding-v4.json"
    args.wire_config = folder / "wire-config.json"
    args.agent_runtime_config = folder / "agent-runtime.json"
    args.logger_diagnostic_profile = "source-diagnostic-v1"
    args.record_owned_ulog = True
    args.record_depth_payload = True
    args.simulation_seed = 1701
    args.motion_profile = "target-bearing-multiaxis-v1"
    args.physics_trace_profile = "substep-calibration-v1"
    return execution_contract(
        args, derive_launch_environment(binding), record_provider=FinishedRecordProvider(binding, values, rows, native)
    )


def audit_finished_records(identity, sha, index, values, terminal, reader):
    """Pure retained-record joins; caller authorization stays in Task4 receiver."""
    from pathlib import PurePosixPath

    from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256
    from tools.benchmark.audit_live_wire_resources import audit_resource_graph_records
    from tools.benchmark.calibration_capture_contract import SCENE_MANIFEST_SHA

    native = {r["requested"]: r for r in identity["files"]}
    for r in native.values():
        entry._validate_pin(r)
    rows = {r["role"]: r for r in index["files"]}
    study = json.loads(values["study"])
    binding = json.loads(values["binding"])
    execution = json.loads(values["execution"])
    preparation = json.loads(values["preparation"])
    if (
        hashlib.sha256(values["study"]).hexdigest() != sha
        or study.get("schema") != "target-bearing-frozen-raw-study-v4"
        or not _typed_equal(study.get("qualification"), QUALIFICATION)
    ):
        raise ValueError("finished study schema/sha/qualification differs")
    if set(rows) != set(study["files"]) | {"study"}:
        raise ValueError("finished role set differs")
    for role, record in study["files"].items():
        if not _typed_equal(record, rows[role]["source"]):
            raise ValueError("finished study/source role join differs")
    for record in binding["baseline"]["files"] + preparation["pre"]["files"]:
        pin = {k: v for k, v in record.items() if k != "role"}
        if not _typed_equal(pin, native.get(pin["requested"])):
            raise ValueError("baseline absent/different native pre/post receipt")
    if (
        preparation["binding_sha256"] != hashlib.sha256(values["binding"]).hexdigest()
        or preparation["execution_sha256"] != hashlib.sha256(values["execution"]).hexdigest()
    ):
        raise ValueError("finished preparation/binding/execution bytes differ")
    if (
        preparation["schema"] != "raw-static-sdk-preparation-v4"
        or preparation["entry_bill_sha256"] != hashlib.sha256(values["entry_bill"]).hexdigest()
    ):
        raise ValueError("finished bill/preparation differs")
    context = json.loads(values["context"])
    bill = json.loads(values["entry_bill"])
    table = json.loads(values["table"])
    baseline = json.loads(values["baseline"])
    if preparation.get("sdk_pid") != context["pid"]:
        raise ValueError("finished preparation/context SDK PID differs")
    fixed = native_registry(identity["source_root"], context["interpreter"]["requested"])
    if set(rows) != set(fixed) | {"study"} or set(study["files"]) != set(fixed):
        raise ValueError("finished literal registry role set differs")
    folder = PurePosixPath(identity["source_root"]) / "results/target-bearing-runtime-freeze-v4-dev-1701/frozen-study-v4"
    for role, path in dict(fixed, study=str(folder / "study.json")).items():
        if rows[role]["source"]["requested"] != path:
            raise ValueError("finished literal registry path differs")
    observer = native.get(fixed["dependency_code"], {})
    observer_rows = [r for r in binding["baseline"]["files"] if r["requested"] == fixed["dependency_code"]]
    if (
        len(observer_rows) != 1
        or observer_rows[0].get("role") != "runtime:project-source"
        or not _typed_equal({k: v for k, v in observer_rows[0].items() if k != "role"}, observer)
    ):
        raise ValueError("independent descriptor observer provenance source pin differs")
    audit_independent_baseline(baseline, bill, context, observer)
    canonical_membership(binding, bill)
    entry.audit_entry_context_bill_v4(bill, baseline_files=baseline["files"], python_context=context, artifact_reader=reader)
    expected_table = dict(
        schema="loader-selected-path-table-v4",
        paths=bill["selected_paths"],
        context_sha256=entry.context_digest(context),
        baseline_sha256=hashlib.sha256(values["baseline"]).hexdigest(),
        bill_sha256=hashlib.sha256(values["entry_bill"]).hexdigest(),
        transport_sha256=hashlib.sha256(values["transport"]).hexdigest(),
    )
    if not _typed_equal(table, expected_table):
        raise ValueError("finished context/table/baseline joins differ")
    workload = (
        execution["wall_budget_s"],
        execution["supervisor_s"],
        execution["simulation_duration_ns"],
        execution["physics_step_ns"],
        execution["imu_hz"],
        execution["rgbd_hz"],
        execution["rgbd_size"],
        execution["estimator_run"],
    )
    if workload != (300, 300, 25000000000, 1000000, 250, 10, [160, 120], False):
        raise ValueError("finished workload changed")
    if (
        binding.get("schema") != "capture-resource-binding-v4"
        or binding.get("capture_profile") != "target-bearing-raw-v1"
        or execution.get("profiles")
        != {
            "motion_profile": "target-bearing-multiaxis-v1",
            "physics_trace_profile": "substep-calibration-v1",
            "reference_fault_profile": None,
            "source_fanout_profile": None,
        }
        or any(execution.get("inputs", {}).get(k) for k in ("shadow_binary", "shadow_config", "reference_module"))
        or execution.get("reference_sha256") is not None
        or execution.get("simulation_seed") != 1701
    ):
        raise ValueError("finished raw-only profile changed")
    if hashlib.sha256(values["scene_manifest"]).hexdigest() != SCENE_MANIFEST_SHA:
        raise ValueError("source scene manifest bytes differ")
    manifest = json.loads(values["scene_manifest"])
    scene = binding["calibration_scene"]
    source_load = json.loads(values["scene_load"])
    expected_files = dict(
        manifest["files"], **{"manifest.json": dict(bytes=len(values["scene_manifest"]), sha256=SCENE_MANIFEST_SHA)}
    )
    if (
        scene["files"] != expected_files
        or scene["geometry"] != source_load["geometry"]
        or scene["design"] != source_load["design"]
        or scene["qualification"] != source_load["qualification"]
        or scene["manifest_sha256"] != SCENE_MANIFEST_SHA
    ):
        raise ValueError("source scene metadata/manifest differs")
    raw = execution["raw_measurement"]
    prepared = raw["prepared_input"]
    if raw["scene"] != scene or {k: v for k, v in prepared.items() if k != "path"} != {
        k: v for k, v in scene.items() if k != "path"
    }:
        raise ValueError("finished scene/prepared handoff differs")
    for name, record in expected_files.items():
        for prefix in (scene["path"], prepared["path"]):
            actual = native.get(str(PurePosixPath(prefix) / name), {})
            if actual.get("bytes") != record["bytes"] or actual.get("sha256") != record["sha256"]:
                raise ValueError("source/prepared scene native pins missing/different")
    agent = json.loads(values["agent"])
    wire = json.loads(values["wire"])
    selected = execution["agent"]
    if (
        agent.get("schema") != "capture-agent-runtime-v1"
        or agent.get("port") != 18888
        or selected["configuration"] != agent
        or selected["declaration_sha256"] != hashlib.sha256(values["agent"]).hexdigest()
        or execution["wire"]["configuration"] != wire
        or execution["wire"]["sha256"] != hashlib.sha256(values["wire"]).hexdigest()
        or wire.get("schema") != "capture-wire-startup-v2"
    ):
        raise ValueError("owned Agent/wire execution bytes differ")
    required_agent = {
        agent["bundle"]: BUNDLE_SHA256,
        agent["binary"]: AGENT_SHA256,
        **{str(PurePosixPath(agent["lib_dir"]) / n): v for n, v in LIBRARY_SHA256.items()},
    }
    if set(selected["selected_paths"]) != {selected["declaration"], *required_agent}:
        raise ValueError("Agent complete selected membership differs")
    for path, expected in required_agent.items():
        if native.get(path, {}).get("sha256") != expected:
            raise ValueError("Agent immutable cache/bundle native pin differs")
    expected_agent = [
        p
        for p in selected["selected_paths"]
        if p == agent["binary"] or PurePosixPath(p).parent == PurePosixPath(agent["lib_dir"])
    ]
    if bill["agent_paths"] != expected_agent or bill["agent_lib"] != agent["lib_dir"]:
        raise ValueError("Agent loader subset differs")
    context_ref = execution["python_extension_context"]
    if (
        context_ref["schema"] != "bound-python-extension-context-v4"
        or context_ref["file"] != rows["context"]["source"]
        or context_ref["context_sha256"] != entry.context_digest(context)
        or context_ref["loader_selected_paths_sha256"] != hashlib.sha256(values["table"]).hexdigest()
        or context_ref["loader_selected_paths_semantic_sha256"] != entry.context_digest(table)
    ):
        raise ValueError("finished execution/context/path handoff differs")
    audited = audit_resource_graph_records(
        declaration=binding,
        pre=preparation["pre"],
        after_queries=preparation["after_queries"],
        graph=preparation["graph"],
        context=preparation["context"],
        queries=preparation["queries"],
        documents={p: bytes.fromhex(b) for p, b in preparation["documents_hex"].items()},
        path_factory=PurePosixPath,
    )
    if not _typed_equal(audited, preparation["audit"]):
        raise ValueError("finished original-byte graph audit differs")
    expected_execution = expected_finished_execution(identity["source_root"], binding, values, rows, native)
    if not _typed_equal(execution, expected_execution):
        raise ValueError("finished exact execution contract differs")
    if hashlib.sha256(terminal).hexdigest() != index["sdk_terminal_sha256"]:
        raise ValueError("finished SDK terminal bytes differ")
    receipt = json.loads(terminal)
    if (
        receipt.get("study_sha256") != sha
        or receipt.get("sdk_pid") != preparation["sdk_pid"]
        or receipt.get("ticket_sha256") != entry.context_digest(preparation["sdk_ticket"])
        or receipt.get("preparation_sha256") != hashlib.sha256(values["preparation"]).hexdigest()
    ):
        raise ValueError("finished SDK terminal PID/reference differs")
    return dict(
        study_sha256=sha,
        files=study["files"],
        baseline_files=binding["baseline"]["files"],
        graph_audit=audited,
        qualification=QUALIFICATION,
        physical_admitted=False,
        transported_finished_metadata=True,
        current_sdk_executed=False,
    )


def publish(ticket, state=None):
    from tools.benchmark.calibration_capture_study_v4 import _authorize

    actual = _authorize(ticket)
    _state(ticket, actual)
    if state is not None and not _typed_equal(actual, state):
        raise ValueError("publication admission changed")
    preparation = read_declaration(FOLDER / "preparation.json")
    if preparation.get("sdk_pid") != current_pid() or not _typed_equal(preparation.get("sdk_ticket"), ticket):
        raise ValueError("publication requires original same SDK PID/nonce/ticket")
    document = dict(
        schema="target-bearing-frozen-raw-study-v4",
        files={role: file_record(p) for role, p in paths().items()},
        qualification=QUALIFICATION,
    )
    target = FOLDER / "study.json"
    write_manifest(target, document)
    sha = digest(target)
    checked = _verify_contents(target, sha)
    write_manifest(FOLDER / "freeze-verification.json", checked)
    return dict(
        study=str(target), sha256=sha, declared_runtime_graph_frozen=False, physical_admitted=False, qualification=QUALIFICATION
    )


BASE_ENV = dict(entry.ENV)
CATALOG = ROOT / "results/declared-launch-environment-dev-1701/dry-v1/runtime-binding-v3.json"
AGENT = ROOT / "results/agent-capture-contract-dev-1701/agent-runtime.json"
V1_FOLDER = ROOT / "results/target-bearing-runtime-freeze-dev-1701/frozen-study-v1"
RENDERER = "/usr/lib/x86_64-linux-gnu/gz-rendering-8/engine-plugins/libgz-rendering8-ogre2.so.8.2.3"


def _run_tool(argv, env):
    row = entry._run(argv, env, str(ROOT))
    return dict(row, exit=row["returncode"], output_limit_exceeded=row["output_limited"])


def select_entries(catalog, plugins, native, agent_paths, resolver):
    entries = {}
    seen = set()

    def add(role, paths):
        selected = [str(p) for p in paths if str(p) not in seen]
        seen.update(selected)
        if selected:
            entries[role] = list(dict.fromkeys(selected))

    for role, paths in catalog["inventory"].items():
        if (
            role.startswith("runtime-root:")
            and not role.startswith("runtime-root:python")
            and role not in {"runtime-root:openvins", "runtime-root:native-reference"}
        ):
            add(role, paths)
    add("renderer", [RENDERER])
    add("selected-world-model-plugins", plugins)
    add("current-python-native", native)
    add("resolver", [resolver])
    add("agent", agent_paths)
    candidates = list(dict.fromkeys(catalog["inventory"].get("runtime:dependencies", [])))
    return entries, candidates


def reuse_agent_cache(configuration, deployment):
    from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256

    expected = {"bin/MicroXRCEAgent": AGENT_SHA256, **{"lib/" + name: sha for name, sha in LIBRARY_SHA256.items()}}
    binary, lib = Path(configuration["binary"]), Path(configuration["lib_dir"])
    if (
        configuration["schema"] != "capture-agent-runtime-v1"
        or configuration["port"] != 18888
        or binary.parent != lib.parent / "bin"
    ):
        raise ValueError("Agent cache configuration changed")
    if {p.name for p in lib.iterdir()} != set(LIBRARY_SHA256):
        raise ValueError("Agent cache directory member set changed")
    members = {r["member"]: r["deployed"] for r in deployment["members"]}
    if len(members) != len(deployment["members"]) or set(members) != set(expected):
        raise ValueError("Agent cache member set changed")
    rows = []
    for name, sha in expected.items():
        path = binary if name == "bin/MicroXRCEAgent" else lib / name.removeprefix("lib/")
        row = file_record(path)
        if row["sha256"] != sha or not _typed_equal(row, members[name]):
            raise ValueError("Agent cache pinned file changed")
        rows.append(row)
    bundle = file_record(configuration["bundle"])
    if bundle["sha256"] != BUNDLE_SHA256 or not _typed_equal(bundle, deployment["bundle"]):
        raise ValueError("Agent cache original bundle changed")
    return dict(files=rows, bundle=bundle, extracted=False, executed=False, transitive_license_certified=False)


def timed(operation, output, metadata):
    started = time.monotonic_ns()
    record = dict(
        metadata=metadata, start_monotonic_ns=started, start_utc=datetime.datetime.now(datetime.UTC).isoformat(), error=None
    )
    primary = None
    try:
        return operation()
    except BaseException as exc:
        primary = exc
        record["error"] = repr(exc)
        raise
    finally:
        raw = metadata.get("raw_query_path")
        hash_error = None
        try:
            record["raw_query_sha256"] = (
                hashlib.sha256(Path(raw).read_bytes()).hexdigest() if raw and Path(raw).is_file() else None
            )
        except Exception as exc:
            hash_error = exc
            record.update(raw_query_sha256=None, raw_query_error=repr(exc))
            if primary is not None:
                primary.add_note("SDK raw-record identity failure: " + repr(exc))
            else:
                record["error"] = repr(exc)
        ended = time.monotonic_ns()
        record.update(end_monotonic_ns=ended, elapsed_ns=ended - started, end_utc=datetime.datetime.now(datetime.UTC).isoformat())
        try:
            write_manifest(output, record)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("paired-clock persistence failure: " + repr(exc))
        if primary is None and hash_error is not None:
            raise hash_error


class ClockedClient:
    def __init__(self, client, binary):
        self.client, self.binary, self.count = client, binary, 0

    def check_budget(self):
        return self.client.check_budget()

    def query(self, *args):
        number = getattr(self.client, "count", self.count)
        self.count += 1
        raw = self.client.output / f"resource-query-{number:04d}.json"
        clock = self.client.output / f"local-clock-{number:04d}.json"
        return timed(lambda: self.client.query(*args), clock, dict(argv=[str(self.binary), *args], raw_query_path=str(raw)))


def licenses(paths, output):
    selected = sorted({str(Path(p).resolve()) for p in paths if Path(p).is_file() and Path(p).suffix != ".py"})
    tool = file_record("/usr/bin/dpkg-query")
    argv = [tool["requested"], "-S", *selected]
    query = _run_tool(argv, dict(BASE_ENV))
    owner_row = dict(query, tool_before=tool, tool_after=None)
    primary = None
    if (
        query["error"] is not None
        or query["output_limit_exceeded"]
        or query["reader_complete"] is not True
        or type(query["exit"]) is not int
        or query["exit"] not in (0, 1)
    ):
        primary = ValueError("bounded installed license query failed: " + str(query["error"]))
    try:
        owner_row["tool_after"] = file_record(tool["requested"])
        if not _typed_equal(tool, owner_row["tool_after"]):
            raise ValueError("installed license tool changed")
    except Exception as exc:
        owner_row["postpin_error"] = repr(exc)
        if primary is None:
            primary = exc
        else:
            primary.add_note("installed license post-pin failure: " + repr(exc))
    try:
        write_manifest(output / "package-owner-query.json", owner_row)
    except Exception as exc:
        owner_row["persistence_error"] = repr(exc)
        if primary is None:
            primary = exc
        else:
            primary.add_note("installed license query persistence failure: " + repr(exc))
        try:
            write_manifest(output / "installed-license-query-failure.json", owner_row)
        except Exception as fallback:
            primary.add_note("installed license fallback persistence failure: " + repr(fallback))
    if primary is not None:
        raise primary
    owners = set()
    for line in bytes.fromhex(query["stdout_hex"]).decode(errors="strict").splitlines():
        if ": /" in line:
            owners.update(line.split(": /", 1)[0].split(", "))
    notices, packages, distributions = [Path(tool["requested"])], [], []
    record = dict(
        query=query,
        selected_owners=sorted(owners),
        package_notices=packages,
        python_distributions=distributions,
        partially_unowned=query["exit"] == 1,
        transitive_license_certified=False,
    )
    primary = None
    try:
        for owner in sorted(owners):
            notice = Path("/usr/share/doc") / owner.split(":", 1)[0] / "copyright"
            packages.append(dict(owner=owner, copyright=file_record(notice) if notice.is_file() else None))
            if notice.is_file():
                notices.append(notice)
        for package in ("numpy", "scipy", "pyulog", "pymavlink", "protobuf"):
            dist = importlib.metadata.distribution(package)
            files = [
                dist.locate_file(n) for n in dist.files or [] if "license" in str(n).lower() or "copyright" in str(n).lower()
            ]
            files = [p for p in files if p.is_file()]
            notices.extend(files)
            distributions.append(dict(package=package, version=dist.version, notices=[file_record(p) for p in files]))
    except Exception as exc:
        primary = exc
        record["error"] = repr(exc)
        raise
    finally:
        try:
            write_manifest(output / "installed-license-observations.json", record)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("license observation persistence failure: " + repr(exc))
    return notices


def required_plugins(scene, client):
    """Discover selected plugins before baseline; final graph queries recheck them."""
    from tools.benchmark.selected_resource_graph import references

    names = set()
    for path in sorted(Path(scene).rglob("*.sdf")):
        for reference in references(path.read_bytes(), "sdf"):
            if reference["kind"] == "plugin":
                names.add(reference["text"])
    return [client.query("plugin", name)["selected"] for name in sorted(names)]


def scope_before(unit, output):
    from tools.benchmark.calibration_capture_scope import manager_environment

    lines = [line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::")]
    if len(lines) != 1:
        raise ValueError("static preparation cgroup unknown")
    group = lines[0]
    cg = Path("/sys/fs/cgroup" + group)
    limits = {name: (cg / name).read_text().strip() for name in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")}
    props = subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=InvocationID", "--property=ControlGroup"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        env=manager_environment(),
    )
    identities = dict(line.split("=", 1) for line in props.stdout.splitlines() if "=" in line)
    record = dict(pid=os.getpid(), cgroup=group, limits=limits, systemd_properties=props.stdout, qualification=False)
    write_manifest(output / "sdk-inside-before.json", record)
    if (
        re.fullmatch(r"fly-calibration-prepare-[0-9a-f]{24}\.scope", unit) is None
        or not group.endswith("/" + unit)
        or identities.get("ControlGroup") != group
        or not identities.get("InvocationID")
        or limits != {"memory.max": str(512 * 1024**2), "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "64"}
    ):
        raise ValueError("static preparation own scope/limits differ")
    return cg


def _prepare_sdk(ticket, state):
    unit = ticket["unit"]
    from tools.benchmark.prepare_calibration_capture_v4 import _authorize

    _state(ticket, _authorize(ticket))
    from tools.benchmark.bound_resource_graph import build_graph
    from tools.benchmark.calibration_capture_contract import copy_scene, scene_record
    from tools.benchmark.calibration_capture_study_v4 import audit_v4_preparation
    from tools.benchmark.native_resource_client import QUERY_ENV_KEYS, QueryClient
    from tools.benchmark.runtime_resource_binding import ENV_KEYS, validate_binding

    if FOLDER.exists():
        raise FileExistsError("one static raw preparation already exists; no replay")
    parent = FOLDER.parent
    started = time.monotonic_ns()
    start_utc = datetime.datetime.now(datetime.UTC).isoformat()
    cg = timed(lambda: scope_before(unit, parent), parent / "scope-local-clock.json", dict(operation="own-scope-before"))
    FOLDER.mkdir()
    primary = None
    try:
        source = scene_record(SOURCE)
        capture = FOLDER / "capture-input-v1"
        capture.mkdir()
        copy_scene(source, capture)
        wire = dict(
            schema="capture-wire-startup-v2",
            session_id="calibration-measurement-dev-1701",
            sim_origin_ns=0,
            remote_origin_ns=0,
            startup_max_wall_ns=60_000_000_000,
        )
        write_manifest(FOLDER / "wire-config.json", wire)
        old_agent = V1_FOLDER / "agent-runtime.json"
        old_deployment = V1_FOLDER / "agent-deployment.json"
        configuration = json.loads(old_agent.read_text(encoding="utf8"))
        reused = reuse_agent_cache(configuration, json.loads(old_deployment.read_text(encoding="utf8")))
        write_manifest(
            FOLDER / "agent-cache-reuse.json",
            dict(reused, source_configuration=file_record(old_agent), source_deployment=file_record(old_deployment)),
        )
        write_manifest(FOLDER / "agent-runtime.json", configuration)
        args = arguments(FOLDER)
        env = {key: None for key in set(ENV_KEYS) | set(QUERY_ENV_KEYS)}
        env.update(
            HOME="/home/yuchen7509",
            PATH="/usr/bin:/bin",
            LANG="C.UTF-8",
            GZ_SIM_RESOURCE_PATH=str(capture / "models"),
            GZ_SIM_SYSTEM_PLUGIN_PATH="",
            SDF_PATH="",
            GZ_FILE_PATH="",
            GZ_HOMEDIR=str(FOLDER / "gz-home"),
            MESA_SHADER_CACHE_DISABLE="true",
        )
        query_env = {key: env[key] for key in QUERY_ENV_KEYS}
        catalog = json.loads(CATALOG.read_text(encoding="utf8"))
        resolver = Path(catalog["inventory"]["graph:resolver"][0])
        pins = {row["role"]: row for row in catalog["baseline"]["files"] if row["role"] in ("graph:resolver", "graph:source")}
        for role, path in (("graph:resolver", resolver), ("graph:source", ROOT / "tools/benchmark/native/resource_resolver.cc")):
            if file_record(path)["sha256"] != pins[role]["sha256"]:
                raise ValueError("existing SDK resolver/source pin changed")
        sdk = FOLDER / "sdk"
        sdk.mkdir()
        client = ClockedClient(QueryClient(resolver, ROOT, query_env, sdk), resolver)
        context = client.query("context")
        installation = client.query("installation")
        write_manifest(sdk / "installed-context.json", context)
        write_manifest(sdk / "installed-directories.json", installation)
        contract = execution_contract(args, env)
        owned_inventory = InputInventory()
        inventory, add = owned_inventory.inventory, owned_inventory.add

        add("graph:resolver", [resolver])
        add(
            "graph:source",
            [
                ROOT / "tools/benchmark/native/resource_resolver.cc",
            ],
        )
        # A former catalog supplies only installed native root candidates. All
        # selected bytes/dependencies are freshly observed; no old native runs.
        native = [entry.tool_paths()["python"]]
        modules = []
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name and Path(name).is_file():
                modules.append(str(Path(name).resolve()))
                cached = getattr(module, "__cached__", None)
                if cached and Path(cached).is_file():
                    modules.append(str(Path(cached).resolve()))
                if Path(name).suffix == ".so":
                    native.append(str(Path(name).resolve()))
        for pattern in ("gz/**/*.so", "sdformat14*.so"):
            native.extend(str(p.resolve()) for p in Path("/usr/lib/python3/dist-packages").glob(pattern))
        native.extend(m["origin"]["requested"] for m in entry.collect_python_context()["modules"])
        entries, candidates = select_entries(
            catalog, required_plugins(capture, client), native, contract["agent"]["selected_paths"], str(resolver)
        )
        agent_configuration = contract["agent"]["configuration"]
        loader_paths = [
            p
            for p in contract["agent"]["selected_paths"]
            if p == agent_configuration["binary"] or Path(p).parent == Path(agent_configuration["lib_dir"])
        ]
        python_context = entry.collect_python_context()
        bill = entry.discover_entry_context_v4(
            entries, candidates, python_context, loader_paths, agent_configuration["lib_dir"], sdk / "entry-dependencies"
        )
        evidence = capture_entry_evidence(bill, python_context, sdk / "entry-evidence")
        add(
            "graph:dependencies",
            [r["file"]["resolved"] for r in bill["entries"]] + [r["canonical_path"] for r in bill["selected_paths"]],
        )
        for name, role in EVIDENCE_ROLES.items():
            add(role, [evidence["paths"][name]])
        add("runtime:entry-context-bill-v4", [sdk / "entry-dependencies/entry-bill.json"])
        add(
            "runtime:entry-context-source-artifacts-v4",
            sorted((sdk / "entry-dependencies").glob("query-*.json"))
            + [sdk / "entry-dependencies/entry-bill-terminal.json", sdk / "entry-dependencies/entry-bill-terminal.prepared.json"],
        )
        add("runtime:entry-context-transport-members-v4", sorted((sdk / "entry-evidence").glob("artifact-*.bin")))
        add("runtime:entry-dependency-files", [r["requested"] for r in bill["declared_before"]])
        add_loaded_code(add, modules)
        add("runtime:installed-notices", licenses([path for paths in inventory.values() for path in paths], sdk))
        add("runtime:classic-material", [installation["classic_material"]])
        add("runtime:resolver-headers", [ROOT / "tools/benchmark/native/local_candidates.hh"])
        add("runtime:source-scene", [SOURCE / name for name in source["files"]])
        add(
            "runtime:original-models",
            [ROOT / "assets/gazebo/models/x500_benchmark/model.sdf", ROOT / "assets/gazebo/models/OakD-Benchmark/model.sdf"],
        )
        # The collector explicitly requires these original source/profile files.
        add(
            "runtime:px4-selected",
            [
                Path("/home/yuchen7509/PX4-Autopilot") / name
                for name in (
                    "build/px4_sitl_default/rootfs/gz_env.sh",
                    "build/px4_sitl_default/etc/init.d-posix/rcS",
                    "src/modules/simulation/gz_bridge/server.config",
                    "Tools/simulation/gz/models/x500/model.sdf",
                    "Tools/simulation/gz/models/x500_base/model.sdf",
                    "LICENSE",
                )
            ],
        )
        add("runtime:logger", [Path(p) for p in contract["logger_diagnostic"]["source_paths"]])
        add(
            "runtime:configuration",
            [
                FOLDER / "wire-config.json",
                FOLDER / "agent-runtime.json",
                FOLDER / "agent-cache-reuse.json",
                old_agent,
                old_deployment,
                CATALOG,
                AGENT,
                sdk / "entry-dependencies/entry-bill.json",
            ],
        )
        gz_env = Path("/home/yuchen7509/PX4-Autopilot/build/px4_sitl_default/rootfs/gz_env.sh")
        generated = {name: row["sha256"] for name, row in source["files"].items()}
        generated["gz_env.sh"] = file_record(gz_env)["sha256"]
        binding = dict(
            schema="capture-resource-binding-v4",
            capture_profile="target-bearing-raw-v1",
            calibration_scene=source,
            inventory=inventory,
            baseline=snapshot(inventory),
            environment={key: env[key] for key in (*ENV_KEYS, "MESA_SHADER_CACHE_DISABLE")},
            generated=generated,
            graph=dict(schema="generated-resource-graph-v1", cwd=str(ROOT), environment=query_env, expected_context=context),
            runtime_maps=dict(
                self_phases=["postimports", "postfinalize", "postfirststep"],
                owned_roles={"px4": ["ready", "prestop"], "agent": ["ready", "prestop"]},
                max_maps_bytes=8 * 1024**2,
                max_observations=16,
            ),
        )
        validate_binding(binding)
        write_manifest(FOLDER / "runtime-binding-v4.json", binding)
        # The final contract now binds actual context bytes via the newly written
        # binding; the earlier contract supplied only Agent/logger selection.
        contract = execution_contract(args, env)
        write_manifest(FOLDER / "execution-contract.json", contract)
        proof_inventory = dict(inventory)
        for name in source["files"]:
            proof_inventory["generated:" + name] = [str(capture / name)]
        # The copied runtime gz_env bytes have their source record in baseline;
        # the actual runtime-generated path is separately rechecked by worker.
        pre = snapshot(proof_inventory)
        graph_client = ClockedClient(QueryClient(resolver, ROOT, query_env, FOLDER / "graph-queries"), resolver)
        (FOLDER / "graph-queries").mkdir()
        graph_context = graph_client.query("context")
        graph = build_graph(capture / "world.sdf", graph_client, pre["files"], FOLDER / "graph-queries")
        after = snapshot(proof_inventory)
        pre["resource_graph"] = graph
        preparation = dict(
            schema="raw-static-sdk-preparation-v4",
            python_context_file_sha256=digest(evidence["paths"]["context"]),
            python_context_sha256=entry.context_digest(python_context),
            entry_bill_sha256=hashlib.sha256((sdk / "entry-dependencies/entry-bill.json").read_bytes()).hexdigest(),
            binding_sha256=hashlib.sha256((FOLDER / "runtime-binding-v4.json").read_bytes()).hexdigest(),
            execution_sha256=hashlib.sha256((FOLDER / "execution-contract.json").read_bytes()).hexdigest(),
            pre=pre,
            after_queries=after,
            graph=graph,
            context=graph_context,
            queries=[json.loads(p.read_text()) for p in sorted((FOLDER / "graph-queries").glob("resource-query-*.json"))],
            documents_hex={row["source"]: Path(row["source"]).read_bytes().hex() for row in graph["documents"]},
            query_clocks=[json.loads(p.read_text()) for p in sorted((FOLDER / "graph-queries").glob("local-clock-*.json"))],
            audit=None,
            entry_evidence=audit_entry_evidence(evidence["paths"], bill, python_context),
            sdk_ticket=dict(ticket),
            sdk_pid=current_pid(),
        )
        from tools.benchmark.audit_live_wire_resources import audit_resource_graph_records

        preparation["audit"] = audit_resource_graph_records(
            declaration=binding,
            pre=pre,
            after_queries=after,
            graph=graph,
            context=graph_context,
            queries=preparation["queries"],
            documents={p: bytes.fromhex(data) for p, data in preparation["documents_hex"].items()},
        )
        audit_v4_preparation(binding, preparation, sdk / "entry-dependencies/entry-bill.json", bill)
        write_manifest(FOLDER / "preparation.json", preparation)
        result = publish_study_v4(ticket)
        write_manifest(parent / "native-freeze-result.json", result)
        return result
    except Exception as exc:
        primary = exc
        try:
            write_manifest(parent / "native-freeze-failure.json", dict(error=repr(exc), folder=str(FOLDER), qualification=False))
        except Exception as writer:
            exc.add_note("native failure persistence error: " + repr(writer))
        raise
    finally:
        ended = time.monotonic_ns()
        record = dict(
            cgroup=str(cg),
            error=repr(primary) if primary is not None else None,
            start_monotonic_ns=started,
            end_monotonic_ns=ended,
            elapsed_ns=ended - started,
            start_utc=start_utc,
            end_utc=datetime.datetime.now(datetime.UTC).isoformat(),
            qualification=False,
        )
        counter_error = None
        try:
            record.update(
                limits={
                    name: (cg / name).read_text().strip() for name in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")
                },
                memory_events=(cg / "memory.events").read_text(),
                memory_peak=(cg / "memory.peak").read_text() if (cg / "memory.peak").exists() else None,
            )
        except Exception as exc:
            counter_error = exc
            record["counter_error"] = repr(exc)
            if primary is not None:
                primary.add_note("scope final counter failure: " + repr(exc))
        try:
            write_manifest(parent / "sdk-inside-after.json", record)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("scope final persistence failure: " + repr(exc))
        if primary is None and counter_error is not None:
            raise counter_error


def audit_query_clocks(preparation):
    clocks, queries = preparation["query_clocks"], preparation["queries"]
    if type(clocks) is not list or type(queries) is not list or len(clocks) != len(queries):
        raise ValueError("SDK paired-clock membership differs")
    previous_end = None
    for number, (clock, query) in enumerate(zip(clocks, queries, strict=True)):
        raw = FOLDER / "graph-queries" / f"resource-query-{number:04d}.json"
        start, end, elapsed = (clock[k] for k in ("start_monotonic_ns", "end_monotonic_ns", "elapsed_ns"))
        if any(type(v) is not int or v < 0 for v in (start, end, elapsed)) or end - start != elapsed or end < start:
            raise ValueError("SDK paired-clock local interval invalid")
        if previous_end is not None and start < previous_end:
            raise ValueError("SDK paired-clock query order invalid")
        previous_end = end
        inner_start, inner_end = (query[k] for k in ("started_monotonic", "ended_monotonic"))
        if (
            any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (inner_start, inner_end))
            or inner_end < inner_start
        ):
            raise ValueError("SDK paired-clock raw local interval invalid")
        # QueryClient records this same host's seconds as float, the wrapper as
        # integer nanoseconds. One microsecond only covers representation rounding.
        # It is not a sensor-clock tolerance or a cross-host clock comparison.
        if inner_start * 1_000_000_000 < start - 1000 or inner_end * 1_000_000_000 > end + 1000:
            raise ValueError("SDK paired-clock raw local interval outside wrapper")
        if clock["error"] is not None or "raw_query_error" in clock:
            raise ValueError("SDK paired-clock observation incomplete")
        for name in ("start_utc", "end_utc"):
            if type(clock[name]) is not str or datetime.datetime.fromisoformat(clock[name]).utcoffset() != datetime.timedelta(0):
                raise ValueError("SDK paired-clock UTC fact invalid")
        if (
            clock["metadata"] != dict(argv=query["command"], raw_query_path=str(raw))
            or clock["raw_query_sha256"] != hashlib.sha256(raw.read_bytes()).hexdigest()
            or not _typed_equal(read_declaration(raw), query)
        ):
            raise ValueError("SDK paired-clock raw command/file join differs")
