"""Inert production executor and primitive receipt behavior; never dispatch."""

import builtins
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_default_guard_is_installed_before_new_executor_body():
    import subprocess

    assert subprocess.Popen._execute_child.__name__ == "denied"


@pytest.mark.parametrize(
    "value", [None, False, True, 0, -42, "字符串", b"\x00raw", [1, "two"], {"schema": "inert", "values": [None, True, 5]}]
)
def test_primitive_codec_exact_roundtrip(value):
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    assert p.decode_primitive(p.encode_primitive(value)) == value


@pytest.mark.parametrize("data", [b"", b"v4bad", b"V4F1i00;", b"V4F1nextra", b"V4F1d2:s1:ai1;s1:ai2;", b"V4F1l99999999:"])
def test_primitive_decoder_denies_malformed_duplicate_or_partial(data):
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    with pytest.raises(ValueError):
        p.decode_primitive(data)


def test_primitive_hash_matches_independent_host_hash():
    import hashlib

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    for data in (b"", b"abc", b"x" * 64, b"x" * 4097):
        assert p.sha256(data) == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("name", ["static_v4_identity", "static_v4_bootstrap"])
def test_primitive_module_import_and_main_are_inert_before_commands(name, monkeypatch):
    source = (ROOT / "tools/benchmark" / (name + ".py")).read_bytes()
    original = builtins.__import__
    calls = []

    def restricted(module, *args, **kwargs):
        if module in ("sys", "os", "time"):
            return original(module, *args, **kwargs)
        calls.append(module)
        raise AssertionError("nonprimitive import")

    def deny(*a, **k):
        raise AssertionError("unexpected IO")

    for main in (False, True):
        namespace = dict(__name__="__main__" if main else "inert", __file__=str(ROOT / "tools/benchmark" / (name + ".py")))
        with monkeypatch.context() as patch:
            patch.setattr(builtins, "open", deny)
            patch.setattr(builtins, "__import__", restricted)
            if main:
                with pytest.raises(SystemExit):
                    exec(compile(source, name, "exec"), namespace)
            else:
                exec(compile(source, name, "exec"), namespace)
    assert not calls


