"""Actual v4 producer with inert OS/query/filesystem protocols, no native acceptance."""

import builtins
import copy
import hashlib
import importlib
import json
import posixpath
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.benchmark.software_process_boundary import guard_required

RENDERER = "/sdk/libgz-rendering8-ogre2.so.8.2.3"
EXT = "/sdk/_fixture.cpython-312-x86_64-linux-gnu.so"
NUMPY = "/usr/local/lib/python3.12/dist-packages/numpy/_core/_multiarray_umath.cpython-312-x86_64-linux-gnu.so"
OGRE = "/usr/lib/x86_64-linux-gnu/OGRE-2.3"
NAMES = ["libOgreNextMain.so.2.3.1", "libOgreNextHlmsPbs.so.2.3.1", "libOgreNextPlanarReflections.so.2.3.1"]
META = b"ELF Header:\n  Class: ELF64\n  Data: 2's complement, little endian\n  Type: DYN (Shared object file)\n  Machine: Advanced Micro Devices X86-64\n  Number of program headers: 2\nProgram Headers:\n  Type Offset VirtAddr PhysAddr FileSiz MemSiz Flg Align\n  LOAD 0 0 0 1 1 R 1\n  DYNAMIC 0 0 0 1 1 RW 1\n Section to Segment mapping:\nSymbol table '.dynsym' contains 4 entries:\n Num: Value Size Type Bind Vis Ndx Name\n 0: 0 0 NOTYPE LOCAL DEFAULT UND\n 1: 0 0 NOTYPE GLOBAL DEFAULT UND PyDict_New\n 2: 0 0 NOTYPE WEAK DEFAULT UND __gmon_start__\n 3: 10 16 FUNC GLOBAL DEFAULT 1 PyInit__fixture\n"


def test_guard_is_installed_without_process_backend():
    assert guard_required(Path(__file__).name)
    assert subprocess.Popen._execute_child.__name__ == "denied"


