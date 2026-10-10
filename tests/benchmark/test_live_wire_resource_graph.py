"""Synthetic raw query/graph joins, not actual SDK execution evidence."""

import copy
import hashlib
import json

import pytest

from tools.benchmark import audit_live_wire_resources as audit
from tools.benchmark.native_resource_client import LOOKUP_KEYS, QUERY_ENV_KEYS


def fixture(tmp_path):
    world, plugin, resolver = [str(tmp_path / name) for name in ("world.sdf", "driver.so", "resolver")]
    raw = b'<sdf><world><plugin filename="driver" name="example"/></world></sdf>'
    env = dict.fromkeys(QUERY_ENV_KEYS)
    context = dict(
        cwd=str(tmp_path),
        sdf_share_path=str(tmp_path),
        sdf_version="14.9",
        common_callback_observation="unavailable: SDK has no callback inspection API",
        file_paths=[],
        plugin_paths=[str(tmp_path)],
        sdf_callback_present=False,
        search_context_qualified=False,
        runtime_closure_qualified=False,
        common_file_callbacks_present=None,
        common_uri_callbacks_present=None,
        sdf_uri_paths={},
        before_environment=dict.fromkeys(LOOKUP_KEYS),
        after_environment=dict.fromkeys(LOOKUP_KEYS),
    )
    reply = dict(
        ok=True,
        error="",
        selected=plugin,
        normalized="driver",
        paths=[str(tmp_path)],
        candidates=[plugin],
        examined_paths=[plugin],
        candidate_profile="common-442a7ab-spellings",
        runtime_closure_qualified=False,
    )
    queries = []
    for i, (args, answer) in enumerate([(["context"], context), (["plugin", "driver"], reply)]):
        output = json.dumps(answer)
        queries.append(
            dict(
                command=[resolver, *args],
                cwd=str(tmp_path),
                environment=env,
                started_monotonic=1.0 + i,
                ended_monotonic=1.1 + i,
                stdout=output,
                stdout_hex=output.encode().hex(),
                stderr="",
                stderr_hex="",
                returncode=0,
                error=None,
                output_limit_exceeded=False,
                collection_errors=[],
            )
        )
    files = [
        dict(role=role, requested=path, resolved=path, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        for role, path, data in [
            ("generated:world.sdf", world, raw),
            ("plugin", plugin, b"plugin"),
            ("graph:resolver", resolver, b"resolver"),
        ]
    ]
    graph = dict(
        schema="bound-local-resource-graph-v1",
        documents=[dict(source=world, canonical=world, sha256=files[0]["sha256"], format="sdf")],
        edges=[
            dict(
                source=world,
                kind="plugin",
                text="driver",
                position="/sdf[1]/world[1]/plugin[1]/@filename",
                status="selected",
                selected=plugin,
                query=reply,
            )
        ],
        errors=[],
        local_file_graph_verified=True,
        runtime_closure_qualified=False,
        scope="fixed local file dependencies; no decoding, rendering or runtime callback proof",
    )
    declaration = dict(
        inventory={"graph:resolver": [resolver]}, graph=dict(cwd=str(tmp_path), environment=env, expected_context=context)
    )
    return dict(
        declaration=declaration,
        pre=dict(files=files, resource_graph=copy.deepcopy(graph)),
        after_queries=dict(files=files),
        graph=graph,
        context=context,
        queries=queries,
        documents={world: raw},
    )


def run(value):
    function = getattr(audit, "audit_resource_graph_records", None)
    assert callable(function), "resource graph audit missing"
    return function(**value)


def test_replays_graph_without_reading_files_or_starting_sdk(tmp_path, monkeypatch):
    value = fixture(tmp_path)
    import subprocess
    from pathlib import Path

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected runtime/file effect")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    result = run(value)
    assert result["raw_graph_records_consistent"] is True
    assert result["queries"] == 2
    assert result["runtime_closure_qualified"] is False
    assert result["live_qualified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "stdout",
        "hex",
        "nonzero",
        "missing_query",
        "extra_query",
        "argument",
        "environment",
        "timeout",
        "clock",
        "document",
        "edge",
        "selected",
        "undeclared",
        "drift",
        "graph_mirror",
        "extra_document",
        "error",
        "unknown_field",
    ],
)
def test_graph_refuses_missing_or_changed_raw_evidence(tmp_path, fault):
    value = fixture(tmp_path)
    if fault == "stdout":
        value["queries"][1]["stdout"] = "{}"
    elif fault == "hex":
        value["queries"][1]["stdout_hex"] = "7b7d"
    elif fault == "nonzero":
        value["queries"][1]["returncode"] = 1
    elif fault == "missing_query":
        value["queries"].pop()
    elif fault == "extra_query":
        value["queries"].append(copy.deepcopy(value["queries"][-1]))
    elif fault == "argument":
        value["queries"][1]["command"][-1] = "other"
    elif fault == "environment":
        value["queries"][1]["environment"] = dict(value["queries"][1]["environment"], SDF_PATH="/other")
    elif fault == "timeout":
        value["queries"][1]["ended_monotonic"] = 62.0
    elif fault == "clock":
        value["queries"][1]["started_monotonic"] = 0.5
    elif fault == "document":
        value["documents"][next(iter(value["documents"]))] = b"<sdf/>"
    elif fault == "edge":
        value["graph"]["edges"] = []
        value["pre"]["resource_graph"] = copy.deepcopy(value["graph"])
    elif fault == "selected":
        value["graph"]["edges"][0]["selected"] = "other"
        value["pre"]["resource_graph"] = copy.deepcopy(value["graph"])
    elif fault == "undeclared":
        value["pre"]["files"].pop(1)
    elif fault == "drift":
        value["after_queries"]["files"] = copy.deepcopy(value["pre"]["files"])
        value["after_queries"]["files"][0]["sha256"] = "0" * 64
    elif fault == "graph_mirror":
        value["pre"]["resource_graph"]["local_file_graph_verified"] = False
    elif fault == "extra_document":
        value["documents"][str(tmp_path / "extra.sdf")] = b"<sdf/>"
    elif fault == "error":
        value["queries"][1]["collection_errors"] = ["partial"]
    elif fault == "unknown_field":
        value["queries"][1]["inferred"] = True
    with pytest.raises(ValueError):
        run(value)
