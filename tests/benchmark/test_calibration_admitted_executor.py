"""Real dispatcher paths with explicit file/process protocol fixtures only."""

import importlib
import json

import pytest


def api():
    return importlib.import_module("tools.benchmark.run_calibration_capture")


def facts(memory=4 * 1024**3):
    return dict(
        windows_available=memory,
        wsl=dict(available=4 * 1024**3, processes=[]),
        windows_processes=[],
        blocked_processes=[],
        docker_exit=0,
        docker_running="",
        admitted=True,
    )


@pytest.mark.parametrize("scenario", ["first_refusal", "second_refusal", "source_drift", "success"])
def test_actual_dispatch_admission_claim_and_replay(tmp_path, scenario):
    m = api()
    events = []
    study = tmp_path / "study.json"
    study.write_text("{}")
    record = tmp_path / "admission.json"
    attempt = tmp_path / "attempt"
    counters = [
        facts(4 * 1024**3 - 1 if scenario == "first_refusal" else 4 * 1024**3),
        facts(4 * 1024**3 - 1 if scenario == "second_refusal" else 4 * 1024**3),
    ]

    def collect():
        events.append("admission")
        return counters.pop(0)

    n = [0]

    def verify(*_):
        n[0] += 1
        events.append("verify")
        return dict(study_sha256="frozen", files_sha256="changed" if scenario == "source_drift" and n[0] == 2 else "current")

    def launch(*_):
        assert (attempt / "attempt.json").exists()
        events.append("launch")
        return dict(exit=0, owned_group_released=True)

    result = m.execute_once(study, "a" * 64, record, attempt, collect=collect, verify=verify, launch=launch)
    assert json.loads(record.read_text())["first"] == facts(4 * 1024**3 - 1 if scenario == "first_refusal" else 4 * 1024**3)
    if scenario == "success":
        assert events == ["admission", "verify", "verify", "admission", "launch"]
        assert result["attempt_claimed"] is True
        with pytest.raises(FileExistsError):
            m.execute_once(study, "a" * 64, tmp_path / "next-record.json", attempt, collect=collect, verify=verify, launch=launch)
    else:
        assert "launch" not in events and not attempt.exists()
        assert result["attempt_claimed"] is False
        if scenario == "first_refusal":
            assert events == ["admission"]
    assert all(v is False for v in result["qualification"].values())


def test_partial_launch_failure_consumes_claim_without_new_directory(tmp_path):
    m = api()
    study = tmp_path / "study.json"
    study.write_text("{}")
    attempt = tmp_path / "attempt"

    def launch(*_):
        raise OSError("actual Popen protocol refusal")

    result = m.execute_once(
        study,
        "a" * 64,
        tmp_path / "admission.json",
        attempt,
        collect=facts,
        verify=lambda *_: dict(current="same"),
        launch=launch,
    )
    assert result["attempt_claimed"] is True and "Popen protocol refusal" in result["error"]
    assert (attempt / "completion.json").exists()
    with pytest.raises(FileExistsError):
        m.execute_once(
            study,
            "a" * 64,
            tmp_path / "admission2.json",
            attempt,
            collect=facts,
            verify=lambda *_: dict(current="same"),
            launch=launch,
        )


