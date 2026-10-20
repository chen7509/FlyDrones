"""Production byte-opener association behavior; injected identities are not PX4."""

import hashlib
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from flydrones.benchmark.ulog_capture import collect_ulogs


def setup(tmp_path):
    api = importlib.import_module("tools.benchmark.owned_ulog_source")
    runtime = tmp_path / "runtime"
    output = tmp_path / "capture"
    runtime.mkdir()
    output.mkdir()
    binary = tmp_path / "fixture-executable"
    binary.write_bytes(b"fixture, not a PX4 ELF")
    state = {"pid": 1234, "pgrp": 23, "session": 23, "start_ticks": 100, "state": "S", "executable": str(binary.resolve())}
    process = SimpleNamespace(pid=1234, exit=None)
    process.poll = lambda: process.exit
    fds = []
    observer = api.OwnedUlogSource(
        runtime,
        output,
        expected_executable_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        identity_reader=lambda pid: dict(state),
        fd_reader=lambda pid, limit: list(fds),
    )
    observer.register(process, binary)
    return observer, process, state, fds, runtime, output


def logfile(runtime, fds, *, writable=True, name="log.ulg"):
    path = runtime / name
    path.write_bytes(b"ULog\x01\x12\x35" + b"\0" * 25)
    s = path.stat()
    fds.append(
        {
            "fd": 6,
            "path": str(path.resolve()),
            "device": s.st_dev,
            "inode": s.st_ino,
            "mode": s.st_mode,
            "flags": os.O_WRONLY if writable else os.O_RDONLY,
        }
    )
    return path


def artifacts(output):
    for name in ("rgb-capture-manifest.json", "camera-info.json", "events.jsonl"):
        (output / name).write_bytes(b"fixture bytes, not calibrated data")


def test_observed_writable_inode_binds_retained_copy_and_camera_artifacts(tmp_path):
    observer, process, state, fds, runtime, output = setup(tmp_path)
    logfile(runtime, fds)
    observer.observe()
    process.exit = 0
    records = collect_ulogs(runtime, output)
    artifacts(output)
    result = observer.finish(records)
    assert result["all_logs_associated"] is True
    assert result["logs"][0]["observed_writable_opener"] is True
    assert result["logs"][0]["sha256"] == records[0]["sha256"]
    assert not result["live_source_authenticated"]
    assert not result["camera_calibration_verified"]
    assert (output / "owned-ulog-source/association.json").is_file()


def test_missing_witness_preserves_ulogs_and_refuses_association(tmp_path):
    observer, process, state, fds, runtime, output = setup(tmp_path)
    logfile(runtime, fds)
    process.exit = 0
    records = collect_ulogs(runtime, output)
    artifacts(output)
    result = observer.finish(records)
    assert not result["all_logs_associated"]
    assert result["errors"]
    assert (output / records[0]["path"]).is_file()


@pytest.mark.parametrize("key,value", [("start_ticks", 101), ("executable", "/other")])
def test_changed_owned_process_is_refused(tmp_path, key, value):
    observer, process, state, fds, runtime, output = setup(tmp_path)
    state[key] = value
    with pytest.raises(ValueError, match="identity"):
        observer.observe()


def test_outside_or_readonly_descriptor_is_refused(tmp_path):
    observer, process, state, fds, runtime, output = setup(tmp_path)
    path = logfile(runtime, fds, writable=False)
    with pytest.raises(ValueError, match="writable"):
        observer.observe()
    other = tmp_path / "second"
    other.mkdir()
    observer, process, state, fds, runtime, output = setup(other)
    path = logfile(runtime, fds)
    fds[0]["path"] = str(output / path.name)
    with pytest.raises(ValueError, match="runtime"):
        observer.observe()


def test_replaced_source_inode_after_observation_cannot_be_associated(tmp_path):
    observer, process, state, fds, runtime, output = setup(tmp_path)
    source = logfile(runtime, fds)
    observer.observe()
    source.rename(runtime / "held.bin")
    source.write_bytes(b"ULog\x01\x12\x35" + b"\0" * 25)
    process.exit = 0
    records = collect_ulogs(runtime, output)
    artifacts(output)
    result = observer.finish(records)
    assert not result["all_logs_associated"]
    assert result["errors"]


