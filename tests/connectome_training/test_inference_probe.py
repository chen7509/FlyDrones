import importlib
import importlib.util
import json
import subprocess
import sys

import pytest


def module():
    name = "tools.connectome_training.profile_inference"
    assert importlib.util.find_spec(name) is not None, "bounded inference probe missing"
    return importlib.import_module(name)


@pytest.mark.parametrize("change", [
    {"mode": "fake"}, {"samples": 0}, {"samples": True}, {"samples": 1001},
    {"warmup": -1}, {"warmup": 101}, {"threads": 0}, {"threads": 65},
    {"seed": True}, {"seed": -1}, {"timeout_s": float("nan")}, {"timeout_s": 301},
    {"checkpoint": "checkpoint"}, {"checkpoint_sha256": "a" * 64},
])
def test_strict_spec_rejects_invalid_request(change):
    with pytest.raises(ValueError):
        module().ProbeSpec(model="model", parameters="parameters", **change)


@pytest.mark.parametrize("available,allowed", [(4 * 1024**3 - 1, False), (4 * 1024**3, True)])
def test_full_resource_boundary(available, allowed, monkeypatch):
    api = module()
    monkeypatch.setattr(api, "available_memory_bytes", lambda: available)
    assert api._resource_check("full-male-cns")["allowed"] is allowed


@pytest.mark.parametrize("unknown", [False, True])
def test_resource_refusal_keeps_result_and_never_spawns(tmp_path, monkeypatch, unknown):
    api = module()
    def memory():
        if unknown:
            raise OSError("unavailable")
        return 1
    monkeypatch.setattr(api, "available_memory_bytes", memory)
    monkeypatch.setattr(api, "_run_child", lambda *args: pytest.fail("must not spawn"))
    output = tmp_path / "refused"
    result = api.run_probe(api.ProbeSpec(model="absent", parameters="absent"), output)
    assert result["status"] == "resource_refused"
    assert result["worker_started"] is False
    assert result["flight_eligible"] is False
    assert (output / "request.json").exists()
    assert json.loads((output / "result.json").read_text())["status"] == "resource_refused"
    assert not (output / "worker-result.json").exists()
    old = (output / "result.json").read_bytes()
    with pytest.raises(FileExistsError):
        api.run_probe(api.ProbeSpec(model="absent", parameters="absent"), output)
    assert (output / "result.json").read_bytes() == old


def test_real_memory_api_is_positive():
    if sys.platform != "win32":
        pytest.skip("Windows capacity observer")
    assert type(module().available_memory_bytes()) is int
    assert module().available_memory_bytes() > 0


def test_real_direct_child_timeout_preserves_logs_and_reaps(tmp_path):
    api = module()
    result = api._run_child([
        sys.executable, "-u", "-c",
        "import sys,time; print('partial'); print('failure context',file=sys.stderr); time.sleep(30)",
    ], tmp_path, .8)
    assert result["timed_out"] is True
    assert result["kill_sent"] is True
    assert result["returncode"] is not None
    assert result["reaped"] is True
    assert (tmp_path / "stdout.log").read_text().strip() == "partial"
    assert "failure context" in (tmp_path / "stderr.log").read_text()


def test_real_tiny_cli_uses_core_and_never_qualifies_full(tiny_artifacts, tmp_path):
    module()
    source, parameters, _, _ = tiny_artifacts()
    output = tmp_path / "probe"
    completed = subprocess.run([
        sys.executable, "tools/connectome_training/profile_inference.py",
        "--model", str(source), "--parameters", str(parameters), "--output", str(output),
        "--mode", "tiny-fixture", "--threads", "1", "--warmup", "1", "--samples", "3", "--timeout", "30",
    ], capture_output=True, text=True, timeout=40)
    assert completed.returncode == 0, completed.stderr
    parent = json.loads((output / "result.json").read_text())
    worker = json.loads((output / "worker-result.json").read_text())
    assert parent["status"] == worker["status"] == "completed"
    assert parent["child"]["reaped"] is True
    assert worker["model"]["parameter_origin"] == "initialization-only"
    assert worker["latency_gate"]["eligible"] is False
    assert worker["latency_gate"]["passed"] is False
    assert worker["flight_eligible"] is worker["training_success_verified"] is False
    rows = [json.loads(line) for line in (output / "samples.jsonl").read_text().splitlines()]
    assert [r["phase"] for r in rows] == ["warmup"] + ["measured"] * 3
    assert [r["frame_ns"] for r in rows] == [50_000_000, 50_000_000, 150_000_000, 150_000_000]
    assert [r["camera_reused"] for r in rows] == [False, True, False, True]
    assert worker["peak_process_memory_bytes"] > 0
    assert worker["threads"] == 1
    assert worker["inputs_unchanged"] is True
    assert len(worker["latency"]["raw_samples"]) == 3


