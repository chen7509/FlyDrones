"""Linux owned-session cleanup observations. No claim about escaped descendants."""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from pathlib import Path

TERM, KILL = 15, 9  # Linux signal numbers; synthetic tests also run on Windows.
DEAD = {"Z", "X", "x"}


def parse_stat(text):
    try:
        pid = int(text.split(" (", 1)[0])
        f = text.rsplit(") ", 1)[1].split()
        row = dict(pid=pid, state=f[0], pgrp=int(f[2]), session=int(f[3]), start_ticks=int(f[19]))
        if pid <= 0 or row["pgrp"] < 0 or row["session"] < 0 or row["start_ticks"] < 0:
            raise ValueError("invalid stat identity")
        if row["state"] not in set("RSDZTtWXxKPI"):
            raise ValueError("invalid stat state")
        return row
    except (ValueError, IndexError) as exc:
        raise ValueError("malformed proc stat") from exc


def scan_group(pgid, proc_root=Path("/proc")):
    out = dict(members=[], executing=[], errors=[], vanished=[])
    try:
        paths = list(proc_root.iterdir())
    except OSError as exc:
        out["errors"].append(repr(exc))
        return out
    for path in paths:
        if not path.name.isdigit():
            continue
        try:
            row = parse_stat((path / "stat").read_text())
            if row["pid"] != int(path.name):
                raise ValueError("proc directory identity mismatch")
            if row["pgrp"] == pgid:
                out["members"].append(row)
                if row["state"] not in DEAD:
                    out["executing"].append(row)
        except FileNotFoundError:
            out["vanished"].append(int(path.name))
        except (OSError, ValueError) as exc:
            out["errors"].append(dict(pid=int(path.name), reason=repr(exc)))
    return out