def test_finish_requires_actual_child_exit_and_exclusive_output(tmp_path):
    observer, process, state, fds, runtime, output = setup(tmp_path)
    with pytest.raises(ValueError, match="exit"):
        observer.finish([])
    process.exit = 0
    observer.finish([])
    with pytest.raises(FileExistsError):
        observer.finish([])


def test_failed_observation_never_promotes_partial_witness(tmp_path):
    observer, process, state, fds, runtime, output = setup(tmp_path)
    logfile(runtime, fds)

    def change_identity(pid, limit):
        state["start_ticks"] += 1
        return list(fds)

    observer.fd_reader = change_identity
    with pytest.raises(ValueError, match="identity changed"):
        observer.observe()
    process.exit = 0
    records = collect_ulogs(runtime, output)
    artifacts(output)
    assert not observer.finish(records)["all_logs_associated"]


def test_fd_reuse_cannot_mix_inode_with_unrelated_writable_flags(tmp_path, monkeypatch):
    api = importlib.import_module("tools.benchmark.owned_ulog_source")
    a, b = tmp_path / "read-only.ulg", tmp_path / "unrelated.bin"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    fd = SimpleNamespace(name="6", stat=a.stat)
    root = SimpleNamespace(iterdir=lambda: iter([fd]))
    info = SimpleNamespace(read_text=lambda **kwargs: "flags: 0100001\n")
    monkeypatch.setattr(
        api, "Path", lambda path: root if str(path).endswith("/fd") else info if "/fdinfo/" in str(path) else Path(path)
    )
    monkeypatch.setattr(api.os, "readlink", lambda path: str(a))
    monkeypatch.setattr(api, "duplicate_record", lambda pid, target: (b.stat(), os.O_WRONLY), raising=False)
    with pytest.raises(ValueError, match="descriptor identity"):
        api.descriptors(1234, 256)


def test_permission_denied_cannot_fallback_to_racy_flags(tmp_path, monkeypatch):
    api = importlib.import_module("tools.benchmark.owned_ulog_source")
    a = tmp_path / "log.ulg"
    a.write_bytes(b"a")
    fd = SimpleNamespace(name="6", stat=a.stat)
    root = SimpleNamespace(iterdir=lambda: iter([fd]))
    info = SimpleNamespace(read_text=lambda **kwargs: "flags: 0100001\n")
    monkeypatch.setattr(
        api, "Path", lambda path: root if str(path).endswith("/fd") else info if "/fdinfo/" in str(path) else Path(path)
    )
    monkeypatch.setattr(api.os, "readlink", lambda path: str(a))

    def refused(*args):
        raise PermissionError("pidfd duplication denied")

    monkeypatch.setattr(api, "duplicate_record", refused, raising=False)
    with pytest.raises(PermissionError, match="duplication denied"):
        api.descriptors(1234, 256)


def test_duplicate_close_error_still_attempts_pidfd_close(tmp_path, monkeypatch):
    import ctypes

    api = importlib.import_module("tools.benchmark.owned_ulog_source")
    path = tmp_path / "stat-fixture"
    path.write_bytes(b"fixture")
    value = path.stat()
    monkeypatch.setattr(api.platform, "system", lambda: "Linux")
    monkeypatch.setattr(api.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(api.os, "pidfd_open", lambda *args: 20, raising=False)
    monkeypatch.setattr(api.os, "fstat", lambda fd: value)
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(F_GETFL=3, fcntl=lambda *args: os.O_WRONLY))

    class Syscall:
        def __call__(self, *args):
            return 21

    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(syscall=Syscall()))
    closed = []

    def close(fd):
        closed.append(fd)
        if fd == 21:
            raise OSError("duplicate close failed")

    monkeypatch.setattr(api.os, "close", close)
    with pytest.raises(OSError, match="duplicate close failed"):
        api.duplicate_record(1234, 6)
    assert closed == [21, 20]


def test_all_witnessed_logs_must_survive_collection(tmp_path):
    observer, process, state, fds, runtime, output = setup(tmp_path)
    lost = logfile(runtime, fds, name="lost.ulg")
    observer.observe()
    lost.rename(runtime / "gone.bin")
    fds.clear()
    kept = logfile(runtime, fds, name="kept.ulg")
    observer.observe()
    (runtime / "gone.bin").unlink()
    process.exit = 0
    records = collect_ulogs(runtime, output)
    artifacts(output)
    assert kept.exists()
    assert not observer.finish(records)["all_logs_associated"]
