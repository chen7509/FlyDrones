import copy

import pytest

from tools.benchmark.native_supervisor_integration import audit_supervisor


def fixture(term=False):
    owner = dict(pid=123, pgrp=123, session=123, start_ticks=456, state="R")
    zombie = dict(owner, state="Z")
    empty = dict(members=[], executing=[], errors=[], vanished=[])
    pinned = dict(empty, members=[zombie])
    events = [dict(event="ownership", owner=owner, unreaped_until_cleanup=True),
              dict(event="leader_exit_unreaped", pid=123, code=1, status=2),
              dict(event="snapshot", label="before_signals", observation=pinned)]
    if term:
        live = dict(owner, pid=124, state="S")
        events[-1]["observation"] = dict(empty, members=[zombie, live], executing=[live])
        events += [dict(event="signal_intent", pgid=123, signal=15),
                   dict(event="signal_result", pgid=123, signal=15, outcome="dispatched"),
                   dict(event="snapshot", label="drain", observation=pinned)]
    events += [dict(event="snapshot", label="confirm_drained", observation=pinned),
               dict(event="snapshot", label="after_signals", observation=pinned),
               dict(event="leader_reaped", returncode=2),
               dict(event="snapshot", label="after_leader_reap", observation=empty)]
    for i, event in enumerate(events):
        event["monotonic_s"] = 1.0 + i / 10
    cleanup = dict(owner=owner, events=events, errors=[], final_snapshot=empty,
                   no_executing_members=True, group_absent=True, sigkill_dispatched=False,
                   graceful_group_cleanup_verified=True, all_descendant_cleanup_qualified=False)
    return dict(status="worker_exited", worker_pid=123, worker_exit=2, timeout_s=90,
                capture_status="capture_failed", errors=[], cleanup=cleanup), copy.deepcopy(events)


@pytest.mark.parametrize("term", [False, True])
def test_scoped_valid_failure(term):
    summary, journal = fixture(term)
    result = audit_supervisor(summary, journal)
    assert result["qualified"] is True
    assert result["supervisor_sigkill_dispatched"] is False
    assert result["all_descendant_cleanup_qualified"] is False
    assert len(result["signals"]) == int(term)


@pytest.mark.parametrize("case", ["missing_journal", "different_journal", "identity", "bool_pid",
    "float_exit", "nan_clock", "regressed_clock", "missing_wait", "reap_first", "missing_final",
    "unmatched_signal", "foreign_signal", "kill", "late_signal", "scan_error", "live_final",
    "zombie_final", "summary_error", "cleanup_error", "summary_lie", "completed", "foreign_member"])
def test_reject_incomplete_or_inconsistent_evidence(case):
    s, j = fixture(term=True)
    e = s["cleanup"]["events"]
    if case == "missing_journal":
        j = []
    elif case == "different_journal":
        j[0]["owner"]["start_ticks"] += 1
    elif case == "identity":
        e[0]["owner"] = dict(e[0]["owner"], start_ticks=999)
    elif case == "bool_pid":
        s["worker_pid"] = True
    elif case == "float_exit":
        s["worker_exit"] = 2.0
    elif case == "nan_clock":
        e[2]["monotonic_s"] = float("nan")
    elif case == "regressed_clock":
        e[2]["monotonic_s"] = 0
    elif case == "missing_wait":
        e.pop(1)
    elif case == "reap_first":
        e[1], e[-2] = e[-2], e[1]
    elif case == "missing_final":
        e.pop()
    elif case == "unmatched_signal":
        e.pop(4)
    elif case == "foreign_signal":
        e[3]["pgid"] = e[4]["pgid"] = 999
    elif case == "kill":
        e[3]["signal"] = e[4]["signal"] = 9
    elif case == "late_signal":
        pair = e[3:5]
        del e[3:5]
        e[-1:-1] = pair
        for i, row in enumerate(e):
            row["monotonic_s"] = 1 + i / 10
    elif case == "scan_error":
        e[2]["observation"]["errors"] = ["permission denied"]
    elif case in ("live_final", "zombie_final"):
        member = dict(s["cleanup"]["owner"], state="S" if case == "live_final" else "Z")
        final = dict(members=[member], executing=[member] if case == "live_final" else [], errors=[], vanished=[])
        e[-1]["observation"] = s["cleanup"]["final_snapshot"] = final
    elif case == "summary_error":
        s["errors"] = ["unknown"]
    elif case == "cleanup_error":
        s["cleanup"]["errors"] = ["unknown"]
    elif case == "summary_lie":
        s["cleanup"]["no_executing_members"] = 1
    elif case == "completed":
        s["capture_status"] = "capture_completed"
    elif case == "foreign_member":
        e[2]["observation"]["members"][0]["session"] = 999
    if case not in ("missing_journal", "different_journal"):
        j = copy.deepcopy(e)
    with pytest.raises(ValueError):
        audit_supervisor(s, j)


@pytest.mark.parametrize("label", ["before_signals", "confirm_drained", "before_escalation"])
def test_reject_whole_signal_pair_omission(label):
    s, _ = fixture()
    e = s["cleanup"]["events"]
    live = dict(s["cleanup"]["owner"], pid=124, state="S")
    obs = dict(members=[dict(s["cleanup"]["owner"], state="Z"), live], executing=[live], errors=[], vanished=[])
    if label == "before_escalation":
        e.insert(4, dict(event="snapshot", label=label, observation=obs))
    else:
        next(row for row in e if row.get("label") == label)["observation"] = obs
    for i, row in enumerate(e):
        row["monotonic_s"] = 1 + i / 10
    with pytest.raises(ValueError):
        audit_supervisor(s, copy.deepcopy(e))


@pytest.mark.parametrize("mutation", [None, "after_manifest", "before_copy", "after_copy", "missing_copy", "bool_size"])
def test_retained_snapshot_hashes(tmp_path, mutation):
    import hashlib
    import json

    from tools.benchmark.native_supervisor_integration import audit_snapshots

    for side in ("before", "after"):
        d = tmp_path / side
        d.mkdir()
        (d / "0-source.py").write_bytes(b"source\n")
        meta = [dict(path="/frozen/source.py", bytes=7, sha256=hashlib.sha256(b"source\n").hexdigest())]
        (d / "manifest.json").write_text(json.dumps(meta))
    if mutation == "after_manifest":
        meta[0]["sha256"] = "0" * 64
        (tmp_path / "after/manifest.json").write_text(json.dumps(meta))
    elif mutation in ("before_copy", "after_copy"):
        (tmp_path / mutation.split("_")[0] / "0-source.py").write_bytes(b"changed")
    elif mutation == "missing_copy":
        (tmp_path / "after/0-source.py").unlink()
    elif mutation == "bool_size":
        meta[0]["bytes"] = True
        for side in ("before", "after"):
            (tmp_path / side / "manifest.json").write_text(json.dumps(meta))
    if mutation is None:
        assert audit_snapshots(tmp_path / "before", tmp_path / "after")["copied_files_per_snapshot"] == 1
    else:
        with pytest.raises(ValueError):
            audit_snapshots(tmp_path / "before", tmp_path / "after")