class MemoryFiles:
    supported = True

    def __init__(self):
        self.data = {}
        self.ids = {}
        self.dirs = {"/"}
        self.aliases = {}
        self.fd = {}
        self.offset = {}
        self.opened = []

    def add(self, path, data=b"\x7fELFfixture"):
        self.data[path] = data
        self.ids[path] = len(self.ids) + 100
        parent = posixpath.dirname(path)
        while parent != "/":
            self.dirs.add(parent)
            parent = posixpath.dirname(parent)
        return path

    def lstat(self, path):
        if path in self.dirs:
            return SimpleNamespace(st_dev=1, st_ino=1, st_mode=stat.S_IFDIR | 0o755, st_size=0, st_mtime_ns=1, st_ctime_ns=1)
        p = self.aliases.get(path, path)
        data = self.data[p]
        return SimpleNamespace(
            st_dev=1, st_ino=self.ids[p], st_mode=stat.S_IFREG | 0o755, st_size=len(data), st_mtime_ns=1, st_ctime_ns=1
        )

    def file_record(self, path):
        assert path.startswith("/") and ".." not in path.split("/")
        resolved = self.aliases.get(path, path)
        info = self.lstat(path)
        data = self.data[resolved]
        return dict(
            requested=path,
            resolved=resolved,
            links=[],
            identity=dict(device=info.st_dev, inode=info.st_ino, mode=info.st_mode, size=info.st_size, mtime_ns=1, ctime_ns=1),
            path_identity=dict(
                device=info.st_dev, inode=info.st_ino, mode=info.st_mode, size=info.st_size, mtime_ns=1, ctime_ns=1
            ),
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def readlink(self, path):
        raise AssertionError("no links in this explicit integration fixture")

    def open(self, path):
        self.opened.append(path)
        canonical = self.aliases.get(path, path)
        fd = len(self.fd) + 10
        self.fd[fd] = canonical
        self.offset[fd] = 0
        return fd

    def fstat(self, fd):
        return self.lstat(self.fd[fd])

    def read(self, fd, size):
        p = self.fd[fd]
        data = self.data[p][self.offset[fd] : self.offset[fd] + size]
        self.offset[fd] += len(data)
        return data

    def close(self, fd):
        pass


@pytest.fixture
def setup(tmp_path, monkeypatch):
    m = importlib.import_module("tools.benchmark.native_entry_context_v4")
    real_run = m._run
    real_witness = getattr(m, "_file_witness", None)
    paths = importlib.import_module("tools.benchmark.native_loader_paths_v4")
    fs = MemoryFiles()
    tools = dict(ldd="/usr/bin/ldd", readelf="/usr/bin/readelf", python="/usr/bin/python3", loader="/lib64/ld-linux-x86-64.so.2")
    for p in [*tools.values(), RENDERER, EXT, NUMPY, "/sdk/unused.so", *[OGRE + "/" + n for n in NAMES]]:
        fs.add(p)
    root = Path(__file__).resolve().parents[2]
    retained = {
        n: json.loads((root / "results/loader-selected-path-research-dev-1701/retained-v3" / f"query-{n:04d}.json").read_bytes())
        for n in (63, 64)
    }
    numpy_trace = bytes.fromhex(retained[64]["stdout_hex"])
    for line in numpy_trace.decode().splitlines():
        token = line.split(" => ")[-1].strip().split(" (0x")[0]
        if token.startswith("/"):
            # Explicit fixture-only mapping of the three retained spelling aliases.
            canonical = token.replace("/numpy/_core/../../numpy.libs/", "/numpy.libs/")
            if canonical not in fs.data:
                fs.add(canonical)
            fs.aliases[token] = canonical
    context = dict(
        schema="python-extension-context-v1",
        pid=123,
        interpreter=fs.file_record(tools["python"]),
        implementation="cpython",
        version="fixture CPython3.12.3",
        version_info=[3, 12, 3],
        soabi="cpython-312-x86_64-linux-gnu",
        ext_suffix=".cpython-312-x86_64-linux-gnu.so",
        dlopen_flags=2,
        modules=[
            dict(
                name="_fixture",
                origin=fs.file_record(EXT),
                module_file=EXT,
                spec_origin=EXT,
                loader="_frozen_importlib_external.ExtensionFileLoader",
            )
        ],
    )
    observed = copy.deepcopy(context)
    calls = []

    def run(argv, env, cwd):
        calls.append((copy.deepcopy(argv), copy.deepcopy(env), cwd))
        if argv[-1] == "--version":
            data = b"fixture tool version 1\n"
        elif argv[1] == "-d":
            if argv[-1] == EXT:
                data = b"Dynamic section at offset 0x1 contains 1 entries:\n 0x0 (NULL) 0x0\n"
            elif argv[-1] == NUMPY:
                data = bytes.fromhex(retained[63]["stdout_hex"])
            else:
                data = (
                    b"Dynamic section at offset 0x1 contains 5 entries:\n"
                    + b"".join((" 0x1 (NEEDED) Shared library: [" + n + "]\n").encode() for n in NAMES)
                    + (" 0x1d (RUNPATH) Library runpath: [" + OGRE + "]\n 0x0 (NULL) 0x0\n").encode()
                )
        elif argv[1] == "-W":
            data = META
        elif argv[-1] == EXT:
            data = b"\tstatically linked\n"
        elif argv[-1] == NUMPY:
            data = numpy_trace
        else:
            data = b"".join((n + " => " + OGRE + "/" + n + " (0x1234)\n").encode() for n in NAMES)
        return dict(
            argv=argv,
            env=env,
            cwd=cwd,
            pid=321,
            returncode=0,
            error=None,
            timed_out=False,
            output_limited=False,
            owned_child_waited=True,
            reader_complete=True,
            cleanup=dict(exit=0, descendants="unknown"),
            stdout_hex=data.hex(),
            stderr_hex="",
            started_monotonic_ns=100,
            ended_monotonic_ns=200,
            started_utc_ns=1000,
            ended_utc_ns=2000,
            limits=dict(stream_bytes=2097152, timeout_seconds=10, terminate_seconds=5, kill_seconds=5),
        )

    monkeypatch.setattr(m, "file_record", fs.file_record)
    monkeypatch.setattr(m, "tool_paths", lambda: copy.deepcopy(tools))
    monkeypatch.setattr(m, "query_cwd", lambda: "/work")
    monkeypatch.setattr(m, "collect_python_context", lambda: copy.deepcopy(observed))

    def witness(path):
        record = m.file_record(path)
        data = fs.data[record["resolved"]]
        proof = dict(
            schema="native-file-byte-witness-v4",
            prefix_hex=data[:4].hex(),
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            fd_before=copy.deepcopy(record["identity"]),
            fd_after=copy.deepcopy(record["identity"]),
            file_before=copy.deepcopy(record),
            file_after=copy.deepcopy(m.file_record(path)),
        )
        return dict(record, byte_witness=proof)

    monkeypatch.setattr(m, "_file_witness", witness, raising=False)

    def publish_protocol(prepared, final):
        # Inert exclusive file protocol, not an actual Linux atomic link test.
        with Path(final).open("xb") as stream:
            stream.write(Path(prepared).read_bytes())

    monkeypatch.setattr(m, "_publish_completion", publish_protocol)
    monkeypatch.setattr(m, "_run", run)
    monkeypatch.setattr(paths, "_FS", fs)
    entries = {"renderer": [RENDERER], "python": [EXT], "numpy": [NUMPY]}
    return SimpleNamespace(
        m=m,
        fs=fs,
        tools=tools,
        context=context,
        observed=observed,
        calls=calls,
        run=run,
        real_run=real_run,
        real_witness=real_witness,
        entries=entries,
        out=tmp_path / "bill",
        retained=retained,
    )


def produce(s):
    return s.m.discover_entry_context_v4(s.entries, ["/sdk/unused.so"], s.context, [], "/agent/lib", s.out)


def test_real_producer_uses_typed_paths_all_retained_numpy_lines(setup):
    s = setup
    b = produce(s)
    numpy = b["entries"][2]
    assert len(numpy["selected"]) == 10 and sum(".." in p.split("/") for p in numpy["selected"]) == 3
    records = [b["selected_paths"][i] for i in numpy["path_records"]]
    assert [r["raw_path"] for r in records] == numpy["selected"]
    assert len(records) == 10 and all(r["complete"] for r in records)
    assert len({f["requested"] for f in b["files"]}) == len(b["files"])
    assert all(".." not in f["requested"].split("/") for f in b["files"])
    assert b["candidates"][0]["role"] == "candidate_only" and b["candidates"][0]["runtime_closure_qualified"] is False
    assert not any("/sdk/unused.so" in argv for argv, _, _ in s.calls)
    assert b["runtime_closure_qualified"] is False and b["complete"] is True
    s.m.audit_entry_context_bill_v4(b, baseline_files=b["files"], python_context=s.context)


def test_empty_python_selected_keeps_self_and_symbols(setup):
    s = setup
    b = produce(s)
    row = b["entries"][1]
    assert row["entry_kind"] == "python_extension_entry" and row["selected"] == [] and row["dynamic"]["needed"] == []
    assert row["runtime_import_verified"] is False and row["symbols_resolved"] is False
    assert {x["name"] for x in row["elf_metadata"]["symbols"] if x["ndx"] == "UND"} == {"", "PyDict_New", "__gmon_start__"}
    assert EXT in {f["requested"] for f in b["files"]}
    with pytest.raises(ValueError):
        s.m.audit_entry_context_bill_v4(
            b, baseline_files=[f for f in b["files"] if f["requested"] != EXT], python_context=s.context
        )


def test_identical_invocation_across_roles_shares_query_only(setup):
    s = setup
    s.entries["same-explicit-context"] = [RENDERER]
    b = produce(s)
    assert sum(a == [s.tools["ldd"], RENDERER] for a, _, _ in s.calls) == 1
    assert b["entries"][-1]["alias_of"] == 0 and b["entries"][-1]["source_role"] == "same-explicit-context"
    s.m.audit_entry_context_bill_v4(b, baseline_files=b["files"], python_context=s.context)


@pytest.mark.parametrize("kind", ["hardlink", "canonical_alias"])
def test_conflicting_load_spelling_refuses_before_any_query(setup, kind):
    s = setup
    other = "/different/load-origin.so"
    s.fs.add(other)
    if kind == "hardlink":
        s.fs.ids[other] = s.fs.ids[RENDERER]
    else:
        s.fs.aliases[other] = RENDERER
    s.entries["conflicting"] = [other]
    with pytest.raises(ValueError, match="invocation|origin|alias"):
        produce(s)
    assert not s.calls


@pytest.mark.parametrize(
    "fault", ["empty", "extra", "missing", "stderr", "timeout", "cap", "partial", "nonzero", "mutation", "postcontext"]
)
def test_actual_pipeline_retains_index_raw_and_final_attempts(setup, monkeypatch, fault):
    s = setup

    def broken(argv, env, cwd):
        row = s.run(argv, env, cwd)
        if argv == [s.tools["ldd"], NUMPY]:
            if fault == "empty":
                row["stdout_hex"] = ""
            if fault == "extra":
                row["stdout_hex"] += b"unknown\n".hex()
            if fault == "missing":
                row["stdout_hex"] = b"libmissing.so => not found\n".hex()
            if fault == "stderr":
                row["stderr_hex"] = b"error".hex()
            if fault == "timeout":
                row.update(error="fixture timeout", timed_out=True, returncode=-15, cleanup=dict(exit=-15, descendants="unknown"))
            if fault == "cap":
                row["output_limited"] = True
            if fault == "partial":
                row["reader_complete"] = False
            if fault == "nonzero":
                row.update(returncode=1, cleanup=dict(exit=1, descendants="unknown"))
            if fault == "mutation":
                s.fs.data[NUMPY] = b"changed input"
            if fault == "postcontext":
                s.observed["modules"] = []
        return row

    monkeypatch.setattr(s.m, "_run", broken)
    with pytest.raises(ValueError):
        produce(s)
    b = json.loads((s.out / "entry-bill.json").read_bytes())
    assert not b["complete"] and b["error"] and b["entries"][-1]["ldd_query"] == len(b["queries"])
    assert b["queries"][-1]["record"]["stdout_hex"] or fault == "empty"
    assert set(b["final_observations"]) == {"context", "declared", "files", "tools", "candidates", "selected_paths"}
    assert all(v["attempted"] for v in b["final_observations"].values())


@pytest.mark.parametrize(
    "fault", ["phrase", "initializer", "program", "headers", "truncated_symbols", "dynamic", "role", "abi", "origin"]
)
def test_zero_needed_stays_strict(setup, monkeypatch, fault):
    s = setup
    if fault == "role":
        s.context["modules"] = []
        s.observed["modules"] = []
    if fault == "abi":
        s.context["soabi"] = "cpython-311-x86_64-linux-gnu"
    if fault == "origin":
        s.context["modules"][0]["spec_origin"] = "/wrong.so"

    def broken(argv, env, cwd):
        r = s.run(argv, env, cwd)
        data = bytes.fromhex(r["stdout_hex"])
        if argv[-1] == EXT:
            if argv[0] == s.tools["ldd"] and fault == "phrase":
                data += b"\n"
            if argv[1] == "-W":
                if fault == "initializer":
                    data = data.replace(b"PyInit__fixture", b"PyInit_other")
                if fault == "program":
                    data = data.replace(b"DYNAMIC", b"INTERP")
                if fault == "headers":
                    data = data.replace(b"Program Headers:", b" Class: ELF32\nProgram Headers:")
                if fault == "truncated_symbols":
                    data = data[: data.index(b" 3:")]
            if argv[1] == "-d" and fault == "dynamic":
                data = data.split(b"\n")[0] + b"\n"
        r["stdout_hex"] = data.hex()
        return r

    monkeypatch.setattr(s.m, "_run", broken)
    with pytest.raises(ValueError):
        produce(s)


@pytest.mark.parametrize(
    "fault", ["token", "querybytes", "alias", "file", "candidate", "extraquery", "tool", "self", "context", "agent"]
)
def test_auditor_rederives_complete_bill(setup, fault):
    s = setup
    b = produce(s)
    changed = copy.deepcopy(b)
    if fault == "token":
        changed["selected_paths"][0]["trace"]["origin"]["token_span"][0] += 1
    if fault == "querybytes":
        changed["queries"][-1]["record"]["stdout_hex"] = ""
    if fault == "alias":
        changed["entries"][0]["selected"][0] = "/forged.so"
    if fault == "file":
        changed["files"].pop()
    if fault == "candidate":
        changed["candidates"] = []
    if fault == "extraquery":
        changed["queries"].append(copy.deepcopy(changed["queries"][-1]))
    if fault == "tool":
        changed["tools_after"]["ldd"]["sha256"] = "0" * 64
    if fault == "self":
        changed["entries"][1]["file"]["sha256"] = "0" * 64
    if fault == "context":
        changed["observed_context_after"]["modules"] = []
    if fault == "agent":
        changed["agent_paths"] = ["/sdk/unused.so"]
    with pytest.raises(ValueError):
        s.m.audit_entry_context_bill_v4(changed, baseline_files=b["files"], python_context=s.context)


def test_final_file_failure_keeps_prefix_and_attempts_all_remaining(setup, monkeypatch):
    s = setup
    active = False
    attempted = []
    original = s.m.file_record

    def run(argv, env, cwd):
        nonlocal active
        r = s.run(argv, env, cwd)
        if argv == [s.tools["ldd"], NUMPY]:
            active = True
            r["stdout_hex"] = b"primary malformed trace\n".hex()
        return r

    def record(path):
        if active:
            attempted.append(path)
            if path == "/sdk/unused.so":
                raise OSError("secondary final file unavailable")
        return original(path)

    monkeypatch.setattr(s.m, "_run", run)
    monkeypatch.setattr(s.m, "file_record", record)
    with pytest.raises(ValueError, match="malformed") as caught:
        produce(s)
    b = caught.value.bill
    assert b["declared_after"] and NUMPY in {f["requested"] for f in b["declared_after"]}
    assert b["files_after"] and s.tools["ldd"] in {f["requested"] for f in b["files_after"]}
    assert b["tools_after"] and b["observed_context_after"]
    assert b["final_observations"]["declared"]["available"] is False
    assert "secondary final" in str(b["secondary_errors"]) and "malformed" in b["error"]


def test_failed_selected_observer_retains_full_partial_attempt(setup, monkeypatch):
    s = setup
    original = s.fs.open

    def open_path(path):
        if ".." in path.split("/"):
            raise OSError("fixture selected open failure")
        return original(path)

    monkeypatch.setattr(s.fs, "open", open_path)
    with pytest.raises(ValueError, match="selected open failure") as caught:
        produce(s)
    b = caught.value.bill
    attempt = b["path_attempts"][-1]
    assert attempt["error"] and attempt["record"]["complete"] is False
    assert attempt["record"]["walk_before"]["events"] and attempt["query_index"] == b["entries"][-1]["ldd_query"]
    assert ".." in attempt["raw_path"].split("/")


def test_query_and_aggregate_writer_keep_primary_and_fallback(setup, monkeypatch):
    s = setup

    def run(argv, env, cwd):
        r = s.run(argv, env, cwd)
        r["reader_complete"] = False
        return r

    def writer(path, value):
        raise OSError("fixture writer failure")

    monkeypatch.setattr(s.m, "_run", run)
    monkeypatch.setattr(s.m, "_write_json", writer)
    with pytest.raises(ValueError, match="terminal/stream") as caught:
        produce(s)
    b = caught.value.bill
    assert "terminal/stream" in b["error"] and "writer failure" in str(b["secondary_errors"])
    assert (s.out / "query-0001-fallback.json").is_file() and (s.out / "entry-bill-fallback.json").is_file()


@pytest.mark.parametrize("target", ["context", "tools", "candidates"])
def test_each_final_observer_failure_is_attempted_with_primary_intact(setup, monkeypatch, target):
    s = setup
    active = False
    original = s.m.file_record

    def run(argv, env, cwd):
        nonlocal active
        row = s.run(argv, env, cwd)
        if argv == [s.tools["ldd"], NUMPY]:
            active = True
            row["error"] = "first command failure"
        return row

    def record(path):
        if active and (
            (target == "tools" and path == s.tools["loader"]) or (target == "candidates" and path == "/sdk/unused.so")
        ):
            raise OSError("final observer fault")
        return original(path)

    def context():
        if active and target == "context":
            raise OSError("final context fault")
        return copy.deepcopy(s.context)

    monkeypatch.setattr(s.m, "_run", run)
    monkeypatch.setattr(s.m, "file_record", record)
    monkeypatch.setattr(s.m, "collect_python_context", context)
    with pytest.raises(ValueError) as caught:
        produce(s)
    b = caught.value.bill
    assert all(status["attempted"] for status in b["final_observations"].values())
    assert "unsuccessful" in b["error"] and b["secondary_errors"]


@pytest.mark.parametrize("fault", ["success", "cap", "timeout", "reader", "thread_start", "generic_wait", "terminate"])
def test_bounded_process_protocol_never_calls_external_backend(setup, monkeypatch, fault):
    s = setup
    m = s.m
    events = []
    clock = [0]
    reads = {1: [b"x" * (2097152 + 1), b""], 2: [b""]}
    if fault != "cap":
        reads[1] = [b"partial bytes", b""]

    class Pipe:
        def __init__(self, n):
            self.n = n

        def fileno(self):
            return self.n

        def close(self):
            events.append(("close", self.n))

    class Process:
        pid = 999
        stdout = Pipe(1)
        stderr = Pipe(2)

        def poll(self):
            return None if fault in ("timeout", "terminate", "generic_wait") and not any(e[0] == "wait" for e in events) else 0

        def terminate(self):
            events.append(("terminate",))
            if fault == "terminate":
                raise OSError("terminate secondary")

        def wait(self, timeout):
            events.append(("wait", timeout))
            if fault in ("timeout", "terminate") and sum(e[0] == "wait" for e in events) == 1:
                raise subprocess.TimeoutExpired("fixture", 5)
            if fault == "generic_wait" and sum(e[0] == "wait" for e in events) == 1:
                raise OSError("fixture wait failure")
            return 0

        def kill(self):
            events.append(("kill",))

    class Thread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.started = False

        def start(self):
            if fault == "thread_start":
                raise OSError("primary thread start failure")
            self.started = True
            self.target(*self.args)

        def join(self, timeout):
            if not self.started:
                raise RuntimeError("unstarted reader join")

        def is_alive(self):
            return False

    def read(fd, size):
        if fault == "reader" and fd == 1:
            raise OSError("fixture stream read failure")
        data = reads[fd].pop(0)
        if len(data) > size:
            reads[fd].insert(0, data[size:])
            data = data[:size]
        return data

    def monotonic_ns():
        n = clock[0]
        clock[0] += 10_000_000_000 if fault in ("timeout", "terminate", "generic_wait") else 1
        return n

    monkeypatch.setattr(m, "os", SimpleNamespace(name="posix", read=read))
    monkeypatch.setattr(
        m,
        "subprocess",
        SimpleNamespace(
            Popen=lambda *a, **kw: events.append(("popen", kw["cwd"])) or Process(),
            DEVNULL=-1,
            PIPE=-1,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
    )
    monkeypatch.setattr(m, "threading", SimpleNamespace(Thread=Thread, Event=__import__("threading").Event))
    monkeypatch.setattr(m, "time", SimpleNamespace(monotonic_ns=monotonic_ns, time_ns=lambda: 100))
    row = s.real_run(["/tool", "/entry"], {"PATH": "/bin"}, "/exact/cwd")
    assert events[0] == ("popen", "/exact/cwd") and all(e[1] == 5 for e in events if e[0] == "wait")
    if fault == "success":
        assert row["error"] is None and row["owned_child_waited"] and row["stdout_hex"] == b"partial bytes".hex()
    elif fault == "cap":
        assert row["output_limited"] and len(bytes.fromhex(row["stdout_hex"])) == 2097152
    elif fault == "thread_start":
        assert "primary thread start failure" in row["error"]
    elif fault == "generic_wait":
        assert ("kill",) in events and row["owned_child_waited"]
    else:
        assert row["error"]


def test_real_collector_reads_existing_extension_without_import_target(setup, monkeypatch):
    from importlib.machinery import ExtensionFileLoader

    s = setup
    m = s.m
    fake = SimpleNamespace(__file__=EXT, __spec__=SimpleNamespace(origin=EXT, loader=ExtensionFileLoader("_fixture", EXT)))
    monkeypatch.setattr(
        m,
        "sys",
        SimpleNamespace(
            modules={"_fixture": fake},
            executable=s.tools["python"],
            implementation=SimpleNamespace(name="cpython"),
            version="fixture CPython3.12.3",
            version_info=[3, 12, 3],
            getdlopenflags=lambda: 2,
        ),
    )
    monkeypatch.setattr(m.sysconfig, "get_config_var", lambda key: s.context[{"SOABI": "soabi", "EXT_SUFFIX": "ext_suffix"}[key]])
    actual = m.__dict__["collect_python_context"]
    # Fixture replaced collector at setup; obtain the compiled function from source namespace.
    namespace = {}
    exec(compile(Path(m.__file__).read_text(encoding="utf-8"), m.__file__, "exec"), namespace)
    collector = namespace["collect_python_context"]
    collector.__globals__.update(sys=m.sys, file_record=s.fs.file_record, sysconfig=m.sysconfig)
    assert collector()["modules"] == s.context["modules"]
    assert callable(actual) and not hasattr(fake, "executed")


@pytest.mark.parametrize("fault", ["extra_bill_field", "chronology", "pin_shape"])
def test_auditor_refuses_extra_schema_or_forged_first_observation(setup, fault):
    s = setup
    b = produce(s)
    baseline = copy.deepcopy(b["files"])
    if fault == "extra_bill_field":
        b["source_verified"] = True
    elif fault == "chronology":
        b["first_observed_query"] = {p: 0 for p in b["first_observed_query"]}
    else:
        # All copies are altered consistently; absence of required link/path pin
        # fields must still be rejected rather than trusting matching dict labels.
        def remove(value):
            if isinstance(value, dict):
                if {"requested", "resolved", "identity", "sha256", "bytes"} <= value.keys():
                    value.pop("links", None)
                    value.pop("path_identity", None)
                for item in value.values():
                    remove(item)
            elif isinstance(value, list):
                for item in value:
                    remove(item)

        remove(b)
        remove(baseline)
    with pytest.raises(ValueError):
        s.m.audit_entry_context_bill_v4(b, baseline_files=baseline, python_context=s.context)


def test_renderer_coverage_not_replaced_by_other_entry_trace(setup, monkeypatch):
    s = setup

    def run(argv, env, cwd):
        row = s.run(argv, env, cwd)
        if argv == [s.tools["ldd"], RENDERER]:
            row["stdout_hex"] = (NAMES[0] + " => " + OGRE + "/" + NAMES[0] + " (0x1234)\n").encode().hex()
        return row

    monkeypatch.setattr(s.m, "_run", run)
    with pytest.raises(ValueError, match="renderer"):
        produce(s)


def test_agent_uses_own_explicit_library_context_only(setup):
    s = setup
    agent = s.fs.add("/agent/bin/Agent")
    s.entries["agent"] = [agent]
    b = s.m.discover_entry_context_v4(s.entries, ["/sdk/unused.so"], s.context, [agent], "/agent/lib", s.out)
    relevant = [env for argv, env, _ in s.calls if argv[-1] == agent]
    assert relevant and all(env["LD_LIBRARY_PATH"] == "/agent/lib" for env in relevant)
    assert all("LD_LIBRARY_PATH" not in env for argv, env, _ in s.calls if argv[-1] not in (agent,))
    s.m.audit_entry_context_bill_v4(b, baseline_files=b["files"], python_context=s.context)


@pytest.mark.parametrize("key", ["links", "path_identity"])
def test_file_pin_requires_complete_declared_record(setup, key):
    s = setup
    record = s.fs.file_record(EXT)
    del record[key]
    with pytest.raises(ValueError):
        s.m._validate_pin(record)


def test_nonzero_needed_python_context_uses_same_typed_trace(setup):
    s = setup
    module = dict(
        name="numpy._core._multiarray_umath",
        origin=s.fs.file_record(NUMPY),
        module_file=NUMPY,
        spec_origin=NUMPY,
        loader="_frozen_importlib_external.ExtensionFileLoader",
    )
    s.context["modules"].append(module)
    s.observed["modules"].append(copy.deepcopy(module))
    b = produce(s)
    row = b["entries"][2]
    assert row["entry_kind"] == "python_extension_entry" and row["dynamic"]["needed"]
    assert row["metadata_query"] is None and len(row["selected"]) == 10


def test_module_body_has_no_sdk_or_consumed_import_or_file_effect(setup, monkeypatch):
    s = setup
    source = Path(s.m.__file__).read_text(encoding="utf-8")
    code = compile(source, s.m.__file__, "exec")
    original = builtins.__import__
    imports = []
    allowed = {
        "__future__",
        "copy",
        "hashlib",
        "json",
        "os",
        "posixpath",
        "re",
        "stat",
        "subprocess",
        "sys",
        "sysconfig",
        "threading",
        "time",
        "pathlib",
        "tools.benchmark",
        "tools.benchmark.declared_runtime_snapshot",
    }

    def importing(name, *args, **kwargs):
        imports.append(name)
        if name not in allowed:
            raise AssertionError("unexpected body import: " + name)
        return original(name, *args, **kwargs)

    def denied(*args, **kwargs):
        raise AssertionError("module-body file/process effect")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", denied)
        for name in ("read_bytes", "read_text", "open", "mkdir"):
            patch.setattr(Path, name, denied)
        patch.setattr(builtins, "__import__", importing)
        namespace = {"__name__": "inert_entry_module"}
        exec(code, namespace)
    assert callable(namespace["discover_entry_context_v4"]) and not any("context_v3" in n for n in imports)


def test_command_failure_precedes_postpin_observer_error(setup, monkeypatch):
    s = setup
    active = False
    original = s.m.file_record
    post = []

    def run(argv, env, cwd):
        nonlocal active
        row = s.run(argv, env, cwd)
        if argv == [s.tools["ldd"], NUMPY]:
            active = True
            row.update(
                error="primary native timeout", timed_out=True, returncode=-15, cleanup=dict(exit=-15, descendants="unknown")
            )
        return row

    def record(path):
        if active:
            post.append(path)
            if path == s.tools["ldd"]:
                raise OSError("secondary postpin observer")
        return original(path)

    monkeypatch.setattr(s.m, "_run", run)
    monkeypatch.setattr(s.m, "file_record", record)
    with pytest.raises(Exception) as caught:
        produce(s)
    assert isinstance(caught.value, ValueError) and "unsuccessful" in caught.value.bill["error"]
    assert "primary native timeout" in caught.value.bill["queries"][-1]["record"]["error"]
    assert NUMPY in post and "secondary postpin" in str(caught.value.bill["secondary_errors"])


def test_full_aggregate_write_then_failure_cannot_publish_complete(setup, monkeypatch):
    s = setup
    writer = s.m._write_json

    def late_failure(path, value):
        result = writer(path, value)
        if Path(path).name == "entry-bill.json":
            raise OSError("fullwrite late-close/readback failure")
        return result

    monkeypatch.setattr(s.m, "_write_json", late_failure)
    with pytest.raises(OSError, match="fullwrite") as caught:
        produce(s)
    actual = json.loads((s.out / "entry-bill.json").read_bytes())
    assert caught.value.bill["complete"] is False
    with pytest.raises(ValueError):
        s.m.audit_entry_context_bill_v4(actual, baseline_files=caught.value.bill["files"], python_context=s.context)


def test_auditor_uses_pinned_sdk_interpreter_not_reviewer_host(setup, monkeypatch):
    s = setup
    b = produce(s)
    monkeypatch.setattr(s.m, "tool_paths", lambda: dict(s.tools, python="/reviewer/other-python"))
    s.m.audit_entry_context_bill_v4(b, baseline_files=b["files"], python_context=s.context)


def test_coordinated_nonelf_relabel_cannot_drop_final_entry_queries(setup):
    s = setup
    b = produce(s)
    baseline = copy.deepcopy(b["files"])
    changed = copy.deepcopy(b)
    row = changed["entries"][-1]
    changed["queries"] = changed["queries"][: row["dynamic_query"] - 1]
    row.update(
        elf=False,
        dynamic_query=None,
        metadata_query=None,
        ldd_query=None,
        dynamic=None,
        elf_metadata=None,
        trace_kind=None,
        selected=[],
        path_records=[],
        nonfiles=[],
    )
    count = len(changed["entries"][0]["path_records"])
    for key in ("selected_paths", "selected_paths_after", "path_attempts"):
        changed[key] = changed[key][:count]
    declared = (
        set(s.tools.values())
        | {p for values in s.entries.values() for p in values}
        | {"/sdk/unused.so"}
        | {OGRE + "/" + n for n in NAMES}
    )
    for key in ("declared_before", "declared_after", "files", "files_after"):
        changed[key] = [r for r in changed[key] if r["requested"] in declared]
    changed["first_observed_query"] = {p: v for p, v in changed["first_observed_query"].items() if p in declared}
    # Exercise semantic evidence as well as the public completed-artifact hash gate.
    auditor = getattr(s.m, "_audit_content_v4", s.m.audit_entry_context_bill_v4)
    with pytest.raises(ValueError):
        auditor(changed, baseline_files=baseline, python_context=s.context)


@pytest.mark.parametrize("bad", [float("nan"), object()])
def test_initial_unserializable_context_gets_error_lifecycle(setup, bad):
    s = setup
    s.context["version"] = bad
    with pytest.raises(Exception) as caught:
        produce(s)
    assert hasattr(caught.value, "bill") and not caught.value.bill["complete"]
    saved = json.loads((s.out / "entry-bill.json").read_bytes())
    assert saved["error"] and set(saved["final_observations"]) == {
        "context",
        "declared",
        "files",
        "tools",
        "candidates",
        "selected_paths",
    }
    assert not s.calls


def test_serialized_bill_roundtrip_preserves_entry_and_version_order(setup):
    s = setup
    b = produce(s)
    actual = json.loads((s.out / "entry-bill.json").read_bytes())
    s.m.audit_entry_context_bill_v4(actual, baseline_files=b["files"], python_context=s.context)


@pytest.mark.parametrize("data", [b"", b"x", b"\x7fE", b"\x7fELF", b"\x7fELFpayload"])
def test_real_prefix_witness_hashes_same_owned_descriptor(setup, monkeypatch, data):
    s = setup
    assert callable(s.real_witness)
    s.fs.data[EXT] = data

    class Stream:
        def __init__(self):
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def fileno(self):
            return 99

        def close(self):
            pass

        def read(self, size):
            assert size == 65536
            block = data[self.offset : self.offset + size]
            self.offset += len(block)
            return block

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", lambda path, mode: Stream())
        patch.setattr(s.m, "os", SimpleNamespace(fstat=lambda fd: s.fs.lstat(EXT)))
        record = s.real_witness(EXT)
    assert record["byte_witness"]["prefix_hex"] == data[:4].hex()
    assert record["byte_witness"]["sha256"] == hashlib.sha256(data).hexdigest()


def test_terminal_receipt_prepared_write_failure_never_commits(setup, monkeypatch):
    s = setup
    writer = s.m._write_json

    def late_failure(path, value):
        ref = writer(path, value)
        if Path(path).name == "entry-bill-terminal.prepared.json":
            raise OSError("prepared receipt fullwrite failure")
        return ref

    monkeypatch.setattr(s.m, "_write_json", late_failure)
    with pytest.raises(OSError, match="prepared"):
        produce(s)
    actual = json.loads((s.out / "entry-bill.json").read_bytes())
    assert not (s.out / "entry-bill-terminal.json").exists()
    with pytest.raises(ValueError):
        s.m.audit_entry_context_bill_v4(actual, baseline_files=actual["files"], python_context=s.context)


@pytest.mark.parametrize(
    "field,value", [("prefix_hex", "7f45"), ("prefix_hex", "7F454C46"), ("sha256", "0" * 64), ("fd_after", {})]
)
def test_malformed_baseline_prefix_witness_refuses(setup, field, value):
    s = setup
    b = produce(s)
    changed = copy.deepcopy(b)
    row = next(r for r in changed["files"] if r["requested"] == NUMPY)
    row["byte_witness"][field] = value
    with pytest.raises(ValueError):
        s.m._audit_content_v4(changed, baseline_files=changed["files"], python_context=s.context)


def test_terminal_publisher_is_exclusive_atomic_primitive_protocol(setup, monkeypatch):
    s = setup
    calls = []

    def link(*args, **kwargs):
        calls.append((args, kwargs))

    # Inspect the unpatched implementation under an inert OS protocol.
    namespace = {}
    exec(compile(Path(s.m.__file__).read_text(), s.m.__file__, "exec"), namespace)
    namespace["os"] = SimpleNamespace(link=link)
    namespace["_publish_completion"]("prepared", "final")
    assert calls == [(("prepared", "final"), dict(follow_symlinks=False))]


def test_prepared_terminal_is_not_public_authority(setup):
    s = setup
    b = produce(s)
    changed = copy.deepcopy(b)
    changed["completion_path"] = str(s.out / "entry-bill-terminal.prepared.json")
    with pytest.raises(ValueError):
        s.m.audit_entry_context_bill_v4(changed, baseline_files=b["files"], python_context=s.context)
