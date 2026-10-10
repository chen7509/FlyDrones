import json

import pytest


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def failed_capture(tmp_path):
    capture = tmp_path / "capture-v1"
    capture.mkdir()
    write_json(capture / "result.json", {
        "status": "capture_failed",
        "end_sim_ns": 10_000_000,
        "motion": {"active_steps": 0, "support_steps": 0, "absolute_impulse_ns": 0.0},
        "source_fanout": {"fusion_eligible": False},
        "px4_exit_code": -9,
        "errors": ["process mapping not covered", "future acknowledgement source"],
    })
    return capture


def renderer_probe(tmp_path):
    probe = tmp_path / "renderer-probe-v7"
    probe.mkdir()
    libraries = [{"path": str(tmp_path / f"library-{index}.so")} for index in range(23)]
    for row in libraries:
        (tmp_path / row["path"]).write_bytes(b"library")
    write_json(probe / "result.json", {
        "status": "probe_completed",
        "runtime_closure_qualified": True,
        "mapping": {
            "cache_absent": True,
            "historical_additions": libraries,
            "baseline_additions": [],
        },
    })
    audit = tmp_path / "renderer-probe-v7-audit.json"
    write_json(audit, {
        "failures": [],
        "probe_qualified": True,
        "isolated_renderer_mapping_closure_qualified": True,
        "full_capture_runtime_closure_qualified": False,
    })
    return probe, audit


@pytest.mark.parametrize("field", ["status", "end", "motion", "fusion", "exit", "errors"])
def test_failed_capture_validation_rejects_drift(tmp_path, field):
    from tools.benchmark.estimator_physical_refusal_preflight import validate_failed_capture

    capture = failed_capture(tmp_path)
    validate_failed_capture(capture)
    result = json.loads((capture / "result.json").read_text())
    if field == "status":
        result["status"] = "completed"
    elif field == "end":
        result["end_sim_ns"] += 1
    elif field == "motion":
        result["motion"]["active_steps"] = 1
    elif field == "fusion":
        result["source_fanout"]["fusion_eligible"] = True
    elif field == "exit":
        result["px4_exit_code"] = 0
    else:
        result["errors"] = []
    write_json(capture / "result.json", result)
    with pytest.raises(ValueError):
        validate_failed_capture(capture)


@pytest.mark.parametrize("field", ["status", "closure", "cache", "count", "audit", "scope"])
def test_renderer_probe_validation_rejects_drift(tmp_path, field):
    from tools.benchmark.estimator_physical_refusal_preflight import validate_probe

    probe, audit = renderer_probe(tmp_path)
    validate_probe(probe, audit)
    result = json.loads((probe / "result.json").read_text())
    audit_value = json.loads(audit.read_text())
    if field == "status":
        result["status"] = "probe_failed"
    elif field == "closure":
        result["runtime_closure_qualified"] = False
    elif field == "cache":
        result["mapping"]["cache_absent"] = False
    elif field == "count":
        result["mapping"]["historical_additions"].pop()
    elif field == "audit":
        audit_value["failures"] = ["bad"]
    else:
        audit_value["full_capture_runtime_closure_qualified"] = True
    write_json(probe / "result.json", result)
    write_json(audit, audit_value)
    with pytest.raises(ValueError):
        validate_probe(probe, audit)


def test_augment_binding_adds_only_declared_inputs(tmp_path, monkeypatch):
    from tools.benchmark import estimator_physical_refusal_preflight as module
    from tools.benchmark.declared_runtime_snapshot import snapshot

    base = tmp_path / "base.bin"
    code = tmp_path / "code.py"
    contract = tmp_path / "contract.json"
    evidence = tmp_path / "evidence.json"
    library = tmp_path / "renderer.so"
    for path in (base, code, contract, evidence, library):
        path.write_bytes(path.name.encode())
    inventory = {"runtime:base": [str(base.resolve())]}
    binding = {
        "environment": {"HOME": "/home/test"},
        "inventory": inventory,
        "baseline": snapshot(inventory),
    }
    monkeypatch.setattr(module, "code_paths", lambda: [str(code.resolve())])
    result = module.augment_binding(
        binding,
        renderer_libraries=[{"path": str(library.resolve())}],
        evidence_paths=[evidence],
        contract_path=contract,
    )
    assert "MESA_SHADER_CACHE_DISABLE" not in binding["environment"]
    assert result["environment"]["MESA_SHADER_CACHE_DISABLE"] == "true"
    assert result["inventory"]["runtime:renderer-first-step-libraries"] == [str(library.resolve())]
    assert result["baseline"]["files"] == snapshot(result["inventory"])["files"]


def test_augment_binding_rejects_conflicting_mesa_setting(tmp_path):
    from tools.benchmark.estimator_physical_refusal_preflight import augment_binding

    with pytest.raises(ValueError, match="Mesa environment conflicts"):
        augment_binding(
            {"environment": {"MESA_SHADER_CACHE_DISABLE": "false"}, "inventory": {}},
            renderer_libraries=[], evidence_paths=[], contract_path=tmp_path / "missing",
        )
