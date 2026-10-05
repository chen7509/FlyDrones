import io
import signal
from types import SimpleNamespace

import pytest

from tools.benchmark.owned_group_evidence import KILL, GroupEvidence, parse_stat, scan_group


def stat(pid=500, state="S", pgid=500, sid=500, start=10):
    fields = [state, "1", str(pgid), str(sid)] + ["0"] * 15 + [str(start)] + ["0"] * 8
    return f"{pid} (name ) with space) " + " ".join(fields)


def create(root, pid=500, **kw):
    d = root / str(pid)
    d.mkdir(exist_ok=True)
    (d / "stat").write_text(stat(pid=pid, **kw))


def test_parser_and_zombie_distinction(tmp_path):
    create(tmp_path, state="Z")
    create(tmp_path, pid=501, state="S")
    row = parse_stat(stat())
    assert row == dict(pid=500, state="S", pgrp=500, session=500, start_ticks=10)
    out = scan_group(500, tmp_path)
    assert len(out["members"]) == 2 and len(out["executing"]) == 1 and not out["errors"]


@pytest.mark.parametrize("value", ["bad", "1 (x) S", "1 (x) S 0 -1 0 " + "0 " * 30])
def test_bad_stat_refused(value):
    with pytest.raises(ValueError):
        parse_stat(value)


def test_bad_scan_is_unknown_not_empty_success(tmp_path):
    create(tmp_path)
    create(tmp_path, pid=501)
    (tmp_path / "501/stat").write_text("bad")
    assert scan_group(500, tmp_path)["errors"]


def make(tmp_path, signal_fn=None, stream=None):
    proc = tmp_path / "proc"
    proc.mkdir()
    create(proc, state="Z")
    create(proc, pid=501)
    worker = SimpleNamespace(pid=500)
    clock = [0.0]

    def sleep(dt):
        clock[0] += dt

    events = []

    def send(pgid, sig):
        events.append((pgid, sig))
        create(proc, pid=501, state="Z")

    g = GroupEvidence(
        worker, stream or io.StringIO(), proc_root=proc, send=signal_fn or send, clock=lambda: clock[0], sleep=sleep
    )
    return g, proc, events


def test_graceful_group_no_kill_and_identity(tmp_path):
    g, _, events = make(tmp_path)
    out = g.terminate()
    assert events == [(500, signal.SIGTERM)]
    assert out["no_executing_members"] and out["graceful_group_cleanup_verified"]
    assert not out["group_absent"] and not out["sigkill_dispatched"]
    assert len(out["final_snapshot"]["members"]) == 2
    g.close()


def test_leader_identity_change_refuses_any_signal(tmp_path):
    g, proc, events = make(tmp_path)
    create(proc, start=11)
    out = g.terminate()
    assert not events and out["errors"] and not out["graceful_group_cleanup_verified"]
    g.close()


def test_deadline_escalation_records_dispatch(tmp_path):
    g, proc, events = make(tmp_path)

    def send(pgid, sig):
        events.append((pgid, sig))
        if sig == KILL:
            create(proc, pid=501, state="Z")

    g.send = send
    out = g.terminate()
    assert [x[1] for x in events] == [signal.SIGTERM, KILL]
    assert out["sigkill_dispatched"] and out["no_executing_members"] and not out["graceful_group_cleanup_verified"]
    g.close()


@pytest.mark.parametrize("error", [PermissionError("denied"), ProcessLookupError("absent")])
def test_signal_outcomes_not_assumed_exit(tmp_path, error):
    def send(*a):
        raise error

    g, _, _ = make(tmp_path, send)
    out = g.terminate()
    assert not out["graceful_group_cleanup_verified"] and not out["no_executing_members"]
    assert any(e.get("outcome") in ["permission_error", "absent"] for e in out["events"])
    g.close()


@pytest.mark.parametrize("fault", ["short", "flush", "close"])
def test_journal_failure_does_not_prevent_owned_cleanup(tmp_path, fault):
    class Bad(io.StringIO):
        def write(self, s):
            return len(s) - 1 if fault == "short" else super().write(s)

        def flush(self):
            if fault == "flush":
                raise OSError("flush")

        def close(self):
            if fault == "close":
                raise OSError("close")
            super().close()

    g, _, events = make(tmp_path, stream=Bad())
    g.terminate()
    g.close()
    out = g.summary()
    assert events == [(500, signal.SIGTERM)] and out["errors"] and not out["graceful_group_cleanup_verified"]


def test_scan_missing_directory_is_error(tmp_path):
    assert scan_group(500, tmp_path / "missing")["errors"]


def test_unrelated_kernel_thread_zero_group_is_valid(tmp_path):
    create(tmp_path, pid=2, pgid=0, sid=0)
    create(tmp_path, state="Z")
    out = scan_group(500, tmp_path)
    assert not out["errors"] and not out["executing"] and len(out["members"]) == 1


def test_late_member_in_final_scan_is_cleaned_before_reap(tmp_path):
    g, proc, events = make(tmp_path)
    original = g.snapshot

    def snapshot(label):
        if label == "before_signals":
            create(proc, pid=501, state="Z")
            out = original(label)
            create(proc, pid=501, state="S")
            return out
        return original(label)

    g.snapshot = snapshot
    out = g.terminate()
    assert events == [(500, signal.SIGTERM)] and out["no_executing_members"]
    g.close()


def test_clock_failure_does_not_skip_verified_group_escalation(tmp_path):
    g, proc, events = make(tmp_path)

    def send(pgid, sig):
        events.append((pgid, sig))
        if sig == KILL:
            create(proc, pid=501, state="Z")

    g.send = send
    g.clock = lambda: float("nan")
    out = g.terminate()
    assert events[-1] == (500, KILL) and out["errors"] and not out["graceful_group_cleanup_verified"]
    g.close()


@pytest.mark.parametrize("status", ["supervisor_timeout", "supervisor_wait_error", "supervisor_reap_error"])
def test_new_interruption_paths_retain_ulogs(status):
    from tools.benchmark.capture_disarmed_sensors import needs_supervisor_retention

    assert needs_supervisor_retention({"status": status, "errors": [], "cleanup": {}})
    assert not needs_supervisor_retention(
        {"status": "worker_exited", "errors": [], "cleanup": {"graceful_group_cleanup_verified": True}}
    )


@pytest.mark.parametrize("fault", ["wait_interrupt", "reap_error"])
def test_wait_reap_errors_still_close_terminal_evidence(tmp_path, fault):
    from tools.benchmark.owned_group_evidence import finish_owned_worker

    g, _, _ = make(tmp_path)
    closed = []
    old_close = g.close

    def close():
        closed.append(True)
        old_close()

    g.close = close

    def wait(timeout):
        if fault == "wait_interrupt":
            raise KeyboardInterrupt()

    g.wait_unreaped = wait

    def reap(timeout):
        if fault == "reap_error":
            raise OSError("reap")
        return 0

    g.worker.wait = reap
    out = finish_owned_worker(g.worker, g, 1)
    assert closed and out["errors"] and not out["cleanup"]["graceful_group_cleanup_verified"]
