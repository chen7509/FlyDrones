"""Offline acceptance of the explicitly failed native-epoch physical study.

This does not control processes or certify descendants outside the owned group.
"""

import json
import math


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def integer(value, expected=None):
    return type(value) is int and (expected is None or value == expected)


def identity(row, pid):
    require(isinstance(row, dict), "missing identity")
    require(all(integer(row.get(k), pid) for k in ("pid", "pgrp", "session")), "leader identity")
    require(integer(row.get("start_ticks")) and row["start_ticks"] >= 0, "leader start ticks")
    require(row.get("state") in set("RSDZTtWXxKPI"), "leader state")


def audit_supervisor(summary, journal):
    """Raise ValueError for insufficient evidence; never infer exit from a signal."""
    try:
        return _audit(summary, journal)
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ValueError("malformed supervisor integration evidence") from exc


def _audit(s, journal):
    require(s["status"] == "worker_exited" and s["capture_status"] == "capture_failed", "capture status")
    require(integer(s["worker_exit"], 2) and integer(s["timeout_s"], 90), "exit/timeout")
    require(s["errors"] == [], "supervisor errors")
    pid = s["worker_pid"]
    require(integer(pid) and pid > 1, "worker PID")
    c = s["cleanup"]
    identity(c["owner"], pid)
    require(c["errors"] == [], "cleanup errors")
    for key in ("no_executing_members", "group_absent", "graceful_group_cleanup_verified"):
        require(c[key] is True, key)
    for key in ("sigkill_dispatched", "all_descendant_cleanup_qualified"):
        require(c[key] is False, key)
    events = c["events"]
    require(isinstance(events, list) and len(events) >= 7, "missing events")
    # Canonical JSON also distinguishes boolean and integer fields and rejects NaN.
    require(json.dumps(events, sort_keys=True, allow_nan=False) ==
            json.dumps(journal, sort_keys=True, allow_nan=False), "journal mismatch")
    require(events[0]["event"] == "ownership" and events[0]["owner"] == c["owner"] and
            events[0]["unreaped_until_cleanup"] is True, "ownership journal")
    identity(events[0]["owner"], pid)
    wait_index = reap_index = None
    labels, signals = [], []
    pending = None
    last_time = -math.inf
    for i, e in enumerate(events):
        stamp = e["monotonic_s"]
        require(type(stamp) in (float, int) and math.isfinite(stamp) and stamp >= 0 and
                stamp >= last_time, "invalid event clock")
        last_time = stamp
        kind = e["event"]
        if pending is not None:
            require(kind == "signal_result", "missing signal result")
        if kind == "ownership":
            require(i == 0, "duplicate ownership")
        elif kind == "leader_exit_unreaped":
            require(wait_index is None and reap_index is None and i == 1, "unreaped order")
            require(integer(e["pid"], pid) and integer(e["code"], 1) and integer(e["status"], 2), "waitid outcome")
            wait_index = i
        elif kind == "snapshot":
            require(wait_index is not None, "snapshot before wait")
            obs = e["observation"]
            require(obs["errors"] == [] and isinstance(obs["members"], list) and
                    isinstance(obs["executing"], list) and isinstance(obs["vanished"], list), "scan error/schema")
            require(all(integer(p) and p > 0 for p in obs["vanished"]), "vanished PID")
            members = obs["members"]
            require(len({m["pid"] for m in members}) == len(members), "duplicate member")
            for m in members:
                require(integer(m["pid"]) and m["pid"] > 1 and integer(m["pgrp"], pid) and
                        integer(m["session"], pid) and integer(m["start_ticks"]) and
                        m["start_ticks"] >= 0 and m["state"] in set("RSDZTtWXxKPI"), "foreign/invalid member")
                if m["pid"] == pid:
                    require(m["start_ticks"] == c["owner"]["start_ticks"], "leader reuse")
            require(obs["executing"] == [m for m in members if m["state"] not in {"Z", "X", "x"}], "scan execution mismatch")
            label = e["label"]
            require(label in {"before_signals", "confirm_drained", "drain", "before_escalation", "after_signals", "after_leader_reap"}, "scan label")
            if reap_index is None:
                require(label != "after_leader_reap" and any(m["pid"] == pid and m["state"] == "Z" for m in members), "leader not pinned")
            else:
                require(label == "after_leader_reap" and i == len(events) - 1, "post-reap ordering")
                require(obs == c["final_snapshot"] and members == [] and obs["executing"] == [], "final group not absent")
            if label == "after_signals":
                require(obs["executing"] == [], "cleanup not drained")
            labels.append(label)
        elif kind in ("signal_intent", "signal_result"):
            require(wait_index is not None and reap_index is None and "before_signals" in labels and
                    "after_signals" not in labels, "signal ordering")
            require(integer(e["pgid"], pid) and integer(e["signal"], 15), "foreign/escalated signal")
            if kind == "signal_intent":
                pending = e
            else:
                require(pending is not None and e["outcome"] in ("dispatched", "absent"), "signal outcome")
                signals.append(dict(signal=15, outcome=e["outcome"], pgid=pid))
                pending = None
        elif kind == "leader_reaped":
            require(reap_index is None and wait_index is not None and integer(e["returncode"], 2) and
                    labels[-1:] == ["after_signals"], "reap ordering/outcome")
            reap_index = i
        else:
            raise ValueError("unexpected/error event")
    require(pending is None and wait_index is not None and reap_index is not None, "incomplete sequence")
    require(labels.count("before_signals") == labels.count("confirm_drained") ==
            labels.count("after_signals") == labels.count("after_leader_reap") == 1 and
            labels[0] == "before_signals" and labels[-2:] == ["after_signals", "after_leader_reap"], "missing cleanup stages")
    require(events[-1]["event"] == "snapshot" and events[-1]["label"] == "after_leader_reap", "missing terminal scan")
    return dict(qualified=True, scope="recorded supervisor original owned group only",
                owner=c["owner"], signals=signals, journal_events=len(events),
                supervisor_sigkill_dispatched=False, no_executing_members=True, group_absent=True,
                all_descendant_cleanup_qualified=False, capture_status_retained="capture_failed")