class GroupEvidence:
    def __init__(self, worker, stream, *, proc_root=Path("/proc"), send=None, clock=time.monotonic, sleep=time.sleep):
        self.worker, self.stream, self.proc_root = worker, stream, proc_root
        self.send, self.clock, self.sleep = send or os.killpg, clock, sleep
        self.events, self.errors = [], []
        self.owner, self.final = None, None
        self.sigkill_dispatched = False
        self.last_clock = None
        try:
            if type(worker.pid) is not int or worker.pid <= 1 or worker.pid == os.getpid():
                raise ValueError("invalid owned child PID")
            if hasattr(os, "getpgrp") and worker.pid == os.getpgrp():
                raise ValueError("refuse supervisor's own process group")
            row = self._leader()
            if row["pgrp"] != worker.pid or row["session"] != worker.pid:
                raise ValueError("worker is not fresh session/group leader")
            self.owner = row
            self.emit(dict(event="ownership", owner=row, unreaped_until_cleanup=True))
        except Exception as exc:
            self.errors.append(dict(operation="ownership", reason=repr(exc)))

    def now(self):
        value = self.clock()
        if not math.isfinite(value) or self.last_clock is not None and value < self.last_clock:
            raise ValueError("invalid/regressed cleanup clock")
        self.last_clock = value
        return value

    def emit(self, row):
        # Journal failures remain visible but never disable safe cleanup.
        try:
            row = dict(row, monotonic_s=self.now())
        except Exception as exc:
            self.errors.append(dict(operation="clock", reason=repr(exc)))
            row = dict(row, monotonic_s=None)
        self.events.append(row)
        try:
            text = json.dumps(row, allow_nan=False) + "\n"
            if self.stream.write(text) != len(text):
                raise OSError("short group journal write")
            self.stream.flush()
        except Exception as exc:
            self.errors.append(dict(operation="journal", reason=repr(exc)))

    def _leader(self):
        return parse_stat((self.proc_root / str(self.worker.pid) / "stat").read_text())

    def identity(self):
        if self.owner is None:
            raise ValueError("ownership unavailable")
        row = self._leader()
        if any(row[k] != self.owner[k] for k in ("pid", "pgrp", "session", "start_ticks")):
            raise ValueError("owned leader identity changed")

    def snapshot(self, label):
        out = scan_group(self.worker.pid, self.proc_root)
        if any(m["session"] != self.worker.pid for m in out["members"]):
            out["errors"].append("owned group session mismatch")
        self.final = out
        self.emit(dict(event="snapshot", label=label, observation=out))
        if out["errors"]:
            self.errors.append(dict(operation="scan", label=label, reasons=out["errors"]))
        return out

    def signal(self, number):
        self.identity()
        self.emit(dict(event="signal_intent", pgid=self.worker.pid, signal=number))
        try:
            self.send(self.worker.pid, number)
            outcome = "dispatched"
            if number == KILL:
                self.sigkill_dispatched = True
        except ProcessLookupError:
            outcome = "absent"
        except PermissionError as exc:
            outcome = "permission_error"
            self.errors.append(dict(operation="signal", reason=repr(exc)))
        except OSError as exc:
            outcome = "error"
            self.errors.append(dict(operation="signal", reason=repr(exc)))
        self.emit(dict(event="signal_result", pgid=self.worker.pid, signal=number, outcome=outcome))

    def drain(self, duration):
        deadline = self.now() + duration
        for _ in range(int(duration / 0.05) + 2):
            self.identity()
            out = self.snapshot("drain")
            if not out["errors"] and not out["executing"]:
                return True
            if self.now() >= deadline:
                return False
            self.sleep(0.05)
        return False

    def terminate(self):
        term_sent = False
        try:
            self.identity()
            out = self.snapshot("before_signals")
            if out["errors"] or out["executing"]:
                self.signal(TERM)
                term_sent = True
                self.drain(3)
            # /proc enumeration is not atomic. Reconfirm while the leader is pinned.
            out = self.snapshot("confirm_drained")
            if out["errors"] or out["executing"]:
                if not term_sent:
                    self.signal(TERM)
                    self.drain(3)
                out = self.snapshot("before_escalation")
                if out["errors"] or out["executing"]:
                    self.signal(KILL)
                    self.drain(2)
            out = self.snapshot("after_signals")
            if out["errors"] or out["executing"]:
                raise RuntimeError("owned group not observed drained at final confirmation")
        except Exception as exc:
            self.errors.append(dict(operation="cleanup", reason=repr(exc)))
            self.emit(dict(event="cleanup_error", reason=repr(exc)))
            try:
                # A broken clock/scan must not skip bounded, identity-checked escalation.
                self.signal(KILL)
                self.sleep(0.05)
                self.snapshot("emergency_after_kill")
            except Exception as final_exc:
                self.errors.append(dict(operation="emergency_cleanup", reason=repr(final_exc)))
        return self.summary()

    def wait_unreaped(self, timeout_s):
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("invalid supervisor timeout")
        deadline = self.now() + timeout_s
        while True:
            info = os.waitid(os.P_PID, self.worker.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if info is not None:
                self.emit(dict(event="leader_exit_unreaped", pid=info.si_pid, code=info.si_code, status=info.si_status))
                return
            if self.now() >= deadline:
                raise subprocess.TimeoutExpired("owned worker", timeout_s)
            self.sleep(min(0.05, max(0, deadline - self.now())))

    def close(self):
        for name, op in (("flush", self.stream.flush), ("close", self.stream.close)):
            try:
                op()
            except Exception as exc:
                self.errors.append(dict(operation=name, reason=repr(exc)))

    def summary(self):
        known = self.final is not None and not self.final["errors"]
        stopped = known and not self.final["executing"]
        return dict(
            scope="owned original process group only; escaped descendants not tracked",
            owner=self.owner,
            events=self.events,
            errors=self.errors,
            final_snapshot=self.final,
            no_executing_members=bool(stopped),
            group_absent=bool(known and not self.final["members"]),
            sigkill_dispatched=self.sigkill_dispatched,
            graceful_group_cleanup_verified=bool(stopped and not self.errors and not self.sigkill_dispatched),
            all_descendant_cleanup_qualified=False,
        )


def finish_owned_worker(worker, evidence, timeout_s):
    """Preserve cleanup and terminal evidence on wait/reap errors and Python interruption."""
    status, code, errors = "worker_exited", None, []

    def record(operation, exc):
        errors.append(dict(operation=operation, reason=repr(exc)))
        evidence.errors.append(dict(operation=operation, reason=repr(exc)))
        evidence.emit(dict(event=operation + "_error", reason=repr(exc)))

    try:
        evidence.wait_unreaped(timeout_s)
    except subprocess.TimeoutExpired:
        status = "supervisor_timeout"
    except (Exception, KeyboardInterrupt) as exc:
        status = "supervisor_wait_error"
        record("wait", exc)
    try:
        evidence.terminate()
    except (Exception, KeyboardInterrupt) as exc:
        record("terminate", exc)
        try:
            evidence.signal(KILL)
        except (Exception, KeyboardInterrupt) as fallback:
            record("terminate_fallback", fallback)
    try:
        try:
            code = worker.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            record("reap_timeout", exc)
            evidence.signal(KILL)
            code = worker.wait(timeout=5)
        evidence.emit(dict(event="leader_reaped", returncode=code))
    except (Exception, KeyboardInterrupt) as exc:
        status = "supervisor_reap_error"
        record("reap", exc)
    finally:
        try:
            evidence.snapshot("after_leader_reap")
        except (Exception, KeyboardInterrupt) as exc:
            record("final_snapshot", exc)
        evidence.close()
    return dict(status=status, worker_exit=code, errors=errors, cleanup=evidence.summary())
