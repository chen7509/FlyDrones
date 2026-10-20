"""Inert POSIX filesystem protocol, not a Linux target/loader experiment."""

import builtins
import copy
import hashlib
import importlib
import json
import os
import stat
import subprocess
from types import SimpleNamespace

import pytest

from tools.benchmark.software_process_boundary import ProcessBoundaryError, guard_required


def test_default_guard_installed_without_backend_call():
    for name in [
        "test_native_loader_paths_v4.py",
        "test_native_entry_context_v4.py",
        "test_calibration_capture_study_v4.py",
        "test_calibration_static_v4_executor.py",
    ]:
        assert guard_required(name)
    assert not guard_required("test_native_dataset_consumer.py")
    assert subprocess.Popen._execute_child.__name__ == "denied"
    with pytest.raises(ProcessBoundaryError):
        # Calls only the installed denial function; never constructs a child.
        subprocess.Popen._execute_child(None)


class Filesystem:
    supported = True

    def __init__(self):
        self.nodes = {
            "/": ("dir", 1),
            "/fixture": ("dir", 2),
            "/other": ("dir", 3),
            "/other/nested": ("dir", 4),
            "/fixture/link": ("link", "/other/nested"),
            "/other/lib": ("file", b"abc"),
            "/fixture/file": ("file", b"x"),
        }
        self.opened = []
        self.closed = []
        self.read_sizes = []
        self.offset = 0
        self.mutate = False
        self.mismatch = False

    def lstat(self, path):
        kind, value = self.nodes[path]
        mode = {
            "dir": stat.S_IFDIR | 0o755,
            "link": stat.S_IFLNK | 0o777,
            "file": stat.S_IFREG | 0o644,
            "fifo": stat.S_IFIFO | 0o600,
        }[kind]
        return SimpleNamespace(
            st_dev=1,
            st_ino=sorted(self.nodes).index(path) + 1,
            st_mode=mode,
            st_size=len(value) if isinstance(value, (bytes, str)) else 0,
            st_mtime_ns=10,
            st_ctime_ns=20,
        )

    def readlink(self, path):
        return self.nodes[path][1]

    def open(self, raw):
        self.opened.append(raw)
        return 99

    def fstat(self, fd):
        row = self.lstat("/other/lib")
        if self.mismatch:
            row.st_ino += 1
        if self.mutate and self.offset:
            row.st_mtime_ns += 1
        return row

    def read(self, fd, size):
        self.read_sizes.append(size)
        data = self.nodes["/other/lib"][1][self.offset : self.offset + size]
        self.offset += len(data)
        return data

    def close(self, fd):
        self.closed.append(fd)


@pytest.fixture
def module(monkeypatch):
    value = importlib.import_module("tools.benchmark.native_loader_paths_v4")
    fs = Filesystem()
    monkeypatch.setattr(value, "_FS", fs)
    return value, fs


def origin(tmp_path, path="/fixture/link/../lib", *, extra="", query_changes=None):
    stdout = ("\tlib.so => " + path + " (0x1234)\n" + extra).encode()
    pin = dict(
        requested="/tools/ldd",
        resolved="/tools/ldd",
        bytes=3,
        sha256="a" * 64,
        identity=dict(device=1, inode=8, mode=stat.S_IFREG | 0o755, size=3, mtime_ns=1, ctime_ns=2),
    )
    entry = copy.deepcopy(pin)
    entry.update(requested="/entry.so", resolved="/entry.so")
    query = dict(
        schema="native-entry-query-v4",
        kind="ldd",
        index=1,
        entry=entry,
        role="dependency_entry",
        argv=["/tools/ldd", "/entry.so"],
        cwd="/work",
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        tool_before=pin,
        tool_after=copy.deepcopy(pin),
        input_before=entry,
        input_after=copy.deepcopy(entry),
        returncode=0,
        error=None,
        timed_out=False,
        output_limited=False,
        owned_child_waited=True,
        limits=dict(stream_bytes=2097152, timeout_seconds=10, terminate_seconds=5, kill_seconds=5),
        started_monotonic_ns=100,
        ended_monotonic_ns=200,
        stdout_hex=stdout.hex(),
        stderr_hex="",
    )
    version = {k: copy.deepcopy(v) for k, v in query.items() if k not in ("entry", "role", "input_before", "input_after")}
    version.update(
        schema="native-tool-version-query-v4",
        kind="version",
        argv=["/tools/ldd", "--version"],
        stdout_hex=b"ldd (GNU libc) 2.39\n".hex(),
    )
    version_data = json.dumps(version).encode()
    version_path = tmp_path / "version.json"
    version_path.write_bytes(version_data)
    query["tool_version"] = dict(query_path=str(version_path), query_sha256=hashlib.sha256(version_data).hexdigest())
    query.update(query_changes or {})
    data = json.dumps(query).encode()
    file = tmp_path / "query.json"
    file.write_bytes(data)
    start = stdout.index(path.encode())
    end = start + len(path.encode())
    return dict(
        schema="native-loader-trace-origin-v4",
        query_path=str(file),
        query_sha256=hashlib.sha256(data).hexdigest(),
        query_index=1,
        entry=entry,
        role="dependency_entry",
        line_span=[0, len(stdout.splitlines(keepends=True)[0])],
        token_span=[start, end],
    )