def test_inside_real_counter_gate_before_collector(tmp_path):
    m = importlib.import_module("tools.benchmark.calibration_capture_scope")
    values = {"memory.max": str(4 * 1024**3), "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "256"}
    properties = {"InvocationID": "fixture", "ControlGroup": "/user.slice/fly-calibration-123.scope"}
    assert m.verify_scope("fly-calibration-123.scope", properties["ControlGroup"], values, properties) is None
    values["memory.swap.max"] = "1"
    with pytest.raises(ValueError, match="scope"):
        m.verify_scope("fly-calibration-123.scope", properties["ControlGroup"], values, properties)


def test_prepared_scene_handoff_uses_frozen_bytes_and_refuses_extra(tmp_path, monkeypatch):
    import hashlib

    from tools.benchmark import calibration_capture_contract as raw
    from tools.benchmark import capture_disarmed_sensors as capture

    out = tmp_path / "prepared"
    out.mkdir()
    (out / "world.sdf").write_bytes(b"fixture-world")
    source = dict(path="source", files={"world.sdf": dict(bytes=13, sha256=hashlib.sha256(b"fixture-world").hexdigest())})
    prepared = dict(source, path=str(out))

    def record(path):
        if str(path) == str(out) and (out / "unexpected").exists():
            raise ValueError("member set changed")
        return prepared if str(path) == str(out) else source

    monkeypatch.setattr(raw, "scene_record", record)
    assert raw.validate_prepared_scene(source, out) == prepared
    result = capture.select_capture_scene(out, dict(raw_measurement=dict(scene=source, prepared_input=prepared)))
    assert result == {"world.sdf": source["files"]["world.sdf"]["sha256"]}
    (out / "unexpected").write_bytes(b"old-result")
    with pytest.raises(ValueError):
        raw.validate_prepared_scene(source, out)


def test_supervisor_prepared_handoff_keeps_original_absence_guard(tmp_path, monkeypatch):
    from tools.benchmark import calibration_capture_contract as raw
    from tools.benchmark.disarmed_sensor_provenance import supervise_worker

    selected = []

    def validate(source, out):
        selected.append((source, out))

    monkeypatch.setattr(raw, "validate_prepared_scene", validate)

    def spawn(*_, **__):
        raise RuntimeError("fixture launch boundary reached")

    with pytest.raises(FileExistsError):
        supervise_worker(["fixture"], tmp_path, spawn=spawn, terminate=lambda _: None)
    with pytest.raises(RuntimeError, match="launch boundary"):
        supervise_worker(["fixture"], tmp_path, spawn=spawn, terminate=lambda _: None, prepared_input={"scene": "fixture"})
    assert selected == [({"scene": "fixture"}, tmp_path)]


def test_study_current_files_detect_actual_member_mutation(tmp_path):
    from tools.benchmark.declared_runtime_snapshot import file_record

    m = importlib.import_module("tools.benchmark.calibration_capture_study")
    p = tmp_path / "binding.json"
    p.write_bytes(b"bound-fixture")
    rows = {"binding": file_record(p)}
    assert m.verify_files(rows) == rows
    p.write_bytes(b"changed-input")
    with pytest.raises(ValueError, match="study input"):
        m.verify_files(rows)


def test_command_join_accepts_declared_resolved_interpreter_identity(tmp_path):
    from tools.benchmark.calibration_capture_study import require_command_baseline

    path = tmp_path / "python3.12"
    path.write_bytes(b"fixture-interpreter")
    rows = [dict(requested=str(tmp_path / "python3"), resolved=str(path.resolve()))]
    assert require_command_baseline([path], rows) is None
    with pytest.raises(ValueError, match="input bill"):
        require_command_baseline([tmp_path / "unselected"], rows)


def test_scope_timeout_missing_identity_only_cleans_own_launcher(tmp_path, monkeypatch):
    import subprocess

    m = api()
    from types import SimpleNamespace

    stopped = []

    class Process:
        pid = 700
        waits = 0
        done = False

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("protocol fixture", timeout)
            return -1

        def poll(self):
            return -1 if self.done else None

        def terminate(self):
            self.done = True
            stopped.append("own-terminate")

    monkeypatch.setattr(m.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(
        m, "wsl", lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=b"LoadState=not-found\n", stderr=b"")
    )
    monkeypatch.setattr(m, "stop_scope", lambda *_: stopped.append("unit-stop"))
    with pytest.raises(RuntimeError, match="timeout"):
        m.launch_scope(tmp_path, tmp_path / "study", "a" * 64, {}, "fly-calibration-" + "a" * 24 + ".scope")
    assert stopped == ["own-terminate"]
    assert json.loads((tmp_path / "scope-ownership-unknown.json").read_text())["residual"] == "unknown; no unit stop"


def test_scope_stop_rejects_different_invocation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    m = api()
    unit = "fly-calibration-" + "a" * 24 + ".scope"
    group = "/user.slice/" + unit
    calls = []

    def observed(*argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=("InvocationID=changed\nControlGroup=" + group + "\n").encode(), stderr=b"")

    monkeypatch.setattr(m, "wsl", observed)
    with pytest.raises(RuntimeError, match="ownership unknown"):
        m.stop_scope(tmp_path, unit, dict(cgroup=group, systemd_properties="InvocationID=original\nControlGroup=" + group + "\n"))
    assert len(calls) == 1 and "stop" not in calls[0]


def test_preparation_never_reuses_old_estimator_roots():
    m = importlib.import_module("tools.benchmark.prepare_calibration_capture")
    assert m.runtime_catalog(
        dict(
            inventory={
                "runtime-root:openvins": ["old-consumed"],
                "runtime-root:native-reference": ["old-reference"],
                "runtime:estimator-inputs": ["old-yaml"],
                "runtime-root:physics-dartsim": ["installed-physics"],
                "runtime:dependencies": ["/lib/installed.so", "/usr/local/old-numpy.so"],
                "runtime-root:python-numpy": ["/usr/local/old-module.so"],
            }
        )
    ) == ["installed-physics", "/lib/installed.so"]


def test_real_worker_environment_accepts_validated_prepared_input(tmp_path, monkeypatch):
    from tools.benchmark import calibration_capture_contract as raw
    from tools.benchmark.capture_disarmed_sensors import record_worker_environment

    out = tmp_path / "prepared"
    out.mkdir()
    selected = []
    monkeypatch.setattr(raw, "validate_prepared_scene", lambda source, path: selected.append((source, path)))
    contract = dict(
        schema="capture-execution-v2",
        launch_environment={"HOME": "fixture"},
        raw_measurement=dict(scene={"fixture": True}, prepared_input={"fixture": True}),
    )
    path = tmp_path / "execution.json"
    path.write_text(json.dumps(contract))
    result = record_worker_environment(out, contract, path, reader=lambda: b"HOME=fixture\0")
    assert result["matches"] is True and selected == [({"fixture": True}, out)]
    assert (out / "execution-environment-worker.json").exists()
    contract.pop("raw_measurement")
    with pytest.raises(FileExistsError):
        record_worker_environment(out, contract, path, reader=lambda: b"HOME=fixture\0")


@pytest.mark.parametrize("failure", ["start_write", "wait", "post_verify"])
def test_linux_helper_retains_terminal_facts_and_cleans_own_process(tmp_path, monkeypatch, failure):
    import subprocess
    from pathlib import Path
    from types import SimpleNamespace

    from tools.benchmark import calibration_capture_scope as m
    from tools.benchmark import calibration_capture_study as study

    group = "/user.slice/fly-calibration-123.scope"
    cg = tmp_path / "cg"
    cg.mkdir()
    for key, value in {
        "memory.max": str(4 * 1024**3),
        "memory.swap.max": "0",
        "cpu.max": "100000 100000",
        "pids.max": "256",
        "memory.events": "oom 0\n",
        "memory.peak": "123",
    }.items():
        (cg / key).write_text(value)
    proc = tmp_path / "cgroup"
    proc.write_text("0::" + group)
    monkeypatch.setattr(
        m,
        "Path",
        lambda value: (
            proc if str(value) == "/proc/self/cgroup" else cg if str(value) == "/sys/fs/cgroup" + group else Path(value)
        ),
    )
    monkeypatch.setattr(
        m.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="InvocationID=fixture\nControlGroup=" + group)
    )
    monkeypatch.setattr(m, "manager_environment", lambda: {"PATH": "fixture"}, raising=False)
    checked = dict(command=["fixture"], cwd=str(tmp_path))

    def verify(*a, **k):
        if failure == "post_verify" and k.get("require_absent") is False:
            raise ValueError("actual fixture post input drift")
        return checked

    monkeypatch.setattr(study, "verify_study", verify)
    terminated = []

    class Process:
        pid = 700
        done = False

        def poll(self):
            return 0 if self.done else None

        def terminate(self):
            self.done = True
            terminated.append("own")

        def kill(self):
            self.done = True

        def wait(self, timeout):
            if failure == "wait" and not self.done:
                raise subprocess.TimeoutExpired("fixture", timeout)
            self.done = True
            return 0

    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: Process())
    original_write = m.write

    def write(path, value):
        if failure == "start_write" and path.name == "collector-start.json":
            raise OSError("fixture start write refused")
        original_write(path, value)

    monkeypatch.setattr(m, "write", write)
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            dict(output=str(tmp_path), unit="fly-calibration-123.scope", study="fixture", study_sha256="a", verified=checked)
        )
    )
    with pytest.raises((OSError, ValueError, subprocess.TimeoutExpired)):
        m.main([str(profile)])
    result = json.loads((tmp_path / "inside-completion.json").read_text())
    assert result["error"] and result["memory_events"] == "oom 0\n"
    assert result["memory_peak"] == "123" and result["qualification"] is False
    assert terminated == (["own"] if failure in {"start_write", "wait"} else [])


