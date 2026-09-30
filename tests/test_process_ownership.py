import json
import shutil
import signal
from pathlib import Path

import pytest

from flydrones.process_ownership import (
    ProcessIdentity,
    append_process_identity,
    identity_matches,
    load_process_registry,
    process_identity_status,
    read_process_identity,
    stop_owned_processes,
)


def _write_process(
    proc_root: Path,
    pid: int,
    *,
    name: str,
    start_ticks: int,
    argv: tuple[str, ...],
    state: str = "S",
):
    directory = proc_root / str(pid)
    directory.mkdir(parents=True)
    fields_4_to_21 = [str(index) for index in range(4, 22)]
    (directory / "stat").write_text(
        f"{pid} ({name}) {state} {' '.join(fields_4_to_21)} {start_ticks} 0 0\n",
        encoding="utf-8",
    )
    (directory / "cmdline").write_bytes(b"\0".join(item.encode() for item in argv) + b"\0")


def test_read_process_identity_handles_spaces_and_parentheses_in_name(tmp_path):
    _write_process(
        tmp_path,
        321,
        name="gz sim (server)",
        start_ticks=987654,
        argv=("gz", "sim", "-r", "flydrones_forest.sdf"),
    )

    identity = read_process_identity(321, proc_root=tmp_path)

    assert identity == ProcessIdentity(
        pid=321,
        start_ticks=987654,
        argv=("gz", "sim", "-r", "flydrones_forest.sdf"),
        role="",
    )


def test_identity_matches_unchanged_pid_start_time_and_command(tmp_path):
    _write_process(tmp_path, 42, name="px4", start_ticks=1234, argv=("px4", "-i", "0"))
    record = ProcessIdentity(42, 1234, ("px4", "-i", "0"), "px4-0")

    assert identity_matches(record, proc_root=tmp_path)
    assert process_identity_status(record, proc_root=tmp_path) == "matching"


def test_identity_rejects_reused_pid_with_new_start_time(tmp_path):
    _write_process(tmp_path, 42, name="unrelated", start_ticks=9999, argv=("sleep", "100"))
    record = ProcessIdentity(42, 1234, ("px4", "-i", "0"), "px4-0")

    assert not identity_matches(record, proc_root=tmp_path)
    assert process_identity_status(record, proc_root=tmp_path) == "ownership-mismatch"


def test_identity_rejects_changed_command_even_with_same_start_time(tmp_path):
    _write_process(tmp_path, 42, name="other", start_ticks=1234, argv=("sleep", "100"))
    record = ProcessIdentity(42, 1234, ("px4", "-i", "0"), "px4-0")

    assert not identity_matches(record, proc_root=tmp_path)
    assert process_identity_status(record, proc_root=tmp_path) == "ownership-mismatch"


def test_missing_process_is_reported_as_already_stopped(tmp_path):
    record = ProcessIdentity(404, 1234, ("px4", "-i", "0"), "px4-0")

    assert not identity_matches(record, proc_root=tmp_path)
    assert process_identity_status(record, proc_root=tmp_path) == "already-gone"


def test_zombie_process_is_reported_as_already_stopped(tmp_path):
    _write_process(tmp_path, 42, name="px4", start_ticks=1234, argv=("px4", "-i", "0"), state="Z")
    record = ProcessIdentity(42, 1234, ("px4", "-i", "0"), "px4-0")

    assert process_identity_status(record, proc_root=tmp_path) == "already-gone"


def test_empty_cmdline_after_term_is_reported_as_already_stopped(tmp_path):
    _write_process(tmp_path, 42, name="px4", start_ticks=1234, argv=())
    record = ProcessIdentity(42, 1234, ("px4", "-i", "0"), "px4-0")

    assert process_identity_status(record, proc_root=tmp_path) == "already-gone"


def test_process_identity_round_trips_through_registry_json():
    record = ProcessIdentity(5, 77, ("gz", "sim"), "gazebo-server")

    encoded = json.dumps(record.to_dict())

    assert ProcessIdentity.from_dict(json.loads(encoded)) == record


def test_registry_append_is_atomic_and_idempotent_for_same_identity(tmp_path):
    _write_process(tmp_path / "proc", 5, name="gz", start_ticks=77, argv=("gz", "sim"))
    registry = tmp_path / "owned-processes.json"

    first = append_process_identity(registry, 5, "gazebo-server", proc_root=tmp_path / "proc")
    second = append_process_identity(registry, 5, "gazebo-server", proc_root=tmp_path / "proc")

    assert second == first
    assert load_process_registry(registry) == [first]
    assert not list(tmp_path.glob("*.tmp"))


def test_registry_append_waits_for_nonempty_argv(tmp_path):
    proc_root = tmp_path / "proc"
    _write_process(proc_root, 5, name="native", start_ticks=77, argv=())
    attempts = []

    def expose_argv(_duration):
        attempts.append(True)
        (proc_root / "5/cmdline").write_bytes(b"native\0observe\0")

    record = append_process_identity(
        tmp_path / "owned-processes.json",
        5,
        "observer",
        proc_root=proc_root,
        read_attempts=3,
        read_delay_s=0.0,
        sleep=expose_argv,
    )

    assert attempts == [True]
    assert record.argv == ("native", "observe")


def test_registry_append_rejects_persistently_empty_argv(tmp_path):
    proc_root = tmp_path / "proc"
    _write_process(proc_root, 5, name="native", start_ticks=77, argv=())
    with pytest.raises(RuntimeError, match="nonempty argv"):
        append_process_identity(
            tmp_path / "owned-processes.json",
            5,
            "observer",
            proc_root=proc_root,
            read_attempts=2,
            read_delay_s=0.0,
            sleep=lambda _duration: None,
        )


def test_owned_stop_signals_only_matching_processes_and_reports_reused_pid(tmp_path):
    proc_root = tmp_path / "proc"
    _write_process(proc_root, 10, name="owned", start_ticks=100, argv=("sleep", "10"))
    _write_process(proc_root, 11, name="reused", start_ticks=999, argv=("unrelated",))
    owned = ProcessIdentity(10, 100, ("sleep", "10"), "owned")
    stale = ProcessIdentity(11, 101, ("sleep", "11"), "stale")
    missing = ProcessIdentity(12, 102, ("sleep", "12"), "gone")
    signals = []

    def send_signal(pid, signum):
        signals.append((pid, signum))
        shutil.rmtree(proc_root / str(pid))

    evidence = stop_owned_processes(
        [owned, stale, missing],
        timeout_s=0.01,
        proc_root=proc_root,
        send_signal=send_signal,
        sleep=lambda _duration: None,
    )

    assert signals == [(10, signal.SIGTERM)]
    assert evidence["stopped"] == [owned.to_dict()]
    assert evidence["already_gone"] == [missing.to_dict()]
    assert evidence["ownership_mismatch"] == [stale.to_dict()]
    assert evidence["failed_to_stop"] == []