def test_ordered_link_parent_and_owned_original_open(module, tmp_path):
    m, fs = module
    o = origin(tmp_path)
    r = m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    assert r["raw_path"] == "/fixture/link/../lib" and r["raw_utf8_hex"] == r["raw_path"].encode().hex()
    assert r["canonical_path"] == "/other/lib"
    assert fs.opened == ["/fixture/link/../lib"] and fs.closed == [99]
    assert fs.read_sizes == [65536, 65536]
    assert r["sha256"] == hashlib.sha256(b"abc").hexdigest() and r["bytes"] == 3
    assert [x["component"] for x in r["walk_before"]["events"]] == ["fixture", "link", "other", "nested", "..", "lib"]
    assert r["walk_before"]["events"][1]["target"] == "/other/nested"
    assert r["walk_before"] == r["walk_after"] and r["complete"] is True
    baseline = {"/other/lib": dict(sha256=r["sha256"], bytes=3, identity=r["fd_before"])}
    m.audit_selected_path(r, trace_origin=o, baseline_files=baseline)
    assert r["runtime_closure_qualified"] is False


@pytest.mark.parametrize("path", ["", "relative", "//bad", "/a\x00b", "/a\nb", "/" + ("x" * 4095), "/a\x7fb"])
def test_invalid_spelling_before_open(module, tmp_path, path):
    m, fs = module
    with pytest.raises(ValueError):
        m.record_selected_path(path, trace_origin={})
    assert fs.opened == []


@pytest.mark.parametrize("path", ["/fixture/file/../lib", "/fixture/missing/../lib", "/fixture/link/../../../missing"])
def test_not_lexical_success(module, tmp_path, path):
    m, fs = module
    with pytest.raises(m.SelectedPathError) as e:
        m.record_selected_path(path, trace_origin=origin(tmp_path, path))
    assert not e.value.partial["complete"] and fs.opened == []


@pytest.mark.parametrize("kind", ["dangling", "loop", "long_chain", "fifo", "directory", "events"])
def test_walk_refusals(module, tmp_path, kind):
    m, fs = module
    path = "/fixture/link/../lib"
    if kind == "dangling":
        fs.nodes["/fixture/link"] = ("link", "/absent")
    if kind == "loop":
        fs.nodes["/fixture/link"] = ("link", "/fixture/link")
    if kind == "long_chain":
        fs.nodes["/fixture/link"] = ("link", "/s0")
        for i in range(41):
            fs.nodes["/s" + str(i)] = ("link", "/s" + str(i + 1))
    if kind == "fifo":
        fs.nodes["/other/lib"] = ("fifo", 0)
    if kind == "directory":
        fs.nodes["/other/lib"] = ("dir", 8)
    if kind == "events":
        fs.nodes["/fixture/link"] = ("link", "./" * 4096 + "../other/nested")
    with pytest.raises(m.SelectedPathError) as e:
        m.record_selected_path(path, trace_origin=origin(tmp_path, path))
    assert e.value.partial["complete"] is False and fs.opened == []


@pytest.mark.parametrize("field", ["mutate", "mismatch"])
def test_fd_disagreement_keeps_partial_and_closes(module, tmp_path, field):
    m, fs = module
    setattr(fs, field, True)
    with pytest.raises(m.SelectedPathError) as e:
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
    assert e.value.partial["complete"] is False and fs.closed == [99]


