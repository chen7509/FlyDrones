import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "results/target-bearing-runtime-freeze-v3-dev-1701/run-static-preparation-v3.py"


def load(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("static_v3_coordinator_fixture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path / "results/target-bearing-runtime-freeze-v3-dev-1701")
    monkeypatch.setattr(module, "FOLDER", module.OUT / "frozen-study-v3")
    module.OUT.mkdir(parents=True)
    return module


def facts():
    return dict(
        windows_available=2**30,
        wsl=dict(available=2**30, processes=[]),
        windows_processes=[],
        blocked_processes=[],
        docker_exit=0,
        docker_running="",
    )


def test_first_refusal_retains_exact_facts_without_claim(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    first = facts()
    first["windows_available"] -= 1
    monkeypatch.setattr(m, "admission", lambda: first)
    monkeypatch.setattr(m, "source_snapshot", lambda: {"fixture": "source"})
    monkeypatch.setattr(m, "preidentity", lambda: pytest.fail("resource refusal must precede identity calls"))
    result = m.execute()
    assert result["attempt_consumed"] is False
    assert json.loads((m.OUT / "first-admission-private.json").read_text())["facts"] == first
    assert not (m.OUT / "attempt.json").exists()


def test_existing_claim_refuses_before_admission(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    (m.OUT / "attempt.json").write_text("{}")
    monkeypatch.setattr(m, "admission", lambda: pytest.fail("no gate for consumed attempt"))
    with pytest.raises(FileExistsError):
        m.execute()


def configure(m, monkeypatch):
    monkeypatch.setattr(m, "CONTROL", {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/1000"})
    monkeypatch.setattr(m, "admission", facts)
    monkeypatch.setattr(m, "source_snapshot", lambda: {"fixture": "source"})
    monkeypatch.setattr(m, "preidentity", lambda: {"fixture": "identity"})
    monkeypatch.setattr(m, "verify_preidentity", lambda identity: None)
    monkeypatch.setattr(m, "manager_call", lambda *args: subprocess.CompletedProcess(args, 0, b"LoadState=not-found\n", b""))
    monkeypatch.setattr(m, "observe_release", lambda unit: {"owned_group_released": True})
    monkeypatch.setattr(m, "verify_result", lambda: {"fixture_only": True})
    monkeypatch.setattr(m, "postidentity", lambda: {"fixture_only": True})


class Child:
    pid = 991

    def __init__(self):
        self.calls = []

    def poll(self):
        return None

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")

    def wait(self, timeout):
        self.calls.append(("wait", timeout))
        return 0


def test_after_spawn_writer_failure_cleans_owned_child_and_preserves_primary(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    child = Child()
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: child)
    write = m.write

    def fail(path, row):
        if path.name == "launcher.json":
            raise OSError("fixture postspawn writer")
        write(path, row)

    monkeypatch.setattr(m, "write", fail)
    result = m.execute()
    assert result["attempt_consumed"] is True and "postspawn writer" in result["error"]
    assert "terminate" in child.calls and ("wait", 5) in child.calls
    assert (m.OUT / "completion.json").is_file()


def test_timeout_unknown_scope_never_stops_unit(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    child = Child()

    def wait(timeout):
        child.calls.append(("wait", timeout))
        if timeout == 240:
            raise subprocess.TimeoutExpired("fixture", 240)
        return -15

    child.wait = wait
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: child)
    calls = []
    monkeypatch.setattr(
        m, "manager_call", lambda *args: calls.append(args) or subprocess.CompletedProcess(args, 0, b"LoadState=not-found\n", b"")
    )
    result = m.execute()
    assert result["attempt_consumed"] is True and result["error"]
    assert not any("stop" in args for args in calls)
    assert result["escaped_closure"] == "unknown"


def test_stop_requires_fresh_matching_invocation_and_group(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    unit = "fly-calibration-prepare-" + "a" * 24 + ".scope"
    inside = dict(cgroup="/fixture/" + unit, systemd_properties="InvocationID=original\nControlGroup=/fixture/" + unit)
    calls = []
    monkeypatch.setattr(
        m,
        "manager_call",
        lambda *args: (
            calls.append(args) or subprocess.CompletedProcess(args, 0, b"InvocationID=other\nControlGroup=/fixture\n", b"")
        ),
    )
    with pytest.raises(ValueError, match="ownership"):
        m.stop_if_owned(unit, inside)
    assert not any("stop" in args for args in calls)


def test_second_refusal_after_preidentity_never_claims(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    calls = []

    def collect():
        data = facts()
        if calls:
            data["wsl"]["available"] -= 1
        calls.append(True)
        return data

    monkeypatch.setattr(m, "admission", collect)
    result = m.execute()
    assert result["attempt_consumed"] is False and len(calls) == 2
    assert not (m.OUT / "attempt.json").exists()


def test_changed_postidentity_is_terminal_even_with_successful_launcher(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    child = Child()
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(m, "postidentity", lambda: (_ for _ in ()).throw(ValueError("fixture changed tool")), raising=False)
    result = m.execute()
    assert result["error"] and "changed tool" in result["postidentity_error"]


def test_manager_control_must_join_observed_uid(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "source_snapshot", lambda: {"fixture": "source"})
    record = dict(
        error=None,
        sources={"fixture": "source"},
        files_before=[],
        files_after=[],
        uid=1000,
        manager_control_environment=dict(PATH="/usr/bin:/bin", LANG="C.UTF-8", XDG_RUNTIME_DIR="/run/user/1001"),
    )
    with pytest.raises(ValueError, match="manager"):
        m.verify_preidentity(record)


def test_completion_writer_cannot_mask_primary_spawn_failure(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    configure(m, monkeypatch)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("primary spawn")))
    write = m.write

    def fail(path, row):
        if path.name == "completion.json":
            raise OSError("secondary writer")
        write(path, row)

    monkeypatch.setattr(m, "write", fail)
    result = m.execute()
    assert "primary spawn" in result["error"] and "secondary writer" in result["completion_writer_error"]
    assert json.loads((m.OUT / "completion-fallback.json").read_text())["error"] == result["error"]


def test_only_execute_flag_and_observer_source_has_no_import_effects(tmp_path, monkeypatch):
    import ast

    m = load(tmp_path, monkeypatch)
    observer = Path(__file__).resolve().parents[2] / "tools/benchmark/static_v3_identity.py"
    tree = ast.parse(observer.read_text(encoding="utf8"))
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name for n in imports if isinstance(n, ast.Import) for a in n.names}
    assert names == {"os", "sys", "time"} and not any(isinstance(n, ast.ImportFrom) for n in imports)
    assert m.observer_arguments("/request", "/output")[:2] == ["/usr/bin/python3", "-S"]
    with pytest.raises(SystemExit):
        m.main(["--preidentity"])


def test_preidentity_rejects_changed_host_bootstrap_bytes(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    record = dict(path="/usr/bin/sha256sum", sha256="a" * 64, bytes=2)
    monkeypatch.setattr(m, "host_pin", lambda p: dict(record, sha256="b" * 64))
    with pytest.raises(ValueError, match="bootstrap"):
        m.verify_bootstrap([record])


def test_primitive_decoder_retains_prefix_before_terminal_error(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    raw = b"{'kind': 'file', 'file': {'requested': '/a'}}\n{'kind': 'terminal', 'error': 'fixture failure'}\n"
    rows = m.decode_observer(raw)
    assert rows[0]["file"]["requested"] == "/a" and rows[-1]["error"] == "fixture failure"
    with pytest.raises(ValueError):
        m.decode_observer(raw + b"bad line\n")


def test_preidentity_invalid_manager_uid_rejected_before_claim(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        m.verify_preidentity(
            {
                "error": None,
                "sources": m.source_snapshot(),
                "files_before": [],
                "files_after": [],
                "uid": 1000,
                "manager_control_environment": {"XDG_RUNTIME_DIR": "/run/user/0"},
            }
        )


@pytest.mark.parametrize(
    "fault", ["empty", "missing_version", "extension", "changed_file", "bad_clock", "valid", "wrongargv", "emptyversion"]
)
def test_preidentity_terminal_and_membership_are_independently_verified(tmp_path, monkeypatch, fault):
    m = load(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "source_snapshot", lambda: {"fixture": "source"})
    file = dict(requested="/usr/bin/sha256sum", resolved="/usr/bin/sha256sum", bytes=3, sha256="a" * 64, identity={"inode": 1})
    request = dict(
        sources={"fixture": "source"},
        paths=["/usr/bin/sha256sum"],
        roots=[],
        versions=["/usr/bin/sha256sum"],
        bootstrap=[dict(path="/usr/bin/sha256sum", bytes=3, sha256="a" * 64)],
    )
    monkeypatch.setattr(m, "host_pin", lambda p: dict(path=p, bytes=3, sha256="a" * 64))
    monkeypatch.setattr(m, "linux", lambda p: str(p))
    monkeypatch.setattr(m, "OBSERVER", Path(__file__))
    rows = [
        dict(kind="bootstrap", file=file),
        dict(
            kind="begin",
            requested=["/usr/bin/sha256sum"],
            uid=1000,
            manager_control_environment=dict(PATH="/usr/bin:/bin", LANG="C.UTF-8", XDG_RUNTIME_DIR="/run/user/1000"),
            imported_extensions=[],
            start_monotonic_ns=1,
        ),
        dict(kind="file", phase="before", file=file),
        dict(
            kind="version",
            file="/usr/bin/sha256sum",
            file_before=file,
            file_after=file,
            query=dict(
                argv=["/usr/bin/sha256sum", "--version"],
                environment=dict(PATH="/usr/bin:/bin", LANG="C.UTF-8"),
                pid=432,
                exit=0,
                error=None,
                reader_complete=True,
                stdout_hex="31",
                stderr_hex="",
                start_monotonic_ns=2,
                end_monotonic_ns=3,
                elapsed_ns=1,
                cleanup=dict(waited=True, escaped_closure="unknown"),
            ),
        ),
        dict(kind="file", phase="after", file=file),
        dict(kind="terminal", error=None, imported_extensions=[], start_monotonic_ns=1, end_monotonic_ns=4, elapsed_ns=3),
    ]
    if fault == "wrongargv":
        rows[3]["query"]["argv"] = ["/wrong", "--version"]
    if fault == "emptyversion":
        rows[3]["query"]["stdout_hex"] = ""
    if fault == "empty":
        rows = [dict(rows[1], requested=[]), rows[-1]]
    if fault == "missing_version":
        rows = [r for r in rows if r["kind"] != "version"]
    if fault == "extension":
        rows[-1]["imported_extensions"] = ["_json"]
    if fault == "changed_file":
        rows[4] = dict(rows[4], file=dict(file, sha256="b" * 64))
    if fault == "bad_clock":
        rows[-1]["elapsed_ns"] = 0

    # Explicit raw hashing protocol rows, never a real SHA child or Linux proof.
    def hashrow(file, start):
        return dict(
            kind="hash-query",
            query=dict(
                argv=["/usr/bin/sha256sum", "--", file["requested"]],
                environment=dict(PATH="/usr/bin:/bin", LANG="C.UTF-8"),
                pid=433,
                exit=0,
                error=None,
                reader_complete=True,
                stdout_hex=(file["sha256"] + "  " + file["requested"] + "\n").encode().hex(),
                stderr_hex="",
                start_monotonic_ns=start,
                end_monotonic_ns=start + 1,
                elapsed_ns=1,
                cleanup=dict(waited=True, escaped_closure="unknown"),
            ),
        )

    expanded = []
    for row in rows:
        if row["kind"] == "bootstrap":
            expanded += [hashrow(row["file"], 0), row]
        elif row["kind"] == "file":
            expanded += [hashrow(row["file"], 2 if row["phase"] == "before" else 8), row]
        elif row["kind"] == "version":
            row["query"].update(start_monotonic_ns=5, end_monotonic_ns=6)
            expanded += [hashrow(file, 4), hashrow(file, 6), row]
        else:
            if row["kind"] == "begin":
                row["start_monotonic_ns"] = 0
            if row["kind"] == "terminal":
                row.update(start_monotonic_ns=0, end_monotonic_ns=10, elapsed_ns=0 if fault == "bad_clock" else 10)
            expanded.append(row)
    rows = expanded

    def remote(*argv, **kw):
        (m.OUT / "preidentity-primitive.txt").write_text("".join(repr(r) + "\n" for r in rows), encoding="utf8")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(m, "remote", remote)
    if fault == "valid":
        assert m.identity_run("preidentity", request)["files_before"] == [file]
    else:
        with pytest.raises(ValueError):
            m.identity_run("preidentity", request)


def test_request_builder_timeout_cleans_only_own_child(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    child = Child()

    def wait(timeout):
        child.calls.append(("wait", timeout))
        if timeout == 15:
            raise subprocess.TimeoutExpired("fixture request", 15)
        return -15

    child.wait = wait
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **kw: child)
    with pytest.raises(subprocess.TimeoutExpired):
        m.build_request_bounded()
    assert "terminate" in child.calls and ("wait", 5) in child.calls
    saved = json.loads((m.OUT / "request-builder-return.json").read_bytes())
    assert saved["error"] and saved["cleanup"]["exit"] == -15


def test_before_use_bootstrap_includes_launchers_and_loader(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    assert {"/usr/bin/env", "/usr/bin/timeout", "/lib64/ld-linux-x86-64.so.2", "/usr/bin/python3", "/usr/bin/sha256sum"}.issubset(
        m.BOOTSTRAP_TOOLS
    )


def test_study_input_closure_refuses_unapproved_runtime_file(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    before = dict(
        requested="/approved", resolved="/approved", bytes=1, sha256="a" * 64, identity={"inode": 1}, path_identity={"inode": 1}
    )
    binding = dict(inventory={}, baseline={"files": [dict(before, requested="/new-file", role="runtime:python-modules")]})
    with pytest.raises(ValueError, match="prepin"):
        m.validate_study_inputs({"files_before": [before]}, binding, {"path": "/scene", "files": {}})


def test_identity_timeout_retains_existing_primitive_prefix_and_stdout(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "linux", lambda p: str(p))
    monkeypatch.setattr(m, "OBSERVER", Path(__file__))
    monkeypatch.setattr(m, "verify_bootstrap", lambda r: None)

    def remote(*a, **k):
        (m.OUT / "preidentity-primitive.txt").write_bytes(b"{'kind':'file','file':{'requested':'/prefix'}}\n{'truncated'")
        raise subprocess.TimeoutExpired(a, 45, output=b"actual fixture prefix stdout", stderr=b"fixture stderr")

    monkeypatch.setattr(m, "remote", remote)
    request = dict(paths=["/prefix"], roots=[], versions=[], bootstrap=[])
    with pytest.raises(subprocess.TimeoutExpired):
        m.identity_run("preidentity", request)
    row = json.loads((m.OUT / "preidentity-return.json").read_bytes())
    assert row["raw_bytes"] > 0 and bytes.fromhex(row["stdout_hex"]) == b"actual fixture prefix stdout"
    prefix = json.loads((m.OUT / "preidentity-decoded-prefix.json").read_bytes())
    assert prefix["rows"][0]["file"]["requested"] == "/prefix" and prefix["parse_error"]


def test_identity_rejects_claimed_hashes_without_raw_hash_queries(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    file = dict(requested="/a", resolved="/a", bytes=1, sha256="a" * 64)
    rows = [
        dict(kind="bootstrap", file=file),
        dict(kind="begin", requested=["/a"], uid=1000, imported_extensions=[], start_monotonic_ns=1),
        dict(kind="file", phase="before", file=file),
        dict(kind="file", phase="after", file=file),
        dict(kind="terminal", error=None, imported_extensions=[], end_monotonic_ns=3, elapsed_ns=2),
    ]
    request = dict(paths=["/a"], roots=[], versions=[], bootstrap=[dict(path="/a", bytes=1, sha256="a" * 64)])
    with pytest.raises(ValueError, match="hash"):
        m.validate_identity_rows(rows, request)


def test_request_includes_native_sources_headers_and_startup_controls(tmp_path, monkeypatch):
    from tools.benchmark import calibration_capture_contract as scene_api
    from tools.benchmark import prepare_calibration_capture as old
    from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256

    m = load(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "source_snapshot", lambda: {"source.py": "a" * 64})
    base = m.ROOT / "results/target-bearing-runtime-freeze-dev-1701/frozen-study-v1"
    base.mkdir(parents=True)
    binary = m.linux(base / "agent-deployment-v1/bin/MicroXRCEAgent")
    lib = m.linux(base / "agent-deployment-v1/lib")
    expected = {"bin/MicroXRCEAgent": AGENT_SHA256, **{"lib/" + k: v for k, v in LIBRARY_SHA256.items()}}
    config = dict(schema="capture-agent-runtime-v1", binary=binary, lib_dir=lib, bundle="/bundle", port=18888)
    (base / "agent-runtime.json").write_text(json.dumps(config))
    (base / "agent-deployment.json").write_text(
        json.dumps(
            dict(bundle={"sha256": BUNDLE_SHA256}, members=[dict(member=k, deployed={"sha256": v}) for k, v in expected.items()])
        )
    )
    libs = tmp_path / "libs"
    libs.mkdir()
    for name in LIBRARY_SHA256:
        (libs / name).write_bytes(b"fixture")
    site = tmp_path / "site"
    site.mkdir()
    for name in ["numpy", "scipy", "pyulog", "pymavlink", "protobuf"]:
        info = site / (name + "-1.dist-info")
        info.mkdir()
        (info / "METADATA").write_text("Name: " + name + "\nVersion: 1\n")
    (site / "startup.pth").write_text("fixture startup source")
    monkeypatch.setattr(
        m, "host_path", lambda p: libs if p == lib else site if p == "/usr/lib/python3/dist-packages" else tmp_path / "absent"
    )
    hashes = {binary: AGENT_SHA256, "/bundle": BUNDLE_SHA256, **{lib + "/" + k: v for k, v in LIBRARY_SHA256.items()}}
    monkeypatch.setattr(m, "host_pin", lambda p: dict(path=p, bytes=1, sha256=hashes.get(p, "a" * 64)))
    monkeypatch.setattr(
        scene_api, "scene_record", lambda p: dict(path=str(tmp_path / "scene"), files={"world.sdf": {"sha256": "a" * 64}})
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {"inventory": {"graph:resolver": ["/resolver"], "graph:source": ["/source.cc"], "graph:dependencies": ["/header.hh"]}}
        )
    )
    monkeypatch.setattr(old, "CATALOG", catalog)
    request = m.identity_request()
    assert {
        "/source.cc",
        "/header.hh",
        "/etc/python3.12/sitecustomize.py",
        "/usr/lib/python3/dist-packages/startup.pth",
    }.issubset(request["paths"])


def test_actual_prepare_includes_existing_python_cache_bytes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from test_calibration_capture_study_v3 import (
        test_actual_prepare_v3_pipeline_keeps_empty_selection_self_and_context as pipeline,
    )

    from tools.benchmark import prepare_calibration_capture_v3 as prepare

    source = tmp_path / "cached-module.py"
    source.write_text("# source")
    cache = tmp_path / "cached-module.pyc"
    cache.write_bytes(b"fixture bytecode, never executed")
    monkeypatch.setattr(
        prepare, "sys", SimpleNamespace(modules={"fixture_source": SimpleNamespace(__file__=str(source), __cached__=str(cache))})
    )
    pipeline(tmp_path, monkeypatch)
    binding = json.loads((tmp_path / "out/frozen/runtime-binding-v4.json").read_bytes())
    assert str(cache) in binding["inventory"]["runtime:python-modules"]


def test_primitive_writer_secondary_failure_keeps_primary(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from tools.benchmark import static_v3_identity as observer
    request=tmp_path/'request.txt';request.write_text('P\t'+b'/fixture'.hex()+'\n')
    calls=[]
    def fail(fd,data):
        calls.append(data)
        raise OSError('primary journal' if len(calls)==1 else 'secondary journal')
    fake=SimpleNamespace(**{k:getattr(observer.os,k) for k in dir(observer.os) if not k.startswith('__')})
    fake.getuid=lambda:1000
    fake.lstat=lambda p:SimpleNamespace(st_uid=1000,st_mode=0o040700)
    fake.stat=lambda p:SimpleNamespace(st_dev=1,st_ino=1,st_mode=0o100600,st_size=1,st_mtime_ns=1,st_ctime_ns=1)
    fake.write=fail
    monkeypatch.setattr(observer,'os',fake)
    monkeypatch.setattr(observer,'sys',SimpleNamespace(platform='linux',flags=SimpleNamespace(no_site=1),builtin_module_names=['time'],version='fixture'))
    monkeypatch.setattr(observer,'imported_extensions',lambda:[])
    monkeypatch.setattr(observer,'query',lambda *a:dict(exit=0,error=None,stdout_hex=('a'*64+'  /fixture\n').encode().hex(),stderr_hex='',reader_complete=True))
    with pytest.raises(OSError,match='primary journal') as caught:observer.observe(str(request),str(tmp_path/'primitive.txt'))
    assert 'secondary journal' in ' '.join(caught.value.__notes__)


def test_scope_absence_nonzero_return_is_not_admission(tmp_path,monkeypatch):
    m=load(tmp_path,monkeypatch);configure(m,monkeypatch)
    monkeypatch.setattr(m,'manager_call',lambda *a:subprocess.CompletedProcess(a,1,b'LoadState=not-found\n',b'fixture nonzero'))
    with pytest.raises(ValueError,match='absence'):m.execute()
    assert not (m.OUT/'attempt.json').exists()