def test_request_hash_refuses_change_before_loading(tmp_path):
    api = module()
    (tmp_path / "request.json").write_text("{}")
    with pytest.raises(ValueError, match="request hash"):
        api._read_request(tmp_path, "0" * 64)


def test_input_manifest_detects_file_drift(tiny_artifacts):
    api = module()
    source, parameters, _, _ = tiny_artifacts()
    spec = api.ProbeSpec(model=str(source), parameters=str(parameters), mode="tiny-fixture")
    before = api._input_hashes(spec)
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="input files changed"):
        api._verify_inputs(spec, before)


def test_invalid_source_keeps_actual_worker_failure(tiny_artifacts, tmp_path):
    api = module()
    source, parameters, _, _ = tiny_artifacts()
    source.write_bytes(source.read_bytes() + b"tamper")
    result = api.run_probe(api.ProbeSpec(model=str(source), parameters=str(parameters),
                                       mode="tiny-fixture", threads=1, timeout_s=30), tmp_path / "failed")
    assert result["status"] == "failed"
    assert result["child"]["returncode"] != 0
    worker = json.loads((tmp_path / "failed/worker-result.json").read_text())
    assert "source hash" in worker["error"]
    assert worker["flight_eligible"] is False


def test_spawn_failure_is_not_reported_as_a_started_worker(tiny_artifacts, tmp_path, monkeypatch):
    api = module()
    source, parameters, _, _ = tiny_artifacts()
    def failed_spawn(*args, **kwargs):
        raise OSError("cannot create process")
    monkeypatch.setattr(api.subprocess, "Popen", failed_spawn)
    result = api.run_probe(api.ProbeSpec(model=str(source), parameters=str(parameters), mode="tiny-fixture"),
                           tmp_path / "spawn-failed")
    assert result["status"] == "failed"
    assert result["worker_started"] is False
    assert "cannot create process" in result["error"]


def test_worker_rechecks_full_memory_before_model_construction(tmp_path, monkeypatch):
    api = module()
    request = {"schema": "connectome-probe-request-v1", "spec": {
        "model": "missing", "parameters": "missing", "mode": "full-male-cns",
    }, "input_hashes": {}}
    api._write_json(tmp_path / "request.json", request)
    monkeypatch.setattr(api, "available_memory_bytes", lambda: 1)
    monkeypatch.setattr(api, "_verify_inputs", lambda *args: pytest.fail("no loading on refusal"))
    assert api._worker(tmp_path, api._hash(tmp_path / "request.json")) == 0
    result = json.loads((tmp_path / "worker-result.json").read_text())
    assert result["status"] == "resource_refused"
    assert not (tmp_path / "samples.jsonl").exists()


def test_timed_out_parent_never_accepts_partial_completed_report(tiny_artifacts, tmp_path, monkeypatch):
    api = module()
    source, parameters, _, _ = tiny_artifacts()
    def timeout(command, output, timeout_s, **kwargs):
        api._write_json(output / "worker-result.json", {"status": "completed"})
        return {"pid": 1, "timed_out": True, "returncode": -9, "reaped": True}
    monkeypatch.setattr(api, "_run_child", timeout)
    result = api.run_probe(api.ProbeSpec(model=str(source), parameters=str(parameters), mode="tiny-fixture"),
                           tmp_path / "partial-timeout")
    assert result["status"] == "timed_out"
    assert "worker_result_sha256" in result