@pytest.mark.parametrize(
    "changes",
    [
        {"returncode": 1},
        {"stderr_hex": "78"},
        {"timed_out": True},
        {"output_limited": True},
        {"error": "failed"},
        {"owned_child_waited": False},
        {"ended_monotonic_ns": 99},
        {"role": "candidate_only"},
        {"limits": {}},
        {"tool_after": {}},
        {"input_after": {}},
    ],
)
def test_unsuccessful_or_unbound_query_refuses_before_file(module, tmp_path, changes):
    m, fs = module
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path, query_changes=changes))
    assert not fs.opened


@pytest.mark.parametrize("variant", ["missing", "token", "sha", "extra", "empty", "index", "role"])
def test_provenance_refuses(module, tmp_path, variant):
    m, fs = module
    o = origin(tmp_path, extra="garbage\n" if variant == "extra" else "")
    if variant == "missing":
        o = {}
    if variant == "token":
        o["token_span"][0] += 1
    if variant == "sha":
        o["query_sha256"] = "0" * 64
    if variant == "empty":
        o = origin(tmp_path, query_changes={"stdout_hex": ""})
    if variant == "index":
        o["query_index"] = 2
    if variant == "role":
        o["role"] = "python_extension_entry"
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    assert not fs.opened


@pytest.mark.parametrize("change", ["hash", "walk", "canonical", "raw", "baseline", "clock", "flag"])
def test_auditor_rejects_unjoined_record(module, tmp_path, change):
    m, fs = module
    o = origin(tmp_path)
    r = m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    baseline = {"/other/lib": dict(sha256=r["sha256"], bytes=3, identity=r["fd_before"])}
    if change == "hash":
        r["sha256"] = "0" * 64
    if change == "walk":
        r["walk_after"]["events"][0]["identity"]["inode"] = 99
    if change == "canonical":
        r["canonical_path"] = "/fixture/lib"
    if change == "raw":
        r["raw_utf8_hex"] = "00"
    if change == "baseline":
        baseline = {}
    if change == "clock":
        r["ended_monotonic_ns"] = r["started_monotonic_ns"] - 1
    if change == "flag":
        r["runtime_closure_qualified"] = True
    with pytest.raises(ValueError):
        m.audit_selected_path(r, trace_origin=o, baseline_files=baseline)