def receipt_fixture(p):
    recipe = dict(
        schema="static-recipe-v4",
        source_root="/fixture/project",
        nonce="a" * 64,
        unit="fly-calibration-prepare-" + "a" * 24 + ".scope",
        source_sha256={"tools/a.py": "b" * 64},
        files=["/fixture/project/tools/a.py"],
        versions=[],
        sdk_environment={"PATH": "/usr/bin:/bin"},
        static_limits={"memory.max": "536870912", "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "64"},
    )
    scope = dict(
        uid=1000,
        pid=99,
        unit=recipe["unit"],
        InvocationID="c" * 32,
        ControlGroup="/user.slice/" + recipe["unit"],
        limits=dict(recipe["static_limits"]),
    )
    pre = dict(
        schema="static-identity-v4",
        phase="pre",
        nonce=recipe["nonce"],
        recipe_sha256=p.sha256(p.encode_primitive(recipe)),
        source_root=recipe["source_root"],
        source_sha256=dict(recipe["source_sha256"]),
        files_before=[],
        files_after=[],
        versions=[],
        error=None,
        started_monotonic_ns=1,
        ended_monotonic_ns=2,
        uid=1000,
    )
    ident = dict(device=1, inode=1, mode=33188, size=1, mtime_ns=1, ctime_ns=1)
    record = dict(
        requested=recipe["files"][0],
        resolved=recipe["files"][0],
        links=[],
        identity=ident,
        path_identity=dict(ident),
        bytes=1,
        sha256="b" * 64,
    )
    pre["files_before"] = [record]
    pre["files_after"] = [record]
    claim = dict(
        schema="static-claim-v4",
        nonce=recipe["nonce"],
        unit=recipe["unit"],
        recipe_sha256=pre["recipe_sha256"],
        preidentity_sha256=p.sha256(p.encode_primitive(pre)),
        source_root=recipe["source_root"],
    )
    marker = dict(
        schema="static-sdk-start-v4",
        pid=99,
        uid=1000,
        nonce=recipe["nonce"],
        InvocationID=scope["InvocationID"],
        ControlGroup=scope["ControlGroup"],
        claim_sha256=p.sha256(p.encode_primitive(claim)),
        started_monotonic_ns=3,
    )
    ticket = dict(
        schema="static-sdk-ticket-reference-v4",
        nonce=recipe["nonce"],
        unit=recipe["unit"],
        InvocationID=scope["InvocationID"],
        ControlGroup=scope["ControlGroup"],
        claim_sha256=marker["claim_sha256"],
        recipe_sha256=claim["recipe_sha256"],
        preidentity_sha256=claim["preidentity_sha256"],
        sdk_start_sha256=p.sha256(p.encode_primitive(marker)),
    )
    return recipe, scope, pre, claim, marker, ticket


def test_receipt_semantics_valid_with_independent_inert_scope_records():
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, scope, pre, claim, marker, ticket = receipt_fixture(p)
    assert (
        p.validate_sdk_ticket(ticket, actual_scope=scope, recipe=recipe, preidentity=pre, claim=claim, marker=marker, now=3)[
            "sdk_pid"
        ]
        == 99
    )


@pytest.mark.parametrize(
    "mutation", ["nonce", "uid", "pid", "invocation", "group", "marker", "source", "extra", "stale", "nonzero"]
)
def test_full_receipt_validation_refuses_internally_shaped_changes(mutation):
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, scope, pre, claim, marker, ticket = receipt_fixture(p)
    if mutation == "nonce":
        ticket["nonce"] = "d" * 64
    elif mutation == "uid":
        scope["uid"] = 2000
    elif mutation == "pid":
        scope["pid"] = 100
    elif mutation == "invocation":
        scope["InvocationID"] = "d" * 32
    elif mutation == "group":
        scope["ControlGroup"] = "/wrong/group"
    elif mutation == "marker":
        marker = None
    elif mutation == "source":
        pre["source_sha256"]["tools/a.py"] = "e" * 64
    elif mutation == "extra":
        pre["files_before"] = [{"requested": "/extra"}]
    elif mutation == "stale":
        pre["ended_monotonic_ns"] = 0
    else:
        pre["error"] = "nonzero metadata command"
    with pytest.raises(ValueError):
        p.validate_sdk_ticket(ticket, actual_scope=scope, recipe=recipe, preidentity=pre, claim=claim, marker=marker, now=3)


def test_primary_writer_failure_cannot_mask_observer_failure():
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    first = ValueError("primary observation")

    def body(emit):
        emit({"partial": "kept"})
        raise first

    rows = []

    def writer(value):
        if value.get("terminal"):
            raise OSError("final writer")
        rows.append(value)

    with pytest.raises(ValueError, match="primary observation") as caught:
        p.retain_observation(body, writer)
    assert caught.value is first and rows == [{"partial": "kept"}]
    assert any("final writer" in note for note in first.__notes__)


def test_real_windows_entry_denies_pytest_before_file_or_child(monkeypatch):
    p = importlib.import_module("tools.benchmark.static_v4_executor")

    def deny(*a, **k):
        raise AssertionError("effect before pytest refusal")

    monkeypatch.setattr(p, "native_backend", deny)
    with pytest.raises(ValueError, match="pytest"):
        p.execute_once()


def test_incomplete_task4_cannot_dispatch_even_with_fixture_boundary(monkeypatch):
    p = importlib.import_module("tools.benchmark.static_v4_executor")
    monkeypatch.setattr(p, "production_boundary", lambda: None)

    def deny(*a, **k):
        raise AssertionError("pending production called backend")

    monkeypatch.setattr(p, "native_backend", deny)
    with pytest.raises(ValueError, match="Task4 .*pending"):
        p.execute_once()


@pytest.mark.parametrize(
    "stage", ["first", "second", "absence", "claim", "spawn", "wait", "post", "release", "writer", "success"]
)
def test_actual_coordinator_lifecycle_with_only_inert_backend(stage):
    p = importlib.import_module("tools.benchmark.static_v4_executor")
    calls = []

    class Inert:
        def record(self, name, value):
            calls.append(name)
            if stage == "writer" and name == "completion":
                raise OSError("completion writer")

        def admission(self, number):
            calls.append("gate" + str(number))
            return dict(
                windows_available=0 if stage == ("first" if number == 1 else "second") else 1073741824,
                wsl_available=1073741824,
                competitor_count=0,
                docker_exit=0,
                docker_empty=True,
            )

        def prepare_identity(self):
            calls.append("pre")
            return {"uid": 1000}

        def scope_absent(self):
            calls.append("absence")
            return dict(exit=1 if stage == "absence" else 0, absent=True)

        def claim(self):
            calls.append("claim")
            if stage == "claim":
                raise FileExistsError("claim duplicate")

        def start(self):
            calls.append("spawn")
            if stage == "spawn":
                raise OSError("spawn failure")
            return "owned-inert-process"

        def finish(self, process):
            calls.append("wait")
            if stage == "wait":
                raise TimeoutError("owned timeout")
            return 0

        def postverify(self):
            calls.append("post")
            if stage == "post":
                raise ValueError("postidentity changed")

        def cleanup(self, process):
            calls.append("own-cleanup")

        def release(self):
            calls.append("release")
            if stage == "release":
                raise ValueError("unknown group")
            return dict(owned_group_released=True, escaped_closure="UNKNOWN")

    if stage in ("first", "second"):
        result = p.run_protocol(Inert())
        assert result["state"] == "REFUSED_UNCONSUMED" and "spawn" not in calls
    elif stage == "success":
        assert p.run_protocol(Inert())["state"] == "CHILD_ZERO_STATIC_AUDIT_PENDING"
    else:
        with pytest.raises((ValueError, OSError, TimeoutError)):
            p.run_protocol(Inert())
        if stage in ("wait", "post", "release", "writer"):
            assert "own-cleanup" in calls
    if stage == "absence":
        assert "claim" not in calls


@pytest.mark.parametrize("mutation", ["none", "exit", "claim", "source", "post", "extra", "generated-native"])
def test_finished_native_receipt_joins_are_not_caller_authority(mutation):
    import copy

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, scope, pre, claim, marker, ticket = receipt_fixture(p)
    post = copy.deepcopy(pre)
    post["phase"] = "post"
    child = dict(schema="static-child-exit-v4", exit=0, waited=True, claim_sha256=p.sha256(p.encode_primitive(claim)))
    if mutation == "exit":
        child["exit"] = 1
    elif mutation == "claim":
        child["claim_sha256"] = "0" * 64
    elif mutation == "source":
        post["source_sha256"]["tools/a.py"] = "0" * 64
    elif mutation == "post":
        post["files_after"][0]["sha256"] = "0" * 64
    elif mutation == "extra":
        post["files_before"].append(copy.deepcopy(post["files_before"][0]))
    elif mutation == "generated-native":
        record = copy.deepcopy(post["files_before"][0])
        record["requested"] = record["resolved"] = "/unknown/new.so"
        post["files_before"].append(record)
        post["files_after"] = copy.deepcopy(post["files_before"])
    if mutation == "none":
        assert p.audit_finished_native_receipts(recipe, pre, post, claim, child)["files"] == pre["files_before"]
    else:
        with pytest.raises(ValueError):
            p.audit_finished_native_receipts(recipe, pre, post, claim, child)


@pytest.mark.parametrize("mode", ["normal", "cap", "timeout", "partial-pipe"])
def test_real_primitive_query_lifecycle_uses_inert_os_only(mode):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_identity")

    class Inert:
        WNOHANG = 1

        def __init__(self):
            self.pairs = []
            self.closed = []
            self.killed = []
            self.reads = 0
            self.ticks = 0

        def pipe(self):
            if mode == "partial-pipe" and self.pairs:
                raise OSError("second pipe primary")
            pair = (3, 4) if not self.pairs else (5, 6)
            self.pairs.append(pair)
            return pair

        def fork(self):
            return 1234

        def close(self, fd):
            self.closed.append(fd)

        def set_blocking(self, *a):
            pass

        def read(self, fd, limit):
            assert limit == 65536
            if fd == 5:
                return b""
            self.reads += 1
            if mode == "cap":
                return b"x" * 65536
            return b"ok" if self.reads == 1 else b""

        def waitpid(self, *a):
            return (0, 0) if mode == "timeout" and not self.killed else (1234, 0)

        def kill(self, pid, signal):
            assert pid == 1234
            self.killed.append(signal)

        def sched_yield(self):
            pass

        def waitstatus_to_exitcode(self, v):
            return v

        def monotonic_ns(self):
            self.ticks += 1_000_000_000 if mode == "timeout" else 1
            return self.ticks

    api = Inert()
    row = p.query(["/inert/tool"], {"PATH": "/inert"}, api=api, clock=SimpleNamespace(monotonic_ns=api.monotonic_ns))
    if mode == "partial-pipe":
        assert "second pipe primary" in row["error"] and set(api.closed) == {3, 4}
    elif mode == "normal":
        assert row["exit"] == 0 and row["reader_complete"] and bytes.fromhex(row["stdout_hex"]) == b"ok"
    elif mode == "cap":
        assert "bound" in row["error"] and len(bytes.fromhex(row["stdout_hex"])) == 2 * 1024**2
    else:
        assert "10s" in row["error"] and api.killed == [15] and row["cleanup"]["waited"]


def test_actual_scope_reads_virtual_payload_without_st_size_assumption(monkeypatch):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_bootstrap")
    recipe, scope, *_ = receipt_fixture(p)
    cg = scope["ControlGroup"]
    content = {"/proc/self/cgroup": ("0::" + cg + "\n").encode()}
    content.update({"/sys/fs/cgroup" + cg + "/" + k: (v + "\n").encode() for k, v in recipe["static_limits"].items()})
    opened = {}
    closed = []

    def opening(path, flags):
        fd = len(opened) + 3
        opened[fd] = [path, content[path]]
        return fd

    def reading(fd, count):
        data = opened[fd][1][:count]
        opened[fd][1] = opened[fd][1][count:]
        return data

    def stating(fd):
        return SimpleNamespace(
            st_dev=1,
            st_ino=fd,
            st_mode=33188,
            st_size=0 if opened[fd][0].startswith("/proc/") else 4096,
            st_mtime_ns=1,
            st_ctime_ns=1,
        )

    api = SimpleNamespace(
        open=opening,
        read=reading,
        fstat=stating,
        close=closed.append,
        O_RDONLY=0,
        O_CLOEXEC=1,
        O_NONBLOCK=2,
        getuid=lambda: 1000,
        getpid=lambda: 99,
    )
    monkeypatch.setattr(p, "os", api)
    monkeypatch.setattr(
        p,
        "query",
        lambda *a: dict(
            exit=0,
            error=None,
            cleanup=dict(waited=True),
            reader_complete=True,
            stdout_hex=("InvocationID=" + scope["InvocationID"] + "\nControlGroup=" + cg + "\n").encode().hex(),
            stderr_hex="",
        ),
    )
    assert p.actual_scope(recipe)["limits"] == recipe["static_limits"]
    assert len(closed) == 5
    with pytest.raises(ValueError, match="receipt changed"):
        p.read_bytes("/proc/self/cgroup", 65536)


@pytest.mark.parametrize("always", [False, True])
def test_owned_windows_cleanup_escalates_actual_popen_timeout(always):
    import subprocess

    p = importlib.import_module("tools.benchmark.static_v4_executor")
    calls = []

    class Child:
        code = None

        def poll(self):
            return self.code

        def terminate(self):
            calls.append("terminate")

        def kill(self):
            calls.append("kill")

        def wait(self, timeout):
            calls.append("wait")
            if always or calls.count("wait") == 1:
                raise subprocess.TimeoutExpired("inert", timeout)
            self.code = 0
            return 0

    if always:
        with pytest.raises(ValueError, match="wait unavailable"):
            p.NativeWindowsBackend.cleanup(None, Child())
    else:
        p.NativeWindowsBackend.cleanup(None, Child())
    assert calls == ["terminate", "wait", "kill", "wait"]


@pytest.mark.parametrize("failure", ["cleanup", "release", "combined"])
def test_completion_records_first_cleanup_error_and_independent_fallback(failure):
    import copy

    p = importlib.import_module("tools.benchmark.static_v4_executor")
    retained = {}

    class Backend:
        def admission(self, n):
            return dict(windows_available=2**30, wsl_available=2**30, competitor_count=0, docker_exit=0, docker_empty=True)

        def record(self, name, value):
            retained[name] = copy.deepcopy(value)
            if failure == "combined" and name == "completion":
                raise OSError("writer secondary")

        def completion_fallback(self, value):
            retained["fallback"] = copy.deepcopy(value)

        def prepare_identity(self):
            pass

        def scope_absent(self):
            return dict(exit=0, absent=True)

        def claim(self):
            pass

        def start(self):
            return "inert"

        def finish(self, child):
            return 0

        def postverify(self):
            pass

        def cleanup(self, child):
            if failure != "release":
                raise ValueError("cleanup primary")

        def release(self):
            raise ValueError("release primary")

    with pytest.raises(ValueError, match="release primary" if failure == "release" else "cleanup primary"):
        p.run_protocol(Backend())
    row = retained["completion"]
    assert row["state"] == "FAILED" and row["consumed"] and row["child_exit"] == 0
    assert ("release primary" if failure == "release" else "cleanup primary") in row["error"]
    if failure == "combined":
        assert retained["fallback"]["completion_persisted"] is False
        assert "writer secondary" in retained["fallback"]["persistence_error"]


def test_finished_receiver_validation_is_repeatable_without_observer_or_writes(monkeypatch):
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    calls = []

    class Receiver:
        def request(self):
            calls.append("request")
            return {"exact": "retained"}

        def acquire(self, request):
            calls.append("acquire")

        def validate(self, request):
            calls.append("validate")
            return {"sdk_exit": 0}

    backend = Receiver()
    p.acquire_finished_receipts(backend)
    assert p.validate_retained_finished_receipts(backend) == {"sdk_exit": 0}
    assert p.validate_retained_finished_receipts(backend) == {"sdk_exit": 0}
    assert calls == ["request", "acquire", "validate", "request", "validate", "request", "validate"]


@pytest.mark.parametrize("mutation", ["none", "request", "command", "study", "index", "source", "post"])
def test_real_finished_receiver_coordinator_then_task3_join_is_readonly(tmp_path, monkeypatch, mutation):
    import copy
    import hashlib
    import json
    import subprocess
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    executor = importlib.import_module("tools.benchmark.static_v4_executor")
    pipeline = importlib.import_module("tools.benchmark.calibration_capture_pipeline_v4")
    if __import__("os").name == "nt":
        tmp_path = Path("\\\\?\\" + str(tmp_path))
    recipe, scope, pre, claim, *_ = receipt_fixture(p)
    folder = tmp_path / "results/target-bearing-runtime-freeze-v4-dev-1701/frozen-study-v4"
    folder.mkdir(parents=True)
    parent = folder.parent

    # Explicit host/native transport protocol, never a production path grant.
    def native(path):
        relative = Path(path).relative_to(tmp_path).as_posix()
        return "/fixture/project" + ("/" + relative if relative != "." else "")

    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf8")

    for name, value in (
        ("study.json", {}),
        ("finished-artifact-index.json", {"files": []}),
        ("sdk-complete.json", {}),
        ("runtime-binding-v4.json", {"baseline": {"files": []}}),
        ("preparation.json", {"pre": {"files": []}}),
        ("sdk/entry-dependencies/entry-bill.json", {"files": []}),
    ):
        write_json(folder / name, value)
    child = dict(schema="static-child-exit-v4", exit=0, waited=True, claim_sha256=p.sha256(p.encode_primitive(claim)))
    for name, value in (("recipe", recipe), ("preidentity", pre), ("claim", claim), ("child-exit", child)):
        (parent / (name + ".frame")).write_bytes(p.encode_primitive(value))
    monkeypatch.setattr(executor, "ROOT", tmp_path)
    monkeypatch.setattr(executor, "OUT", parent)
    monkeypatch.setattr(executor, "native_path", native)
    monkeypatch.setattr(executor, "production_boundary", lambda: None)
    monkeypatch.setattr(executor.NativeWindowsBackend, "sources", lambda self: dict(recipe["source_sha256"]))
    calls = []

    def observe(argv, **kwargs):
        calls.append("inert-observer")
        request = p.decode_primitive((parent / "post-request.frame").read_bytes())
        post = copy.deepcopy(pre)
        post.update(phase="post", recipe_sha256=p.sha256(p.encode_primitive(request["recipe"])))
        records = {r["requested"]: r for r in post["files_before"]}
        for name in ("study.json", "finished-artifact-index.json", "sdk-complete.json"):
            path = folder / name
            data = path.read_bytes()
            record = copy.deepcopy(pre["files_before"][0])
            record.update(requested=native(path), resolved=native(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            record["identity"]["size"] = record["path_identity"]["size"] = len(data)
            records[native(path)] = record
        post["files_before"] = [records[path] for path in request["recipe"]["files"]]
        post["files_after"] = copy.deepcopy(post["files_before"])
        (parent / "postidentity.frame").write_bytes(p.encode_primitive(post))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", observe)
    sha = hashlib.sha256((folder / "study.json").read_bytes()).hexdigest()
    executor.NativeWindowsBackend.postverify(None)
    first = {path.name: path.read_bytes() for path in parent.glob("*.frame")}
    monkeypatch.setattr(pipeline, "audit_finished_transport", lambda identity, digest: (identity["sdk_exit"], digest))
    assert pipeline.verify_finished_transport(folder / "study.json", sha) == (0, sha)
    assert calls == ["inert-observer"]
    assert first == {path.name: path.read_bytes() for path in parent.glob("*.frame")}
    if mutation == "none":
        assert pipeline.verify_finished_transport(folder / "study.json", sha) == (0, sha)
    else:
        if mutation in ("study", "index"):
            (folder / ("study.json" if mutation == "study" else "finished-artifact-index.json")).write_bytes(
                b"{} " if mutation == "study" else b'{"files": []} '
            )
        elif mutation == "source":
            monkeypatch.setattr(executor.NativeWindowsBackend, "sources", lambda self: {})
        elif mutation == "command":
            write_json(parent / "postidentity-command.json", dict(exit=1, stdout_hex="", stderr_hex=""))
        else:
            dest = parent / ("post-request.frame" if mutation == "request" else "postidentity.frame")
            record = p.decode_primitive(dest.read_bytes())
            if mutation == "request":
                record["study_sha256"] = "0" * 64
            else:
                record["error"] = "partial"
            dest.write_bytes(p.encode_primitive(record))
        with pytest.raises(ValueError):
            pipeline.verify_finished_transport(folder / "study.json", sha)
    assert calls == ["inert-observer"]
