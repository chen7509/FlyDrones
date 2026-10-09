"""A separate startup study cannot silently alter the frozen wire capture."""

import copy
import hashlib
import json

import pytest


def _declaration():
    return {
        "schema": "flydrones-live-wire-startup-diagnostic-declaration-v1",
        "study_id": "live-wire-dev-1701-v7",
        "study_manifest_sha256": "a" * 64,
        "observer_source_sha256": "b" * 64,
        "runner_source_sha256": "c" * 64,
        "observer_deadline_ns": 60_000_000_000,
        "ready_timeout_s": 5,
        "log_path": "/study/capture-v1/px4.log",
        "observation_path": "/study/startup-observation.json",
        "summary_path": "/study/startup-summary.json",
        "qualification_granted": False,
    }


def _plan():
    return {
        "run_id": "live-wire-dev-1701-v7",
        "study_manifest": {"sha256": "a" * 64},
        "destination": "/study/capture-v1",
    }


def test_exact_diagnostic_declaration_binds_study_and_observer():
    from tools.benchmark.execute_live_wire_startup_diagnostic import validate_diagnostic

    assert validate_diagnostic(_declaration(), _plan(), "b" * 64, "c" * 64)[
        "qualification_granted"] is False


@pytest.mark.parametrize("change", [
    {"study_manifest_sha256": "d" * 64},
    {"observer_source_sha256": "d" * 64},
    {"runner_source_sha256": "d" * 64},
    {"log_path": "/study/other.log"},
    {"observation_path": "/study/capture-v1/px4.log"},
    {"summary_path": "/study/startup-observation.json"},
    {"observer_deadline_ns": 120_000_000_000},
    {"ready_timeout_s": 8},
    {"qualification_granted": True},
])
def test_declaration_refuses_identity_or_deadline_drift(change):
    from tools.benchmark.execute_live_wire_startup_diagnostic import validate_diagnostic

    declaration = copy.deepcopy(_declaration())
    declaration.update(change)
    with pytest.raises(ValueError, match="startup diagnostic"):
        validate_diagnostic(declaration, _plan(), "b" * 64, "c" * 64)


def test_extra_claim_and_wrong_study_id_are_refused():
    from tools.benchmark.execute_live_wire_startup_diagnostic import validate_diagnostic

    declaration = _declaration()
    declaration["fusion_qualified"] = True
    with pytest.raises(ValueError, match="startup diagnostic"):
        validate_diagnostic(declaration, _plan(), "b" * 64, "c" * 64)
    declaration = _declaration()
    declaration["study_id"] = "live-wire-dev-1701-v6"
    with pytest.raises(ValueError, match="startup diagnostic"):
        validate_diagnostic(declaration, _plan(), "b" * 64, "c" * 64)


def test_executor_binds_declaration_before_invoking_existing_wire_executor(tmp_path, monkeypatch):
    import tools.benchmark.execute_live_wire_startup_diagnostic as diagnostic

    declaration = _declaration()
    declaration["observer_source_sha256"] = diagnostic._sha(
        diagnostic.Path(diagnostic.__file__).with_name("observe_px4_startup.py"))
    declaration["runner_source_sha256"] = diagnostic._sha(
        diagnostic.Path(diagnostic.__file__).with_name("live_wire_startup_runner.py"))
    path = tmp_path / "diagnostic.json"
    raw = json.dumps(declaration).encode()
    path.write_bytes(raw)
    seen = []
    monkeypatch.setattr(diagnostic, "prepare_live_wire_execution", lambda _path: _plan())

    def fake_execute(study, **kwargs):
        seen.append((study, kwargs))
        return 77

    monkeypatch.setattr(diagnostic, "execute_live_wire", fake_execute)
    selected = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="declaration drift"):
        diagnostic.execute_diagnostic(
            tmp_path / "study.json", path, selected_study_sha256="a" * 64,
            selected_diagnostic_sha256="0" * 64, resources_fn=lambda: [],
        )
    assert seen == []
    assert diagnostic.execute_diagnostic(
        tmp_path / "study.json", path, selected_study_sha256="a" * 64,
        selected_diagnostic_sha256=selected, resources_fn=lambda: [],
    ) == 77
    assert len(seen) == 1
    assert callable(seen[0][1]["runner"])


def test_symlink_declaration_refuses_before_existing_executor(tmp_path, monkeypatch):
    import tools.benchmark.execute_live_wire_startup_diagnostic as diagnostic

    declaration = _declaration()
    declaration["observer_source_sha256"] = diagnostic._sha(
        diagnostic.Path(diagnostic.__file__).with_name("observe_px4_startup.py"))
    declaration["runner_source_sha256"] = diagnostic._sha(
        diagnostic.Path(diagnostic.__file__).with_name("live_wire_startup_runner.py"))
    original = tmp_path / "real.json"
    raw = json.dumps(declaration).encode()
    original.write_bytes(raw)
    linked = tmp_path / "selected.json"
    try:
        linked.symlink_to(original)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    monkeypatch.setattr(diagnostic, "prepare_live_wire_execution", lambda _path: _plan())
    calls = []
    monkeypatch.setattr(diagnostic, "execute_live_wire", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="startup diagnostic declaration file"):
        diagnostic.execute_diagnostic(
            tmp_path / "study.json", linked, selected_study_sha256="a" * 64,
            selected_diagnostic_sha256=hashlib.sha256(raw).hexdigest(),
            resources_fn=lambda: [],
        )
    assert calls == []
