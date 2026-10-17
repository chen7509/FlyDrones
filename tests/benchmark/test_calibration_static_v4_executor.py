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
    # Virtual-reader test only; actual environment/argv joins have separate tests.
    monkeypatch.setattr(p, "current_sdk_invocation", lambda recipe: {"explicit_inert_invocation": True})
    monkeypatch.setattr(
        p,
        "checked_query",
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
    from types import SimpleNamespace

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

    child = Child()
    backend = SimpleNamespace(process=child, streams=[], reader_errors=[])
    if always:
        with pytest.raises(ValueError, match="wait unavailable"):
            p.NativeWindowsBackend.cleanup(backend, child)
    else:
        p.NativeWindowsBackend.cleanup(backend, child)
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
    for name in ("sdk-start.frame", "bootstrap-scope-before.frame", "sdk-preparation-entered.frame"):
        (parent / name).write_bytes(p.encode_primitive({"explicit_inert_receiver_join": True}))
    monkeypatch.setattr(p, "audit_sdk_admission_receipts", lambda *a: None)
    monkeypatch.setattr(executor, "ROOT", tmp_path)
    monkeypatch.setattr(executor, "OUT", parent)
    monkeypatch.setattr(executor, "native_path", native)
    monkeypatch.setattr(executor, "production_boundary", lambda: None)
    # This fixture scopes the real receiver/lifecycle join. The separately
    # exercised actual journal auditor has its own retained raw protocols.
    monkeypatch.setattr(p, "audit_identity_journal", lambda *a, **k: None)
    monkeypatch.setattr(executor.NativeWindowsBackend, "sources", lambda self: dict(recipe["source_sha256"]))
    calls = []

    def observe(argv, **kwargs):
        calls.append("inert-observer")
        request = p.decode_primitive((parent / "post-request.frame").read_bytes())
        post = copy.deepcopy(pre)
        post.update(phase="post", recipe_sha256=p.sha256(p.encode_primitive(request["recipe"])))
        records = {r["requested"]: r for r in post["files_before"]}
        for requested in request["recipe"]["files"]:
            if requested in records:
                continue
            path = tmp_path / requested.removeprefix("/fixture/project/")
            data = path.read_bytes()
            record = copy.deepcopy(pre["files_before"][0])
            record.update(requested=native(path), resolved=native(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            record["identity"]["size"] = record["path_identity"]["size"] = len(data)
            records[native(path)] = record
        post["files_before"] = [records[path] for path in request["recipe"]["files"]]
        post["files_after"] = copy.deepcopy(post["files_before"])
        (parent / "postidentity.frame").write_bytes(p.encode_primitive(post))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    def outer(argv, **kwargs):
        result = observe(argv, **kwargs)
        return dict(
            exit=result.returncode,
            stdout_hex=result.stdout.hex(),
            stderr_hex=result.stderr.hex(),
            error=None,
            reader_complete=True,
            cleanup=dict(waited=True),
        )

    monkeypatch.setattr(executor, "bounded_windows_command", outer)
    monkeypatch.setattr(executor, "load_windows_software_release", lambda: None)
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


def test_claim_must_validate_before_any_sdk_marker_output(monkeypatch):
    p = importlib.import_module("tools.benchmark.static_v4_bootstrap")
    recipe, scope, pre, claim, *_ = receipt_fixture(p)
    from types import SimpleNamespace

    monkeypatch.setattr(p, "os", SimpleNamespace(getuid=lambda: 1000, getpid=lambda: 99))
    claim["nonce"] = "d" * 64
    writes = []
    monkeypatch.setattr(
        p, "current_receipts", lambda: ({"parent": "/inert", "marker": "/inert/start"}, recipe, pre, claim, scope)
    )
    monkeypatch.setattr(p, "file_pin", lambda path: pre["files_before"][0])
    monkeypatch.setattr(p, "write_exclusive", lambda path, value: writes.append(path))
    monkeypatch.setattr(p, "revalidate_sdk_reference", lambda ticket: (_ for _ in ()).throw(ValueError("late invalid claim")))
    monkeypatch.setattr(p.time, "monotonic_ns", lambda: 3)
    with pytest.raises(ValueError):
        p.enter_sdk()
    assert writes == []


def test_start_exception_retains_backend_owned_child_cleanup():
    p = importlib.import_module("tools.benchmark.static_v4_executor")
    calls = []

    class Backend:
        process = None

        def admission(self, n):
            return dict(windows_available=2**30, wsl_available=2**30, competitor_count=0, docker_exit=0, docker_empty=True)

        def record(self, *a):
            pass

        def prepare_identity(self):
            pass

        def scope_absent(self):
            return dict(exit=0, absent=True)

        def claim(self):
            pass

        def start(self):
            self.process = "owned-inert-handle"
            raise ValueError("post-acquisition writer primary")

        def cleanup(self, process):
            calls.append(process)

        def release(self):
            calls.append("fresh-release")
            return {"escaped_closure": "UNKNOWN"}

    with pytest.raises(ValueError, match="post-acquisition writer primary"):
        p.run_protocol(Backend())
    assert calls == ["owned-inert-handle", "fresh-release"]


@pytest.mark.parametrize("fallback_fails", [False, True])
def test_primitive_observer_attempts_independent_bounded_failure_fallback(fallback_fails):
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    first = ValueError("first observer error")
    kept = []

    def body(emit):
        raise first

    def emit(value):
        raise OSError("primary writer unavailable")

    def fallback(value):
        kept.append(value)
        if fallback_fails:
            raise OSError("fallback unavailable")

    with pytest.raises(ValueError, match="first observer error") as caught:
        p.retain_observation(body, emit, fallback=fallback)
    assert caught.value is first and len(kept) == 1
    assert kept[0]["primary_error"] == repr(first) and kept[0]["canonical_terminal_persisted"] is False
    if fallback_fails:
        assert any("durability UNKNOWN" in n for n in first.__notes__)


@pytest.mark.parametrize("mode", ["success", "mutation", "query-primary-postpin-fails"])
def test_observer_checked_query_pins_current_tool_and_retains_primary(monkeypatch, mode):
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    pins = []

    def witness(path):
        pins.append(path)
        if mode == "query-primary-postpin-fails" and len(pins) == 2:
            raise OSError("postpin secondary")
        return {"requested": path, "sha256": ("b" if mode == "mutation" and len(pins) == 2 else "a") * 64}

    monkeypatch.setattr(p, "tool_witness", witness, raising=False)
    monkeypatch.setattr(
        p,
        "query",
        lambda *a: dict(
            error="query primary" if mode == "query-primary-postpin-fails" else None,
            exit=1 if mode == "query-primary-postpin-fails" else 0,
            stdout_hex="",
            stderr_hex="",
        ),
    )
    row = p.checked_query(["/inert/tool", "--version"], {"PATH": "/inert"})
    assert pins == ["/inert/tool", "/inert/tool"]
    if mode == "success":
        assert row["tool_before"] == row["tool_after"] and row["error"] is None
    elif mode == "mutation":
        assert "tool changed" in row["error"]
    else:
        assert row["error"] == "query primary" and "postpin secondary" in str(row["observer_notes"])


@pytest.mark.parametrize("mode", ["matching", "wrong", "nonzero", "gone", "duplicate"])
def test_actual_manager_release_uses_only_fresh_matching_scope(tmp_path, monkeypatch, mode):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_executor")
    identity = importlib.import_module("tools.benchmark.static_v4_identity")
    unit = "fly-calibration-prepare-" + "a" * 24 + ".scope"
    cg = "/user.slice/" + unit
    old = dict(InvocationID="b" * 32, ControlGroup=cg)
    (tmp_path / "bootstrap-scope-before.frame").write_bytes(identity.encode_primitive(old))
    monkeypatch.setattr(p, "OUT", tmp_path)
    calls = []

    class Backend:
        unit = "fly-calibration-prepare-" + "a" * 24 + ".scope"
        control = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/1000"}
        stopped = False

        def manager(self, argv):
            calls.append(argv)
            if argv[0] == "stop":
                self.stopped = True
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            text = (
                "LoadState=not-found\nInvocationID=\nControlGroup=\n"
                if mode == "gone" or self.stopped
                else "LoadState=loaded\nInvocationID="
                + ("c" * 32 if mode == "wrong" else old["InvocationID"])
                + "\nControlGroup="
                + cg
                + "\n"
            )
            if mode == "duplicate":
                text += "InvocationID=" + old["InvocationID"] + "\n"
            return SimpleNamespace(returncode=1 if mode == "nonzero" else 0, stdout=text.encode(), stderr=b"")

        def record(self, *a):
            pass

        def remote(self, argv):
            calls.append("owned-CG-absence")
            return SimpleNamespace(returncode=0, stdout=b"False\n", stderr=b"")

    if mode in ("wrong", "nonzero", "duplicate"):
        with pytest.raises(ValueError):
            p.NativeWindowsBackend.release(Backend())
        assert len(calls) == 1
    else:
        assert p.NativeWindowsBackend.release(Backend())["escaped_closure"] == "UNKNOWN"
        assert len(calls) == (2 if mode == "gone" else 4)


def test_fixed_recipe_builder_preserves_complete_declared_groups_without_native_calls():
    p = importlib.import_module("tools.benchmark.static_v4_recipe")
    request = p.build_fixed_request()
    assert request["schema"] == "static-recipe-request-v4"
    groups = request["coverage"]
    assert len(groups["sealed-scene"]) == 45 and len(groups["agent-cache"]) == 14
    assert groups["agent-bundle"] and groups["native-candidates"] and groups["catalog"]
    assert len(groups["project-source"]) == len(request["source_sha256"])
    for required in (
        "calibration_capture_pipeline_v4.py",
        "bound_resource_graph.py",
        "audit_live_wire_resources.py",
        "capture_contract.py",
        "static_v4_recipe.py",
        "static_v4_executor.py",
    ):
        assert any(path.endswith("/" + required) for path in groups["project-source"])
    p.audit_recipe_request(request)
    assert request["native_preidentity_observed"] is False and request["scene_copied"] is False


@pytest.mark.parametrize("mutation", ["scene", "agent", "source", "tool", "metadata", "budgets", "extra", "missing-role"])
def test_fixed_recipe_group_omission_cannot_be_hidden_by_recomputing_union(mutation):
    import copy

    p = importlib.import_module("tools.benchmark.static_v4_recipe")
    request = copy.deepcopy(p.build_fixed_request())
    if mutation in ("scene", "agent", "source", "tool"):
        role = {"scene": "sealed-scene", "agent": "agent-cache", "source": "project-source", "tool": "tools"}[mutation]
        request["coverage"][role].pop()
    elif mutation == "metadata":
        request["metadata_protocol"]["distributions"].pop()
    elif mutation == "budgets":
        request["static_limits"]["memory.max"] = "1073741824"
    elif mutation == "extra":
        request["coverage"]["native-candidates"].append("/arbitrary/new.so")
    else:
        request["coverage"].pop("px4-inputs")
    request["files"] = sorted({path for values in request["coverage"].values() for path in values})
    with pytest.raises(ValueError):
        p.audit_recipe_request(request)


def test_native_metadata_collection_is_fresh_primitive_and_retains_all_notices(monkeypatch):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    protocol = importlib.import_module("tools.benchmark.static_v4_recipe").build_fixed_request()["metadata_protocol"]
    root = protocol["roots"][0]
    names = [name + "-1.0.dist-info" for name in protocol["distributions"]]
    calls = []
    api = SimpleNamespace(
        listdir=lambda path: names if path == root else [],
        path=SimpleNamespace(isdir=lambda path: True, isfile=lambda path: False),
        walk=lambda path, **kwargs: [(path, [], ["METADATA", "LICENSE"])],
        lstat=lambda path: SimpleNamespace(st_mode=0o040755 if path.startswith(root) else 0o100644),
    )
    monkeypatch.setattr(p, "os", api)
    monkeypatch.setattr(p, "walk", lambda path: (path, []))
    monkeypatch.setattr(p, "file_pin", lambda path, **kwargs: dict(requested=path, sha256="a" * 64))

    def checked(argv, env):
        calls.append(argv)
        return dict(
            exit=0,
            error=None,
            reader_complete=True,
            cleanup=dict(waited=True),
            stderr_hex="",
            stdout_hex=(
                b"libc6:amd64: /usr/bin/ldd\n" if argv[1] == "-S" else b"/usr/share/gz/gz-sim8/media/gazebo.material\n"
            ).hex(),
        )

    monkeypatch.setattr(p, "checked_query", checked)
    events = []
    result = p.collect_installed_metadata(
        dict(
            source_root="/inert/project",
            metadata_protocol=protocol,
            coverage={"tools": ["/usr/bin/ldd"], "native-candidates": []},
        ),
        events.append,
    )
    assert result["coverage"]["installed-notices"] == ["/usr/share/doc/libc6/copyright"]
    assert len(result["coverage"]["python-package-metadata"]) == 10
    assert result["coverage"]["installed-packages"] == ["/var/lib/dpkg/status"]
    assert calls == [["/usr/bin/dpkg-query", "-S", "--", "/usr/bin/ldd"], ["/usr/bin/dpkg-query", "-L", "--", "libc6:amd64"]]
    assert result["distribution_names"] == protocol["distributions"] and events


@pytest.mark.parametrize("mutation", ["none", "omitted-query", "tool", "input", "clock", "cwd", "stdout", "terminal"])
def test_native_identity_auditor_replays_actual_journal_not_digest_labels(mutation):
    import copy

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, scope, value, *_ = receipt_fixture(p)
    tool = copy.deepcopy(value["files_before"][0])
    tool.update(requested="/usr/bin/sha256sum", resolved="/usr/bin/sha256sum")
    recipe["files"].append(tool["requested"])
    value["files_before"].append(tool)
    value["files_after"] = copy.deepcopy(value["files_before"])
    value["recipe_sha256"] = p.sha256(p.encode_primitive(recipe))
    base = recipe["source_root"] + "/results/target-bearing-runtime-freeze-v4-dev-1701/preidentity.frame"
    rows = [
        dict(
            kind="hash-tool-bootstrap",
            path=tool["requested"],
            sha256=tool["sha256"],
            identity=tool["identity"],
            reference="/proc/77/fd/30",
        )
    ]
    for phase in ("before", "after"):
        rows.append(dict(kind="file-phase", phase=phase, edge="begin"))
        for number, file in enumerate(value["files_before"]):
            ref = "/proc/77/fd/" + str(number + 3)
            q = dict(
                argv=[tool["requested"], "--", ref],
                environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                cwd=recipe["source_root"],
                stdout_hex=(file["sha256"] + "  " + ref + "\n").encode().hex(),
                stderr_hex="",
                exit=0,
                error=None,
                reader_complete=True,
                cleanup=dict(waited=True),
                started_monotonic_ns=1,
                ended_monotonic_ns=3,
                elapsed_ns=2,
                started_utc="2026-10-15T00:00:00Z",
                ended_utc="2026-10-15T00:00:01Z",
                tool_before=tool,
                tool_after=tool,
                command_started=True,
                input_requested=file["requested"],
                input_identity_before=file["identity"],
                input_identity_after=file["identity"],
                observer_pid=77,
            )
            helper = dict(
                argv=["/proc/77/fd/30", "--", "/proc/77/fd/40"],
                environment=q["environment"],
                cwd=recipe["source_root"],
                exit=0,
                error=None,
                reader_complete=True,
                cleanup=dict(waited=True),
                stdout_hex=(tool["sha256"] + "  /proc/77/fd/40\n").encode().hex(),
                stderr_hex="",
                started_monotonic_ns=0,
                ended_monotonic_ns=1,
                elapsed_ns=1,
                started_utc=q["started_utc"],
                ended_utc=q["ended_utc"],
                root_before=tool,
                root_identity_after=tool["identity"],
                input_identity_before=tool["identity"],
                input_identity_after=tool["identity"],
            )
            rows.append(dict(kind="tool-byte-query", file=copy.deepcopy(tool), query=copy.deepcopy(helper), error=None))
            helper.update(started_monotonic_ns=3, ended_monotonic_ns=4)
            rows.append(dict(kind="tool-byte-query", file=copy.deepcopy(tool), query=copy.deepcopy(helper), error=None))
            rows.append(dict(kind="file-hash-query", query=copy.deepcopy(q)))
            if phase == "after":
                rows.append(dict(kind="final-input-observation", path=file["requested"], file=copy.deepcopy(file), error=None))
        rows.append(dict(kind="file-phase", phase=phase, edge="end"))
    rows.append(dict(kind="hash-tool-final", file=tool))
    target = next(row["query"] for row in rows if row["kind"] == "file-hash-query")
    if mutation == "omitted-query":
        rows.pop(-3)
    elif mutation == "tool":
        target["tool_after"]["sha256"] = "c" * 64
    elif mutation == "input":
        target["input_identity_after"]["inode"] = 500
    elif mutation == "clock":
        target["ended_monotonic_ns"] = 0
    elif mutation == "cwd":
        target["cwd"] = "/wrong"
    elif mutation == "stdout":
        target["stdout_hex"] = bytes.fromhex(target["stdout_hex"]).replace(b"b", b"c").hex()
    reader = {}
    members = []
    for number, row in enumerate(rows, 1):
        ref = base + ".event-" + str(number).zfill(5)
        data = p.encode_primitive(row)
        reader[ref] = data
        members.append(dict(path=ref, bytes=len(data), sha256=p.sha256(data)))
    reader[base + ".event-" + str(len(rows) + 1).zfill(5)] = p.encode_primitive(
        dict(terminal=True, error="failed" if mutation == "terminal" else None)
    )
    value["journal"] = dict(schema="static-identity-query-journal-v4", observer_pid=77, members=members)
    if mutation == "none":
        p.audit_identity_journal(value, recipe=recipe, reader=lambda ref: reader[ref])
    else:
        with pytest.raises(ValueError):
            p.audit_identity_journal(value, recipe=recipe, reader=lambda ref: reader[ref])


@pytest.mark.parametrize("mode", ["normal", "query-error-poststat", "large-tool"])
def test_fresh_tool_hash_uses_owned_bootstrap_descriptor_not_pure_hash_per_file(monkeypatch, mode):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    info = SimpleNamespace(
        st_dev=1, st_ino=2, st_mode=33188, st_size=8020928 if mode == "large-tool" else 4, st_mtime_ns=1, st_ctime_ns=1
    )
    pin = dict(
        requested="/usr/bin/sha256sum",
        resolved="/usr/bin/sha256sum",
        links=[],
        identity=p.identity(info),
        path_identity=p.identity(info),
        bytes=4,
        sha256="b" * 64,
    )
    events = []
    calls = []
    chunks = [b"tool", b""]

    def fstat(fd):
        if mode == "query-error-poststat" and fd == 3 and calls:
            raise OSError("root poststat secondary")
        return info

    monkeypatch.setattr(p, "_HASH_ROOT", dict(pin=pin, fd=3, reference="/proc/77/fd/3", emit=events.append), raising=False)
    monkeypatch.setattr(p, "walk", lambda path: (path, []))
    monkeypatch.setattr(
        p,
        "os",
        SimpleNamespace(
            open=lambda *a: 4,
            fstat=fstat,
            stat=lambda path: info,
            close=lambda fd: None,
            read=lambda fd, n: chunks.pop(0),
            getpid=lambda: 77,
            O_RDONLY=0,
            O_CLOEXEC=1,
            O_NONBLOCK=2,
        ),
    )
    monkeypatch.setattr(p, "sha256", lambda data: (_ for _ in ()).throw(AssertionError("per-file pure hash regression")))

    def query(argv, env):
        calls.append(argv)
        return dict(
            argv=argv,
            environment=env,
            exit=1 if mode == "query-error-poststat" else 0,
            error="root-query-primary" if mode == "query-error-poststat" else None,
            reader_complete=True,
            cleanup=dict(waited=True),
            stdout_hex=b"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc  /proc/77/fd/4\n".hex(),
            stderr_hex="",
        )

    monkeypatch.setattr(p, "query", query)
    if mode == "query-error-poststat":
        with pytest.raises(ValueError, match="root-query-primary") as caught:
            p.tool_witness("/usr/bin/readelf")
        assert "root poststat secondary" in str(caught.value.__notes__) and events
        return
    actual = p.tool_witness("/usr/bin/readelf")
    assert actual["sha256"] == "c" * 64 and calls == [["/proc/77/fd/3", "--", "/proc/77/fd/4"]]
    assert events[0]["kind"] == "tool-byte-query" and events[0]["file"] == actual


@pytest.mark.parametrize("change", ["none", "seed", "metadata", "request", "extra"])
def test_materialized_native_recipe_cannot_change_the_reviewed_request(change):
    import copy

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    request = importlib.import_module("tools.benchmark.static_v4_recipe").build_fixed_request()
    native = copy.deepcopy(
        {
            k: request[k]
            for k in (
                "source_root",
                "source_sha256",
                "nonce",
                "unit",
                "sdk_environment",
                "static_limits",
                "versions",
                "expected_bytes",
                "metadata_protocol",
            )
        }
    )
    extra = {
        "installed-packages": ["/var/lib/dpkg/status"],
        "installed-notices": ["/usr/share/doc/libc6/copyright"],
        "package-owner-inputs": ["/usr/bin/ldd"],
        "package-runtime-files": [],
        "python-package-metadata": ["/inert/numpy.dist-info/METADATA"],
        "python-startup": [],
        "python-bytecode-inputs": [],
        "python-runtime-inputs": ["/usr/lib/python3.12/site.py"],
    }
    native.update(
        schema="static-recipe-v4",
        coverage=dict(request["coverage"], **extra),
        request_sha256=p.sha256(p.encode_primitive(request)),
        metadata_observation=dict(
            coverage=copy.deepcopy(extra),
            distribution_names=request["metadata_protocol"]["distributions"],
            transitive_license_certified=False,
        ),
    )
    if change == "seed":
        native["coverage"]["sealed-scene"].pop()
    elif change == "metadata":
        native["metadata_observation"]["distribution_names"] = []
    elif change == "request":
        native["request_sha256"] = "0" * 64
    elif change == "extra":
        native["coverage"]["arbitrary"] = ["/new"]
    native["files"] = sorted({x for rows in native["coverage"].values() for x in rows})
    if change == "none":
        p.audit_materialized_recipe(request, native)
    else:
        with pytest.raises(ValueError):
            p.audit_materialized_recipe(request, native)


def test_observer_file_pin_command_error_stays_primary_over_postpin_and_writer(monkeypatch):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    info = SimpleNamespace(st_dev=1, st_ino=2, st_mode=33188, st_size=4, st_mtime_ns=1, st_ctime_ns=1)
    checks = []
    kept = []

    def fstat(fd):
        checks.append(fd)
        if len(checks) > 1:
            raise OSError("post-input secondary")
        return info

    monkeypatch.setattr(
        p,
        "os",
        SimpleNamespace(
            open=lambda *a: 3,
            fstat=fstat,
            stat=lambda path: info,
            close=lambda fd: None,
            getpid=lambda: 77,
            O_RDONLY=0,
            O_CLOEXEC=1,
            O_NONBLOCK=2,
        ),
    )
    monkeypatch.setattr(p, "walk", lambda path: (path, []))
    monkeypatch.setattr(
        p,
        "checked_query",
        lambda *a: dict(
            exit=1, error="query primary", reader_complete=False, cleanup=dict(waited=True), stderr_hex="", stdout_hex=""
        ),
    )

    def writer(row):
        kept.append(row)
        raise OSError("writer secondary")

    with pytest.raises(ValueError, match="query primary") as caught:
        p.file_pin("/inert/input", emit=writer)
    assert kept and "post-input secondary" in str(caught.value.__notes__) and "writer secondary" in str(caught.value.__notes__)


@pytest.mark.parametrize("change", ["none", "marker", "entry", "sdk-pid", "scope-query", "ticket"])
def test_finished_sdk_admission_joins_actual_marker_scope_entry_and_preparation(change):
    import copy

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, scope, pre, claim, marker, ticket = receipt_fixture(p)
    tool = copy.deepcopy(pre["files_before"][0])
    tool.update(requested="/usr/bin/systemctl", resolved="/usr/bin/systemctl")
    recipe["files"].append(tool["requested"])
    pre["files_before"].append(tool)
    pre["files_after"] = copy.deepcopy(pre["files_before"])
    pre["recipe_sha256"] = p.sha256(p.encode_primitive(recipe))
    claim.update(recipe_sha256=pre["recipe_sha256"], preidentity_sha256=p.sha256(p.encode_primitive(pre)))
    marker["claim_sha256"] = p.sha256(p.encode_primitive(claim))
    ticket.update(
        claim_sha256=marker["claim_sha256"],
        recipe_sha256=claim["recipe_sha256"],
        preidentity_sha256=claim["preidentity_sha256"],
        sdk_start_sha256=p.sha256(p.encode_primitive(marker)),
    )
    scope["query"] = dict(
        argv=["/usr/bin/systemctl", "--user", "show", recipe["unit"], "--property=InvocationID", "--property=ControlGroup"],
        environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/1000"},
        exit=0,
        error=None,
        reader_complete=True,
        cleanup=dict(waited=True),
        stderr_hex="",
        stdout_hex=("InvocationID=" + scope["InvocationID"] + "\nControlGroup=" + scope["ControlGroup"] + "\n").encode().hex(),
        tool_before=tool,
        tool_after=tool,
        ended_monotonic_ns=2,
    )
    entered = dict(schema="static-sdk-preparation-entry-v4", pid=99, ticket_sha256=p.sha256(p.encode_primitive(ticket)))
    scope["invocation"] = dict(
        environment=recipe["sdk_environment"],
        argv=[recipe["source_root"] + "/tools/benchmark/static_v4_bootstrap.py", "--admitted-once"],
        cwd=recipe["source_root"],
        executable="/usr/bin/python3",
        no_site=True,
        no_bytecode=True,
        sys_path=[recipe["source_root"] + "/tools/benchmark", recipe["source_root"] + "/src", recipe["source_root"]],
    )
    prep = dict(sdk_ticket=copy.deepcopy(ticket), sdk_pid=99)
    if change == "marker":
        marker["nonce"] = "e" * 64
    elif change == "entry":
        entered["ticket_sha256"] = "e" * 64
    elif change == "sdk-pid":
        prep["sdk_pid"] = 100
    elif change == "scope-query":
        scope["query"]["stdout_hex"] = b"InvocationID=wrong\n".hex()
    elif change == "ticket":
        prep["sdk_ticket"]["sdk_start_sha256"] = "e" * 64
    if change == "none":
        p.audit_sdk_admission_receipts(recipe, pre, claim, scope, marker, entered, prep)
    else:
        with pytest.raises(ValueError):
            p.audit_sdk_admission_receipts(recipe, pre, claim, scope, marker, entered, prep)


@pytest.mark.parametrize("entry", ["start", "remote"])
def test_direct_native_backend_launch_methods_deny_pytest_before_effects(monkeypatch, entry):
    import subprocess
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_executor")

    def denied(*a, **k):
        raise AssertionError("backend effect before pytest gate")

    monkeypatch.setattr(subprocess, "run", denied)
    fake = SimpleNamespace(
        control={"PATH": "/inert"}, unit="inert.scope", recipe={"sdk_environment": {"PATH": "/inert"}}, record=denied
    )
    with pytest.raises(ValueError, match="pytest"):
        if entry == "start":
            p.NativeWindowsBackend.start(fake)
        else:
            p.NativeWindowsBackend.remote(fake, ["/inert"])


def test_native_owned_cleanup_waits_exited_handle_and_closes_owned_readers():
    import io
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_executor")
    waits = []

    class Child:
        stdout = io.BytesIO(b"partial")
        stderr = io.BytesIO()

        def poll(self):
            return 0

        def wait(self, timeout):
            waits.append(timeout)
            return 0

    child = Child()
    backend = SimpleNamespace(process=child, streams=[], reader_errors=[])
    result = p.NativeWindowsBackend.cleanup(backend, child)
    assert waits == [5] and child.stdout.closed and child.stderr.closed
    assert result["waited"] is True and result["reader_complete"] is True


@pytest.mark.parametrize("mode", ["normal", "cap", "timeout"])
def test_metadata_windows_runner_has_hard_stream_cap_partial_and_owned_timeout(mode):
    import io
    import time
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_executor")
    calls = []

    class Child:
        pid = 123
        stdout = io.BytesIO(b"x" * (2 * 1024**2 + 1) if mode == "cap" else b"prefix")
        stderr = io.BytesIO()
        code = None if mode == "timeout" else 0

        def poll(self):
            return self.code

        def wait(self, timeout):
            calls.append("wait")
            return self.code

        def terminate(self):
            calls.append("terminate")
            self.code = 0

        def kill(self):
            calls.append("kill")
            self.code = 0

    ticks = [0]

    def now():
        ticks[0] += 20 if mode == "timeout" else 0.001
        return ticks[0]

    row = p.bounded_windows_command(
        ["inert"], cwd=ROOT, timeout=15, popen=lambda *a, **k: Child(), clock=SimpleNamespace(monotonic=now, sleep=time.sleep)
    )
    assert row["cleanup"]["waited"] and row["cleanup"]["escaped_closure"] == "UNKNOWN"
    if mode == "normal":
        assert row["error"] is None and bytes.fromhex(row["stdout_hex"]) == b"prefix"
    elif mode == "cap":
        assert "cap" in row["error"] and len(bytes.fromhex(row["stdout_hex"])) == 2 * 1024**2
    else:
        assert "deadline" in row["error"] and "terminate" in calls


@pytest.mark.parametrize("change", ["none", "native-ready", "request", "code", "archive", "extra"])
def test_reviewed_software_release_is_exact_handoff_not_native_admission(change):
    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, *_ = receipt_fixture(p)
    payload = p.encode_primitive(recipe)
    release = dict(
        schema="static-v4-reviewed-software-release-v1",
        request_sha256=p.sha256(payload),
        source_sha256=recipe["source_sha256"],
        archive="evidence/static-v4-executor-completion-dev-1701.zip",
        archive_sha256="c" * 64,
        review_sha256="d" * 64,
        fixpass_sha256="e" * 64,
        Task4_software_complete=True,
        native_dispatch_ready=False,
    )
    if change == "native-ready":
        release["native_dispatch_ready"] = True
    elif change == "request":
        release["request_sha256"] = "f" * 64
    elif change == "code":
        release["source_sha256"] = {}
    elif change == "archive":
        release["archive"] = "evidence/other.zip"
    elif change == "extra":
        release["allow_native"] = True
    if change == "none":
        p.audit_software_release(release, payload)
    else:
        with pytest.raises(ValueError):
            p.audit_software_release(release, payload)


def test_metadata_command_writer_failure_preserves_query_error_with_independent_raw_fallback(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_executor")
    row = dict(exit=1, error="query primary", stdout_hex=b"partial".hex(), stderr_hex="", cleanup=dict(waited=True))
    monkeypatch.setattr(p, "bounded_windows_command", lambda *a, **k: row)
    monkeypatch.setattr(p, "OUT", tmp_path)

    def bad(*a):
        raise OSError("metadata writer secondary")

    backend = SimpleNamespace(remote_counter=0, record=bad)
    with pytest.raises(ValueError, match="query primary") as caught:
        p.NativeWindowsBackend.recorded_command(backend, ["inert"], 15)
    assert "metadata writer secondary" in str(caught.value.__notes__)
    assert json.loads((tmp_path / "metadata-fallback-001.json").read_bytes())["stdout_hex"] == b"partial".hex()


def test_production_admission_retains_separate_host_samples_without_resampling(tmp_path, monkeypatch):
    import json
    import sys
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_executor")
    reads = []
    fakeps = SimpleNamespace(
        Process=lambda: SimpleNamespace(parents=lambda: []),
        process_iter=lambda *a: [],
        virtual_memory=lambda: reads.append("memory") or SimpleNamespace(available=2**31),
    )
    monkeypatch.setitem(sys.modules, "psutil", fakeps)
    monkeypatch.setattr(p, "OUT", tmp_path)
    linux = dict(
        available=2**31, rows=[], started_monotonic_ns=1, memory_monotonic_ns=2, ended_monotonic_ns=3, utc="2026-10-15T00:00:00Z"
    )

    class Backend:
        def remote(self, argv, *a, **kwargs):
            assert "json" not in argv[-1] and "monotonic_ns" in argv[-1]
            return SimpleNamespace(returncode=0, stdout=repr(linux).encode(), stderr=b"")

        def remote_docker(self):
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    backend = Backend()
    backend.json = json
    value = p.NativeWindowsBackend.admission(backend, 1)
    private = json.loads((tmp_path / "LOCAL_UNPUBLISHED-admission-1.json").read_bytes())
    assert reads == ["memory"] and private["windows_memory"]["available"] == value["windows_available"]
    assert value["linux_clock"]["memory_monotonic_ns"] == 2 and value["windows_clock"]["start"] <= value["windows_clock"]["end"]


def test_windows_release_rejects_rehashed_archive_with_different_recipe_bytes(tmp_path, monkeypatch):
    import hashlib
    import zipfile

    p = importlib.import_module("tools.benchmark.static_v4_executor")
    primitive = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, *_ = receipt_fixture(primitive)
    raw = tmp_path / "results/static-v4-executor-completion-dev-1701"
    raw.mkdir(parents=True)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    template = primitive.encode_primitive(recipe)
    (raw / "reviewed-recipe.frame").write_bytes(template)
    (raw / "independent-review.md").write_bytes(b"EXPLICIT_INERT_REVIEW")
    (raw / "executor-fix-pass.md").write_bytes(b"EXPLICIT_INERT_FIX")
    archive = evidence / "static-v4-executor-completion-dev-1701.zip"
    with zipfile.ZipFile(archive, "x") as z:
        z.writestr("results/static-v4-executor-completion-dev-1701/reviewed-recipe.frame", b"wrong recipe")
    release = dict(
        schema="static-v4-reviewed-software-release-v1",
        request_sha256=primitive.sha256(template),
        source_sha256=recipe["source_sha256"],
        archive="evidence/static-v4-executor-completion-dev-1701.zip",
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        review_sha256=hashlib.sha256(b"EXPLICIT_INERT_REVIEW").hexdigest(),
        fixpass_sha256=hashlib.sha256(b"EXPLICIT_INERT_FIX").hexdigest(),
        Task4_software_complete=True,
        native_dispatch_ready=False,
    )
    (evidence / "static-v4-executor-completion-release.frame").write_bytes(primitive.encode_primitive(release))
    monkeypatch.setattr(p, "ROOT", tmp_path)
    monkeypatch.setattr(p, "native_path", lambda root: recipe["source_root"])
    monkeypatch.setattr(p.NativeWindowsBackend, "sources", lambda self: recipe["source_sha256"])
    with pytest.raises(ValueError):
        p.load_windows_software_release()


def test_project_bytecode_inputs_are_freshly_listed_without_creating_caches(monkeypatch):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    roots = []

    def walk(root, **kwargs):
        roots.append(root)
        return [(root + "/__pycache__", [], ["loaded.cpython-312.pyc", "other.txt"])]

    monkeypatch.setattr(p, "os", SimpleNamespace(walk=walk))
    rows = p.collect_project_bytecode("/inert/project")
    assert len(rows) == 3 and all(path.endswith(".pyc") for path in rows)
    assert roots == ["/inert/project/" + part for part in ("src/flydrones", "tools/benchmark", "tools/connectome")]


def test_owned_cleanup_wait_error_still_closes_retained_raw_pipes():
    import io
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_executor")

    class Child:
        stdout = io.BytesIO()
        stderr = io.BytesIO()

        def poll(self):
            return 0

        def wait(self, timeout):
            raise OSError("own wait primary")

    child = Child()
    backend = SimpleNamespace(process=child, streams=[], reader_errors=[])
    with pytest.raises(OSError, match="own wait primary"):
        p.NativeWindowsBackend.cleanup(backend, child)
    assert child.stdout.closed and child.stderr.closed


@pytest.mark.parametrize("reason", ["new-pth", "new-project-cache"])
def test_review_sdk_gate_rechecks_namespace_before_current_pins(monkeypatch, reason):
    p = importlib.import_module("tools.benchmark.static_v4_bootstrap")

    def changed(recipe):
        raise ValueError(reason)

    monkeypatch.setattr(p, "audit_metadata_inventory", changed)
    monkeypatch.setattr(p, "with_hash_root", lambda body, emit: body(emit))
    monkeypatch.setattr(p, "write_exclusive", lambda *a: None)
    monkeypatch.setattr(p, "file_pin", lambda *a, **k: {})
    with pytest.raises(ValueError, match=reason):
        p.run_current_pin_gate({"files": []}, {"parent": "/inert"}, "preimport")


@pytest.mark.parametrize("mode", ["early-file", "first-writer", "final-file"])
def test_review_observer_always_attempts_every_final_input_and_preserves_primary(monkeypatch, mode):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, scope, pre, *_ = receipt_fixture(p)
    recipe["files"] += ["/inert/second"]
    fixed = {
        "parent": "/inert",
        "pre": "/inert/preidentity.frame",
        "post": "/inert/postidentity.frame",
        "recipe": "/inert/recipe.frame",
        "request": "/inert/recipe-request.frame",
    }
    kept = {}
    calls = []
    failures = []
    monkeypatch.setattr(p, "observer_boundary", lambda: None)
    monkeypatch.setattr(
        p,
        "sys",
        SimpleNamespace(
            flags=SimpleNamespace(no_site=True, dont_write_bytecode=True), builtin_module_names=("time",), modules={}
        ),
    )
    monkeypatch.setattr(p, "fixed_paths", lambda: fixed)
    monkeypatch.setattr(p, "source_root", lambda: recipe["source_root"])
    monkeypatch.setattr(p, "os", SimpleNamespace(getcwd=lambda: recipe["source_root"], getpid=lambda: 77, getuid=lambda: 1000))
    monkeypatch.setattr(
        p,
        "read_bytes",
        lambda path: (
            p.encode_primitive({"initial_recipe_sha256": p.sha256(p.encode_primitive(recipe)), "recipe": recipe})
            if path.endswith("post-request.frame")
            else p.encode_primitive(recipe)
        ),
    )
    monkeypatch.setattr(p, "with_hash_root", lambda body, emit: body(emit))
    monkeypatch.setattr(p, "audit_metadata_inventory", lambda recipe: None)

    def writer(path, value):
        kept[path] = value
        if mode == "first-writer" and path.endswith("event-00001") and not failures:
            failures.append("first")
            raise OSError("first writer primary")

    monkeypatch.setattr(p, "write_exclusive", writer)

    def pin(path, **kwargs):
        calls.append(path)
        if not failures:
            failures.append("first")
            raise ValueError("first file primary")
        if mode == "final-file" and path == recipe["files"][0]:
            raise OSError("final file secondary")
        return dict(requested=path, sha256="b" * 64)

    monkeypatch.setattr(p, "file_pin", pin)
    with pytest.raises((ValueError, OSError), match="first (file|writer) primary"):
        p.observe(fixed["recipe"], fixed["post"])
    assert calls[-2:] == recipe["files"]
    final = [v for v in kept.values() if isinstance(v, dict) and v.get("kind") == "final-input-observation"]
    assert len(final) == 2 and final[-1]["file"]["requested"] == recipe["files"][-1]


@pytest.mark.parametrize("change", ["HOME", "extra"])
def test_review_production_recipe_rejects_actual_environment_before_sdk_effects(monkeypatch, change):
    import copy
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_bootstrap")
    request = importlib.import_module("tools.benchmark.static_v4_recipe").build_fixed_request()
    root = request["source_root"]
    # Isolate the actual invocation join; materialization membership has separate real auditor tests.
    native = {
        k: copy.deepcopy(request[k])
        for k in (
            "source_root",
            "source_sha256",
            "nonce",
            "unit",
            "sdk_environment",
            "static_limits",
            "versions",
            "expected_bytes",
            "metadata_protocol",
        )
    }
    native.update(
        schema="static-recipe-v4",
        files=request["files"],
        coverage=request["coverage"],
        request_sha256=p.sha256(p.encode_primitive(request)),
        metadata_observation={},
    )
    env = dict(request["sdk_environment"])
    env["HOME" if change == "HOME" else "UNDECLARED_PYTHON_INPUT"] = "wrong"
    monkeypatch.setattr(p, "source_root", lambda: root)
    monkeypatch.setattr(p, "read_bytes", lambda path: p.encode_primitive(request))
    monkeypatch.setattr(p, "audit_materialized_recipe", lambda *a: None)
    monkeypatch.setattr(p, "audit_metadata_inventory", lambda *a: None)

    def walk(part):
        return [
            (
                part,
                [],
                [
                    n[len(part) - len(root) :].lstrip("/")
                    for n in request["source_sha256"]
                    if (root + "/" + n).startswith(part + "/")
                ],
            )
        ]

    monkeypatch.setattr(p, "os", SimpleNamespace(environ=env, getcwd=lambda: root, walk=walk))
    with pytest.raises(ValueError, match="actual SDK environment"):
        p.production_recipe(native)


def test_review_second_resource_refusal_after_preidentity_is_consumed():
    p = importlib.import_module("tools.benchmark.static_v4_executor")
    events = []

    class B:
        consumed = False

        def admission(self, n):
            return dict(
                windows_available=2**30 if n == 1 else 0,
                wsl_available=2**30,
                competitor_count=0,
                docker_exit=0,
                docker_empty=True,
            )

        def record(self, name, value):
            events.append((name, dict(value)))

        def prepare_identity(self):
            self.consumed = True

        def scope_absent(self):
            return dict(exit=0, absent=True)

    result = p.run_protocol(B())
    assert result["consumed"] is True and result["state"] == "REFUSED_CONSUMED_PREIDENTITY"


def test_review_external_python_runtime_membership_is_collected_without_import(monkeypatch):
    from types import SimpleNamespace

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    dirs = {
        "/usr/lib/python3.12": (["json", "__pycache__"], ["site.py"]),
        "/usr/lib/python3.12/json": ([], ["__init__.py"]),
        "/usr/lib/python3.12/__pycache__": ([], ["site.cpython-312.pyc"]),
        "/usr/local/lib/python3.12/dist-packages": (["numpy"], []),
        "/usr/local/lib/python3.12/dist-packages/numpy": ([], ["__init__.py", "_core.so"]),
    }
    monkeypatch.setattr(
        p,
        "os",
        SimpleNamespace(
            path=SimpleNamespace(isdir=lambda path: path in dirs, isfile=lambda path: False),
            walk=lambda path, **kwargs: (
                (folder, *values) for folder, values in dirs.items() if folder == path or folder.startswith(path + "/")
            ),
            lstat=lambda path: SimpleNamespace(st_mode=0o040755),
        ),
    )
    monkeypatch.setattr(p, "sys", SimpleNamespace(path=["/usr/lib/python3.12"]))
    result = p.collect_python_runtime(
        {"source_root": "/inert/project", "metadata_protocol": {"roots": ["/usr/local/lib/python3.12/dist-packages"]}}
    )
    assert {
        "/usr/lib/python3.12/site.py",
        "/usr/lib/python3.12/json/__init__.py",
        "/usr/lib/python3.12/__pycache__/site.cpython-312.pyc",
        "/usr/local/lib/python3.12/dist-packages/numpy/_core.so",
    } <= set(result["files"])


@pytest.mark.parametrize("origin", ["/usr/lib/python3.12/site.py", "/usr/lib/python3.12/__pycache__/site.cpython-312.pyc"])
def test_review_external_python_prepin_survives_sdk_and_finished_receipt_join(monkeypatch, origin):
    import copy

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, scope, pre, claim, marker, ticket = receipt_fixture(p)
    # Actual independent materializer uses explicit inert installed-inventory protocol.
    request = importlib.import_module("tools.benchmark.static_v4_recipe").build_fixed_request()
    roles = {
        "installed-packages": ["/var/lib/dpkg/status"],
        "installed-notices": ["/usr/share/doc/libc6/copyright"],
        "package-owner-inputs": ["/usr/bin/python3"],
        "package-runtime-files": [],
        "python-package-metadata": ["/inert/numpy.dist-info/METADATA"],
        "python-startup": [],
        "python-bytecode-inputs": [],
        "python-runtime-inputs": [origin],
    }
    observation = dict(
        coverage=roles, distribution_names=request["metadata_protocol"]["distributions"], transitive_license_certified=False
    )
    monkeypatch.setattr(p, "source_root", lambda: request["source_root"])
    monkeypatch.setattr(p, "collect_installed_metadata", lambda request, emit: copy.deepcopy(observation))
    materialized = p.materialize_recipe_request(request, lambda row: None)
    assert origin in materialized["files"] and materialized["coverage"]["python-runtime-inputs"] == [origin]
    # Real claim/admission and finished-native auditors share the resulting external input.
    # Small native receipt protocol keeps these joins independent of large toy tool/graph backends.
    external = copy.deepcopy(pre["files_before"][0])
    external.update(requested=origin, resolved=origin)
    recipe["files"].append(origin)
    pre["files_before"].append(external)
    pre["files_after"] = copy.deepcopy(pre["files_before"])
    pre["recipe_sha256"] = p.sha256(p.encode_primitive(recipe))
    claim.update(recipe_sha256=pre["recipe_sha256"], preidentity_sha256=p.sha256(p.encode_primitive(pre)))
    p.validate_sdk_claim(claim, actual_scope=scope, recipe=recipe, preidentity=pre, now=pre["ended_monotonic_ns"])
    child = dict(schema="static-child-exit-v4", exit=0, waited=True, claim_sha256=p.sha256(p.encode_primitive(claim)))
    post = copy.deepcopy(pre)
    post["phase"] = "post"
    post["recipe_sha256"] = p.sha256(p.encode_primitive(recipe))
    joined = p.audit_finished_native_receipts(recipe, pre, post, claim, child)
    assert external in joined["files"]
    # An originally unpinned outside Python module remains rejected even with coherent hashes.
    recipe["files"].remove(origin)
    pre["files_before"].pop()
    pre["files_after"].pop()
    pre["recipe_sha256"] = p.sha256(p.encode_primitive(recipe))
    claim.update(recipe_sha256=pre["recipe_sha256"], preidentity_sha256=p.sha256(p.encode_primitive(pre)))
    child["claim_sha256"] = p.sha256(p.encode_primitive(claim))
    revised = dict(recipe, files=[row["requested"] for row in post["files_before"]])
    post["recipe_sha256"] = p.sha256(p.encode_primitive(revised))
    with pytest.raises(ValueError, match="outside native input lacks original prepin"):
        p.audit_finished_native_receipts(recipe, pre, post, claim, child)


@pytest.mark.parametrize("change", ["none", "environment", "path", "argv", "flags"])
def test_review_actual_sdk_startup_facts_require_exact_path_and_environment(change):
    import copy

    p = importlib.import_module("tools.benchmark.static_v4_identity")
    recipe, *_ = receipt_fixture(p)
    root = recipe["source_root"]
    facts = dict(
        environment=copy.deepcopy(recipe["sdk_environment"]),
        argv=[root + "/tools/benchmark/static_v4_bootstrap.py", "--admitted-once"],
        cwd=root,
        executable="/usr/bin/python3",
        no_site=True,
        no_bytecode=True,
        sys_path=[root + "/tools/benchmark", root + "/src", root],
    )
    if change == "environment":
        facts["environment"]["HOME"] = "undeclared"
    elif change == "path":
        facts["sys_path"].append("/unpinned")
    elif change == "argv":
        facts["argv"].append("--fixture")
    elif change == "flags":
        facts["no_bytecode"] = False
    if change == "none":
        p.audit_sdk_invocation_facts(facts, recipe, initial=True)
    else:
        with pytest.raises(ValueError):
            p.audit_sdk_invocation_facts(facts, recipe, initial=True)