@pytest.mark.parametrize("change", ["missing", "bad_hash", "bad_exit", "empty", "changed_tool"])
def test_retained_tool_version_required(module, tmp_path, change):
    m, fs = module
    o = origin(tmp_path)
    q = json.loads((tmp_path / "query.json").read_bytes())
    if change == "missing":
        del q["tool_version"]
    elif change == "bad_hash":
        q["tool_version"]["query_sha256"] = "0" * 64
    else:
        v = json.loads((tmp_path / "version.json").read_bytes())
        if change == "bad_exit":
            v["returncode"] = 1
        if change == "empty":
            v["stdout_hex"] = ""
        if change == "changed_tool":
            v["tool_before"]["sha256"] = "b" * 64
        data = json.dumps(v).encode()
        (tmp_path / "version.json").write_bytes(data)
        q["tool_version"]["query_sha256"] = hashlib.sha256(data).hexdigest()
    data = json.dumps(q).encode()
    (tmp_path / "query.json").write_bytes(data)
    o["query_sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    assert not fs.opened


@pytest.mark.parametrize("count", [39, 40])
def test_link_limit_and_relative_target_accepted(module, tmp_path, count):
    m, fs = module
    fs.nodes["/fixture/link"] = ("link", "/s0")
    for i in range(count - 1):
        fs.nodes["/s" + str(i)] = ("link", "s" + str(i + 1))
    fs.nodes["/s" + str(count - 1)] = ("link", "other/nested")
    if count == 40:
        with pytest.raises(ValueError):
            m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
    else:
        r = m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
        assert r["walk_before"]["links"] == 40 and r["canonical_path"] == "/other/lib"


@pytest.mark.parametrize("spelling", ["/fixture//link/./../lib", "/fixture/link/../lib/", "/fixture/link/../lib/."])
def test_separators_and_trailing_directory_requirement(module, tmp_path, spelling):
    m, fs = module
    if spelling.endswith(("/", "/.")):
        with pytest.raises(ValueError):
            m.record_selected_path(spelling, trace_origin=origin(tmp_path, spelling))
        assert not fs.opened
    else:
        r = m.record_selected_path(spelling, trace_origin=origin(tmp_path, spelling))
        assert r["raw_path"] == spelling and r["canonical_path"] == "/other/lib"


def test_link_change_and_close_secondary_keep_primary(module, tmp_path, monkeypatch):
    m, fs = module

    def read(fd, size):
        fs.nodes["/fixture/link"] = ("link", "/different")
        raise OSError("primary-read-error")

    def close(fd):
        fs.closed.append(fd)
        raise OSError("secondary-close-error")

    monkeypatch.setattr(fs, "read", read)
    monkeypatch.setattr(fs, "close", close)
    with pytest.raises(m.SelectedPathError, match="primary-read-error") as e:
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
    assert "primary-read-error" in e.value.partial["error"]
    assert "secondary-close-error" in e.value.partial["secondary_errors"][0]


def test_path_mutation_after_hash_refuses(module, tmp_path, monkeypatch):
    m, fs = module
    old = fs.read

    def read(fd, size):
        block = old(fd, size)
        if not block:
            fs.nodes["/fixture/link"] = ("link", "/fixture")
        return block

    monkeypatch.setattr(fs, "read", read)
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
    assert fs.closed == [99]


def test_posix_open_flags_are_readonly_cloexec_nonblocking(module, monkeypatch):
    m, _ = module
    calls = []
    # Pure protocol check: no OS open backend is reached, even on Windows.
    monkeypatch.setattr(m.os, "O_CLOEXEC", 0x10000000, raising=False)
    monkeypatch.setattr(m.os, "O_NONBLOCK", 0x20000000, raising=False)
    monkeypatch.setattr(m.os, "open", lambda path, flags: calls.append((path, flags)) or 7)
    assert m._PosixFilesystem().open("/a/../b") == 7
    assert calls == [("/a/../b", os.O_RDONLY | 0x10000000 | 0x20000000)]


@pytest.mark.skipif(
    os.name != "posix", reason="owned POSIX symlink fixture unavailable on Windows; protocol cases above are not Linux acceptance"
)
def test_owned_posix_directory_fixture(tmp_path, monkeypatch):
    m = importlib.import_module("tools.benchmark.native_loader_paths_v4")
    other = tmp_path / "other"
    other.mkdir()
    (other / "nested").mkdir()
    (other / "lib").write_bytes(b"abc")
    (tmp_path / "link").symlink_to(other / "nested", target_is_directory=True)
    path = str(tmp_path) + "/link/../lib"
    monkeypatch.setattr(m, "_FS", m._PosixFilesystem())
    r = m.record_selected_path(path, trace_origin=origin(tmp_path, path))
    assert r["canonical_path"] == str(other / "lib")


def test_collection_import_body_inert_under_traps(module, monkeypatch):
    m, _ = module
    source = open(m.__file__, encoding="utf-8").read()
    code = compile(source, m.__file__, "exec")
    old_import = builtins.__import__
    imports = []
    allowed = {"__future__", "copy", "hashlib", "json", "os", "re", "stat", "time", "collections"}

    def importing(name, *args, **kwargs):
        imports.append(name)
        assert name in allowed, name
        return old_import(name, *args, **kwargs)

    def denied(*args, **kwargs):
        raise AssertionError("import-time file/process effect")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", denied)
        for name in ("open", "lstat", "readlink", "read", "write", "mkdir", "makedirs"):
            patch.setattr(os, name, denied)
        patch.setattr(builtins, "__import__", importing)
        # exec runs only this audited module body, no subprocess or fresh interpreter.
        namespace = {"__name__": "inert_path_module"}
        exec(code, namespace)
    assert callable(namespace["record_selected_path"]) and "json" in imports


def test_unsupported_backend_never_opens(module, tmp_path):
    m, fs = module
    fs.supported = False
    with pytest.raises(ValueError, match="unsupported"):
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
    assert not fs.opened


def test_canonical_path_fd_change_refuses(module, tmp_path, monkeypatch):
    m, fs = module
    old = fs.lstat
    counts = {}

    def lstat(path):
        value = old(path)
        counts[path] = counts.get(path, 0) + 1
        if path == "/other/lib" and counts[path] >= 5:
            value.st_ino += 1
        return value

    monkeypatch.setattr(fs, "lstat", lstat)
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
    assert fs.closed == [99]


def test_postwalk_failure_retains_partial_events(module, tmp_path, monkeypatch):
    m, fs = module
    old = fs.read

    def read(fd, size):
        block = old(fd, size)
        if not block:
            fs.nodes["/fixture/link"] = ("link", "/absent")
        return block

    monkeypatch.setattr(fs, "read", read)
    with pytest.raises(m.SelectedPathError) as e:
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
    assert e.value.partial["partial_walk_after"]["events"][1]["target"] == "/absent"
    assert e.value.partial["partial_walk_after"]["observations"]
    assert fs.closed == [99]


def test_actual_component_event_bound(module, tmp_path):
    m, fs = module
    fs.nodes["/fixture/link"] = ("link", "./" * 2000 + "next")
    fs.nodes["/fixture/next"] = ("link", "./" * 2000 + "last")
    fs.nodes["/fixture/last"] = ("link", "./" * 2000 + "../other/nested")
    with pytest.raises(m.SelectedPathError, match="component event bound") as e:
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path))
    assert len(e.value.partial["partial_walk"]["events"]) == 4096
    assert not fs.opened


