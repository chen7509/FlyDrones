"""Production capture orchestration with external services explicitly replaced."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.benchmark import capture_contract as contract
from tools.benchmark import capture_disarmed_sensors as capture
from tools.benchmark.owned_ulog_source import LIMITS


def runner(request):
    spec = importlib.util.spec_from_file_location(
        "capture_runner_fixture", Path(__file__).with_name("test_capture_runtime_runner.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    case = module.RuntimeRunnerTests()
    case.setUp()
    request.addfinalizer(case.doCleanups)
    case.args["contract"]["owned_ulog_source"] = {"schema": "capture-owned-ULog-opener-v1", **LIMITS}
    observer = SimpleNamespace()
    observer.register = lambda process, binary: case.events.append("source-register")
    observer.observe = lambda: case.events.append(("source-observe", case.clock["sim_ns"]))
    case.args["source_association"] = observer
    return case, observer


def test_actual_runner_registers_before_step_and_bounds_sampling_and_prestop(request):
    case, _ = runner(request)
    case.execute()
    assert case.result["status"] == "capture_completed"
    assert case.events.index("source-register") < case.events.index("postfirststep")
    observations = [e for e in case.events if isinstance(e, tuple) and e[0] == "source-observe"]
    assert 25 <= len(observations) <= 27
    assert observations[-1][1] == 25_000_000_000
    assert case.events.index(observations[-1]) < case.events.index("terminate")


def test_observer_failure_does_not_prevent_owned_child_stop(request):
    case, observer = runner(request)
    observer.observe = lambda: (_ for _ in ()).throw(ValueError("source identity refused"))
    case.execute()
    assert case.result["status"] == "capture_failed"
    assert "source identity refused" in str(case.result["errors"])
    assert "terminate" in case.events
    assert case.process.returncode == 0


def test_owned_observer_requires_declared_bound_px4_before_spawn(request):
    case, _ = runner(request)
    case.args["binding"] = None
    case.execute()
    assert case.result["status"] == "capture_failed"
    assert "spawn" not in case.events


def test_contract_refuses_undeclared_logger_for_owned_source(tmp_path):
    args = capture.parse_capture_args(["--output", str(tmp_path)])
    args.record_owned_ulog = True
    with pytest.raises(ValueError, match="logger"):
        contract.execution_contract(args)


def test_contract_freezes_observer_limits_and_forwards_option(tmp_path, monkeypatch):
    args = capture.parse_capture_args(["--output", str(tmp_path)])
    args.record_owned_ulog = True
    args.logger_diagnostic_profile = "source-diagnostic-v1"
    args.agent_runtime_config = tmp_path / "agent.json"
    args.wire_config = tmp_path / "wire.json"
    args.runtime_binding = tmp_path / "binding.json"
    args.execution_contract = tmp_path / "execution.json"
    monkeypatch.setattr(contract, "wire_configuration_record", lambda path: {})
    monkeypatch.setattr("tools.benchmark.agent_capture_runtime.agent_runtime_record", lambda path: {})
    selected = contract.execution_contract(args)["owned_ulog_source"]
    assert selected["observe_sim_period_ns"] == 1_000_000_000
    assert selected["max_observations"] == 64
    assert selected["max_fd_entries"] == 256
    assert "--record-owned-ulog" in contract.worker_options(args)


def test_parser_accepts_only_owned_logger_context(tmp_path):
    args = capture.parse_capture_args(
        [
            "--output",
            str(tmp_path),
            "--record-owned-ulog",
            "--logger-diagnostic-profile",
            "source-diagnostic-v1",
            "--agent-runtime-config",
            str(tmp_path / "agent.json"),
            "--wire-config",
            str(tmp_path / "wire.json"),
            "--runtime-binding",
            str(tmp_path / "binding.json"),
            "--execution-contract",
            str(tmp_path / "execution.json"),
            "--source-fanout-profile",
            "ready-shadow-heartbeat-estimator-v1",
            "--shadow-binary",
            str(tmp_path / "native"),
            "--shadow-config",
            str(tmp_path / "config"),
            "--reference-module",
            str(tmp_path / "reference"),
            "--reference-sha256",
            "a" * 64,
            "--motion-profile",
            "supported-ready-v1",
            "--physics-trace-profile",
            "substep-ready-v1",
        ]
    )
    assert args.record_owned_ulog is True


def test_cleanup_preserves_collected_ulogs_before_association_refusal(tmp_path, monkeypatch):
    from tools.benchmark.disarmed_sensor_provenance import CaptureJournal

    events = []
    records = [{"path": "px4-ulog/log.ulg", "sha256": "a" * 64, "bytes": 32}]
    monkeypatch.setattr(capture, "collect_ulogs", lambda *args: events.append("collect") or records)

    class Producer:
        def __init__(self, *args, **kwargs):
            pass

        def finish(self, received):
            assert received is records
            events.append("associate")
            return {"errors": ["missing owned witness"], "all_logs_associated": False}

    monkeypatch.setattr("tools.benchmark.owned_ulog_source.OwnedUlogSource", Producer)
    result = {"status": "capture_completed", "errors": []}
    with CaptureJournal(tmp_path, result) as journal:
        capture.prepare_owned_ulog_collection(
            {"owned_ulog_source": {"schema": "capture-owned-ULog-opener-v1", **LIMITS}},
            tmp_path,
            tmp_path,
            "a" * 64,
            result,
            journal,
        )
    assert events == ["collect", "associate"]
    assert result["px4_ulogs"] is records
    assert result["owned_ulog_source"]["all_logs_associated"] is False
    assert result["status"] == "capture_failed"
