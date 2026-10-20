"""Literal v3 entry-bound raw study; never grants source/calibration/flight authority."""

from __future__ import annotations

import datetime
import hashlib
import math
from pathlib import Path

from tools.benchmark import calibration_capture_study as shared
from tools.benchmark.agent_capture_runtime import agent_runtime_record
from tools.benchmark.capture_contract import _typed_equal, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, write_manifest
from tools.benchmark.native_entry_context_v3 import audit_entry_context_bill, context_digest, declared_python_context

ROOT = shared.ROOT
FOLDER = ROOT / "results/target-bearing-runtime-freeze-v3-dev-1701/frozen-study-v3"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paths():
    selected = shared.study_paths(FOLDER)
    selected.update(
        study_code=Path(__file__),
        dependency_code=ROOT / "tools/benchmark/native_entry_context_v3.py",
        producer_code=ROOT / "tools/benchmark/prepare_calibration_capture_v3.py",
        entry_bill=FOLDER / "sdk/entry-dependencies/entry-bill.json",
        python_context=FOLDER / "sdk/python-context.json",
    )
    return selected


def audit_v3_preparation(binding, preparation, bill_path, bill):
    if not _typed_equal(read_declaration(bill_path), bill):
        raise ValueError("actual entry bill bytes differ from supplied bill")
    context_record = declared_python_context(binding)
    if context_record is None:
        raise ValueError("v3 preparation requires declared Python context")
    context = read_declaration(context_record["file"]["requested"])
    if preparation.get("python_context_file_sha256") != context_record["file"]["sha256"] or preparation.get(
        "python_context_sha256"
    ) != context_digest(context):
        raise ValueError("preparation Python context digest differs")
    if (
        preparation.get("schema") != "raw-static-sdk-preparation-v3"
        or preparation.get("entry_bill_sha256") != hashlib.sha256(Path(bill_path).read_bytes()).hexdigest()
    ):
        raise ValueError("actual entry bill digest/schema differs from v3 preparation")
    record = file_record(bill_path)
    selected = [
        {k: v for k, v in row.items() if k != "role"}
        for row in binding["baseline"]["files"]
        if row.get("requested") == record["requested"] and row.get("role") == "runtime:entry-context-bill"
    ]
    if len(selected) != 1 or not _typed_equal(selected[0], record):
        raise ValueError("entry bill absent/different runtime baseline")
    projected = {
        k: v
        for k, v in preparation.items()
        if k not in {"entry_bill_sha256", "query_clocks", "python_context_file_sha256", "python_context_sha256"}
    }
    projected["schema"] = "raw-static-sdk-preparation-v1"
    graph = shared.audit_preparation_at(binding, projected, FOLDER)
    audit_query_clocks(preparation)
    agent = agent_runtime_record(FOLDER / "agent-runtime.json")
    config = agent["configuration"]
    expected = [p for p in agent["selected_paths"] if p == config["binary"] or Path(p).parent == Path(config["lib_dir"])]
    if bill.get("agent_paths") != expected or bill.get("agent_lib") != config["lib_dir"]:
        raise ValueError("entry bill Agent loader context differs from bound execution")
    required = {p for entry in bill["entries"] for p in [entry["file"]["requested"], *entry["selected"]]}
    # The resolver root has its mandatory unique graph:resolver role. Binding
    # inventories prohibit assigning any one path to two roles.
    required -= set(binding["inventory"].get("graph:resolver", []))
    if not required.issubset(set(binding["inventory"].get("graph:dependencies", []))):
        raise ValueError("entry self/dependency membership missing from graph dependencies")
    baseline = {r["requested"]: {k: v for k, v in r.items() if k != "role"} for r in binding["baseline"]["files"]}
    for number, query in enumerate(bill["queries"], 1):
        path = Path(bill_path).parent / f"query-{number:04d}.json"
        if (
            str(path) not in binding["inventory"].get("runtime:entry-context-artifacts", [])
            or not _typed_equal(file_record(path), baseline.get(str(path)))
            or not _typed_equal(read_declaration(path), query)
        ):
            raise ValueError("entry query artifact baseline/raw join differs")
    return dict(graph, **audit_entry_context_bill(bill, baseline_files=binding["baseline"]["files"], python_context=context))


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


def verify_study_v3(path, sha, *, require_absent=True):
    if Path(path).absolute() != FOLDER / "study.json":
        raise ValueError("fixed v3 raw study path mismatch")
    return shared._verify_profile_study(
        path, sha, FOLDER, "target-bearing-frozen-raw-study-v3", paths(), require_absent=require_absent, v3=True
    )


def publish_study_v3():
    document = dict(
        schema="target-bearing-frozen-raw-study-v3",
        files={role: file_record(path) for role, path in paths().items()},
        qualification=dict(shared.QUALIFICATION),
    )
    target = FOLDER / "study.json"
    write_manifest(target, document)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    checked = verify_study_v3(target, sha)
    write_manifest(FOLDER / "freeze-verification.json", checked)
    return dict(
        study=str(target),
        sha256=sha,
        declared_runtime_graph_frozen=True,
        physical_admitted=False,
        qualification=dict(shared.QUALIFICATION),
    )