@pytest.mark.parametrize("env", [{"BAD=NAME": "x"}, {"\x00": "x"}, {"GOOD": "x\x00y"}, {"": "x"}])
def test_impossible_process_environment_refuses(module, tmp_path, env):
    m, fs = module
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=origin(tmp_path, query_changes={"env": env}))
    assert not fs.opened


def test_control_soname_refuses(module, tmp_path):
    m, fs = module
    o = origin(tmp_path)
    q = json.loads((tmp_path / "query.json").read_bytes())
    q["stdout_hex"] = bytes.fromhex(q["stdout_hex"]).replace(b"lib.so", b"li\x00.so").hex()
    data = json.dumps(q).encode()
    (tmp_path / "query.json").write_bytes(data)
    o["query_sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    assert not fs.opened


def test_control_vdso_refuses(module, tmp_path):
    m, fs = module
    o = origin(tmp_path, extra="\tlinux-vdso\x00.so (0x1234)\n")
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    assert not fs.opened


def test_version_environment_must_be_executable(module, tmp_path):
    m, fs = module
    o = origin(tmp_path)
    v = json.loads((tmp_path / "version.json").read_bytes())
    v["env"] = {"BAD=KEY": "x"}
    data = json.dumps(v).encode()
    (tmp_path / "version.json").write_bytes(data)
    q = json.loads((tmp_path / "query.json").read_bytes())
    q["tool_version"]["query_sha256"] = hashlib.sha256(data).hexdigest()
    data = json.dumps(q).encode()
    (tmp_path / "query.json").write_bytes(data)
    o["query_sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    assert not fs.opened


def test_exact_component_event_limit_success(module, tmp_path):
    m, fs = module
    fs.nodes["/fixture/link"] = ("link", "./" * 1500 + "next")
    fs.nodes["/fixture/next"] = ("link", "./" * 1500 + "last")
    fs.nodes["/fixture/last"] = ("link", "./" * 1087 + "../other/nested")
    o = origin(tmp_path)
    r = m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    assert len(r["walk_before"]["events"]) == 4096
    m.audit_selected_path(
        r, trace_origin=o, baseline_files={"/other/lib": dict(bytes=3, sha256=r["sha256"], identity=r["fd_before"])}
    )


@pytest.mark.parametrize("change", ["missing", "bad_type"])
def test_auditor_requires_utc_fields(module, tmp_path, change):
    m, fs = module
    o = origin(tmp_path)
    r = m.record_selected_path("/fixture/link/../lib", trace_origin=o)
    baseline = {"/other/lib": dict(bytes=3, sha256=r["sha256"], identity=r["fd_before"])}
    if change == "missing":
        del r["started_utc_ns"]
        del r["ended_utc_ns"]
    else:
        r["started_utc_ns"] = "unknown"
    with pytest.raises(ValueError):
        m.audit_selected_path(r, trace_origin=o, baseline_files=baseline)