def test_dependency_timeout_preserves_previous_and_partial_query(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    from tools.benchmark import prepare_calibration_capture as m

    paths = [tmp_path / "a.so", tmp_path / "b.so"]
    for path in paths:
        path.write_bytes(b"\x7fELFfixture")

    def run(argv, **kwargs):
        if argv[-1].endswith("b.so"):
            raise subprocess.TimeoutExpired(argv, 10, output=b"partial-native", stderr=b"partial-error")
        return SimpleNamespace(returncode=0, stdout=b"/lib/fixture.so (0x123)\n", stderr=b"")

    monkeypatch.setattr(m.subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        m.dependencies(paths, "fixture", tmp_path)
    records = json.loads((tmp_path / "ldd-observations.json").read_text())
    assert len(records) == 2 and records[0]["exit"] == 0
    assert bytes.fromhex(records[1]["stdout_hex"]) == b"partial-native"
    assert bytes.fromhex(records[1]["stderr_hex"]) == b"partial-error" and records[1]["error"]


def test_required_plugins_are_selected_from_original_scene_before_baseline(tmp_path):
    from tools.benchmark import prepare_calibration_capture as m

    (tmp_path / "world.sdf").write_text(
        '<sdf version="1.9"><world name="w"><plugin name="physics" filename="gz-sim-physics-system"/></world></sdf>'
    )
    models = tmp_path / "models"
    models.mkdir()
    (models / "model.sdf").write_text(
        '<sdf version="1.9"><model name="m"><plugin name="motor" filename="gz-sim-multicopter-motor-model-system"/></model></sdf>'
    )
    calls = []

    class Client:
        def query(self, *args):
            calls.append(args)
            return dict(selected="/installed/" + args[1] + ".so")

    roots = m.required_plugins(tmp_path, Client())
    assert calls == [("plugin", "gz-sim-multicopter-motor-model-system"), ("plugin", "gz-sim-physics-system")]
    assert roots == ["/installed/" + name[1] + ".so" for name in calls]


@pytest.mark.parametrize("failure", ["launcher_write", "early_helper"])
def test_windows_post_spawn_failure_cleans_owned_process_and_scope(tmp_path, monkeypatch, failure):
    from types import SimpleNamespace

    m = api()
    unit = "fly-calibration-" + "a" * 24 + ".scope"
    group = "/user.slice/" + unit
    stopped = []

    class Process:
        pid = 700
        done = False

        def poll(self):
            return 1 if self.done else None

        def wait(self, timeout):
            self.done = True
            return 1

        def terminate(self):
            self.done = True
            stopped.append("own")

    def spawn(*a, **k):
        (tmp_path / "inside-before.json").write_text(
            json.dumps(dict(cgroup=group, systemd_properties="InvocationID=fixture\nControlGroup=" + group))
        )
        return Process()

    monkeypatch.setattr(m.subprocess, "Popen", spawn)
    monkeypatch.setattr(m, "stop_scope", lambda *a: stopped.append("scope"))

    def wsl(*argv, **kwargs):
        if argv[0] == "test":
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"LoadState=not-found\n", stderr=b"")

    monkeypatch.setattr(m, "wsl", wsl)
    old_write = m.write

    def write(path, value):
        if path.name == "launcher.json" and failure == "launcher_write":
            raise OSError("fixture launcher write failed")
        old_write(path, value)

    monkeypatch.setattr(m, "write", write)
    if failure == "launcher_write":
        with pytest.raises(OSError, match="launcher write failed"):
            m.launch_scope(tmp_path, tmp_path / "study", "a" * 64, {}, unit)
        assert stopped == ["scope", "own"]
    else:
        result = m.launch_scope(tmp_path, tmp_path / "study", "a" * 64, {}, unit)
        assert result["exit"] == 1 and stopped == ["scope"]
    assert (tmp_path / "owned-launcher-timeout-cleanup.json").exists()


@pytest.mark.parametrize("mutation", ["prepared", "environment"])
def test_study_join_rejects_declared_handoff_or_environment_drift(tmp_path, monkeypatch, mutation):
    from types import SimpleNamespace

    from tools.benchmark import calibration_capture_contract as raw
    from tools.benchmark import calibration_capture_study as m

    actual = dict(path="actual", files={"fixture": "same"})
    monkeypatch.setattr(raw, "validate_prepared_scene", lambda *a: actual)
    monkeypatch.setattr(m, "execution_contract", lambda args, env: dict(launch_environment=env, raw_measurement=dict(scene={})))
    env = {"HOME": "bound"}
    execution = dict(
        launch_environment={"HOME": "different"} if mutation == "environment" else env,
        raw_measurement=dict(scene={}, prepared_input=dict(actual, path="different") if mutation == "prepared" else actual),
    )
    binding = dict(schema="capture-resource-binding-v4", environment=env, graph=dict(environment={}))
    with pytest.raises(ValueError):
        m.verify_execution_join(SimpleNamespace(output=tmp_path, prepared_scene=True), execution, binding, True)


@pytest.mark.parametrize("mutation", ["extra", "duplicate"])
def test_preparation_exact_input_bill_rejects_unbound_graph_dependency(tmp_path, monkeypatch, mutation):
    from tools.benchmark import audit_live_wire_resources as audit
    from tools.benchmark import calibration_capture_study as m

    monkeypatch.setattr(m, "FOLDER", tmp_path)
    monkeypatch.setattr(audit, "audit_resource_graph_records", lambda **kwargs: dict(raw_graph_records_consistent=True))
    baseline = dict(requested="fixture-baseline", role="fixture", sha256="a")
    world = dict(requested=str(tmp_path / "capture-input-v1/world.sdf"), role="generated:world.sdf", sha256="b")
    rows = [baseline, world, dict(requested="unbound-plugin", role="unbound", sha256="c") if mutation == "extra" else baseline]
    binding = dict(baseline=dict(files=[baseline]), generated={"world.sdf": "b"})
    prep = dict(
        schema="raw-static-sdk-preparation-v1",
        binding_sha256="fixture",
        execution_sha256="fixture",
        pre=dict(files=rows),
        after_queries=dict(files=rows),
        graph={},
        context={},
        queries=[],
        documents_hex={},
        audit=dict(raw_graph_records_consistent=True),
    )
    with pytest.raises(ValueError, match="input bill"):
        m.audit_preparation(binding, prep)


def test_manager_environment_uses_own_uid_without_mutating_query_environment(tmp_path, monkeypatch):
    from tools.benchmark import calibration_capture_scope as m

    monkeypatch.setattr(m.os, "getuid", lambda: 0, raising=False)
    runtime = tmp_path / "0"
    runtime.mkdir()
    before = dict(m.os.environ)
    env = m.manager_environment(tmp_path)
    assert env == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": str(runtime)}
    assert dict(m.os.environ) == before
    runtime.rmdir()
    with pytest.raises((OSError, ValueError)):
        m.manager_environment(tmp_path)


def test_actual_agent_deployment_bytes_exclusive_and_bundle_drift(tmp_path, monkeypatch):
    import hashlib
    import io
    import tarfile

    from tools.benchmark import agent_capture_runtime as agent
    from tools.benchmark import prepare_calibration_capture as m

    bundle = tmp_path / "bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        for name in ("bin", "lib"):
            item = tarfile.TarInfo(name)
            item.type = tarfile.DIRTYPE
            archive.addfile(item)
        for name, data in (("bin/MicroXRCEAgent", b"binary-fixture"), ("lib/fixture.so", b"library-fixture")):
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    monkeypatch.setattr(agent, "BUNDLE_SHA256", hashlib.sha256(bundle.read_bytes()).hexdigest())
    monkeypatch.setattr(agent, "AGENT_SHA256", hashlib.sha256(b"binary-fixture").hexdigest())
    monkeypatch.setattr(agent, "LIBRARY_SHA256", {"fixture.so": hashlib.sha256(b"library-fixture").hexdigest()})
    out = tmp_path / "deploy"
    record = m.stage_agent(bundle, out)
    assert (out / "bin/MicroXRCEAgent").read_bytes() == b"binary-fixture"
    assert (out / "lib/fixture.so").read_bytes() == b"library-fixture" and record["executed"] is False
    with pytest.raises(FileExistsError):
        m.stage_agent(bundle, out)
    bundle.write_bytes(b"changed-bundle")
    with pytest.raises(ValueError, match="bundle"):
        m.stage_agent(bundle, tmp_path / "new")
