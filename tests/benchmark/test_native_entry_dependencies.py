"""Real bill producer with explicit tool-protocol fixtures; never native acceptance."""

import importlib
import json
from pathlib import Path

import pytest


def fixture(tmp_path, monkeypatch):
    m = importlib.import_module("tools.benchmark.native_entry_dependencies")
    root = tmp_path / "installed"
    root.mkdir()
    paths = {}
    for name in [
        "libgz-rendering8-ogre2.so.8.2.3",
        "libOgreNextMain.so.2.3.1",
        "libOgreNextPlanarReflections.so.2.3.1",
        "libOgreNextHlmsPbs.so.2.3.1",
        "ldd",
        "readelf",
        "python",
        "loader",
    ]:
        paths[name] = root / name
        paths[name].write_bytes(b"\x7fELF" + name.encode())
    monkeypatch.setattr(
        m,
        "tool_paths",
        lambda: {
            key: str(paths[value])
            for key, value in {"ldd": "ldd", "readelf": "readelf", "python": "python", "loader": "loader"}.items()
        },
    )
    calls = []
    selected = [
        str(paths[name])
        for name in ["libOgreNextMain.so.2.3.1", "libOgreNextPlanarReflections.so.2.3.1", "libOgreNextHlmsPbs.so.2.3.1"]
    ]

    def run(argv, env):
        calls.append((argv, env))
        if argv[-1] == "--version":
            out = b"fixture version 1\n"
        elif argv[1] == "-d":
            out = (
                b"Dynamic section at offset 0x1 contains 5 entries:\n"
                + b"".join((" 0x1 (NEEDED) Shared library: [" + Path(p).name + "]\n").encode() for p in selected)
                + b" 0x1d (RUNPATH) Library runpath: [/usr/lib/x86_64-linux-gnu/OGRE-2.3]\n 0x0 (NULL) 0x0\n"
            )
        else:
            out = b"linux-vdso.so.1 (0x001)\n" + b"".join((Path(p).name + " => " + p + " (0x002)\n").encode() for p in selected)
        return dict(
            argv=argv,
            environment=env,
            pid=123,
            start_utc="fixture-clock",
            end_utc="fixture-clock",
            start_monotonic_ns=10,
            end_monotonic_ns=20,
            elapsed_ns=10,
            exit=0,
            stdout_hex=out.hex(),
            stderr_hex="",
            error=None,
            cleanup=dict(exit=0, descendants="unknown"),
            output_limit_exceeded=False,
            reader_complete=True,
        )

    monkeypatch.setattr(m, "_run_tool", run)
    return m, paths, calls, run


def produce(m, paths, out):
    return m.discover_entry_dependencies(
        {"renderer": [str(paths["libgz-rendering8-ogre2.so.8.2.3"])]},
        [str(paths["libOgreNextHlmsPbs.so.2.3.1"])],
        [],
        str(paths["ldd"].parent),
        out,
    )


def test_candidate_leaf_is_preserved_without_standalone_invocation(tmp_path, monkeypatch):
    m, paths, calls, _ = fixture(tmp_path, monkeypatch)
    bill = produce(m, paths, tmp_path / "bill")
    assert [c[0][-1] for c in calls if c[0][0] == str(paths["ldd"]) and c[0][-1] != "--version"] == [
        str(paths["libgz-rendering8-ogre2.so.8.2.3"])
    ]
    assert bill["candidates"][0]["file"]["requested"] == str(paths["libOgreNextHlmsPbs.so.2.3.1"])
    assert bill["candidates"][0]["classification"] == "selected_from_entry_trace"
    assert bill["runtime_closure_qualified"] is False and all(v is False for v in bill["qualification"].values())
    baseline = [dict(row, role="fixture") for row in bill["files"]]
    assert m.audit_entry_bill(bill, baseline)["entry_trace_consistent"] is True
    bill["candidates"][0]["classification"] = "candidate_only"
    with pytest.raises(ValueError):
        m.audit_entry_bill(bill, baseline)


def test_exit_zero_notfound_retains_actual_earlier_calls_and_failure(tmp_path, monkeypatch):
    m, paths, calls, run = fixture(tmp_path, monkeypatch)

    def missing(argv, env):
        row = run(argv, env)
        if argv[0] == str(paths["ldd"]) and argv[-1] != "--version":
            row["stdout_hex"] = b"libOgreNextMain.so.2.3.1 => not found\n".hex()
        return row

    monkeypatch.setattr(m, "_run_tool", missing)
    with pytest.raises(ValueError, match="dependency"):
        produce(m, paths, tmp_path / "bill")
    saved = json.loads((tmp_path / "bill/entry-bill.json").read_text())
    assert saved["complete"] is False and len(saved["queries"]) >= 5
    assert b"not found" in bytes.fromhex(saved["queries"][-1]["stdout_hex"])
    assert saved["queries"][-1]["exit"] == 0


def test_duplicate_entry_rejected_before_tool_effects(tmp_path, monkeypatch):
    m, paths, calls, _ = fixture(tmp_path, monkeypatch)
    entry = str(paths["libgz-rendering8-ogre2.so.8.2.3"])
    with pytest.raises(ValueError, match="duplicate"):
        m.discover_entry_dependencies({"renderer": [entry], "other": [entry]}, [], [], str(tmp_path), tmp_path / "bill")
    assert calls == []


def test_resolved_alias_retains_requests_without_second_entry_call_protocol(tmp_path, monkeypatch):
    m, paths, calls, _ = fixture(tmp_path, monkeypatch)
    original = str(paths["libgz-rendering8-ogre2.so.8.2.3"])
    alias = paths["ldd"].parent / "declared-renderer-alias.so"
    alias.write_bytes(Path(original).read_bytes())
    real_record = m.file_record

    def alias_record(path):
        # Explicit resolver protocol fixture, not Windows/Linux symlink evidence.
        if str(path) == str(alias):
            return dict(real_record(original), requested=str(alias))
        return real_record(path)

    monkeypatch.setattr(m, "file_record", alias_record)
    bill = m.discover_entry_dependencies(
        {"renderer": [original], "alias": [str(alias)]}, [str(alias)], [], str(alias.parent), tmp_path / "bill"
    )
    assert [row["file"]["requested"] for row in bill["entries"]] == [original, str(alias)]
    assert bill["entries"][1]["alias_of"] == original
    assert bill["entries"][1]["ldd_query"] is None
    assert bill["entries"][1]["selected"] == bill["entries"][0]["selected"]
    assert bill["candidates"][0]["file"]["requested"] == str(alias)
    assert not any(argv[-1] == str(alias) for argv, _ in calls)
    assert sum(argv[0] == str(paths["ldd"]) and argv[-1] != "--version" for argv, _ in calls) == 1
    baseline = [dict(row, role="fixture") for row in bill["files"]]
    m.audit_entry_bill(bill, baseline)
    bill["entries"][1]["selected"] = []
    with pytest.raises(ValueError, match="alias inherited"):
        m.audit_entry_bill(bill, baseline)


def test_changed_candidate_after_actual_trace_is_refused(tmp_path, monkeypatch):
    m, paths, _, run = fixture(tmp_path, monkeypatch)

    def change(argv, env):
        row = run(argv, env)
        if argv[0] == str(paths["ldd"]) and argv[-1] != "--version":
            paths["libOgreNextHlmsPbs.so.2.3.1"].write_bytes(b"\x7fELFchanged")
        return row

    monkeypatch.setattr(m, "_run_tool", change)
    with pytest.raises(ValueError, match="changed"):
        produce(m, paths, tmp_path / "bill")
    assert json.loads((tmp_path / "bill/entry-bill.json").read_text())["complete"] is False


def test_empty_tool_version_is_not_pre_attestation(tmp_path, monkeypatch):
    m, paths, _, run = fixture(tmp_path, monkeypatch)

    def empty(argv, env):
        row = run(argv, env)
        if argv[-1] == "--version":
            row["stdout_hex"] = ""
        return row

    monkeypatch.setattr(m, "_run_tool", empty)
    with pytest.raises(ValueError, match="version"):
        produce(m, paths, tmp_path / "bill")


def test_real_owned_python_timeout_keeps_partial_stream_and_reaps(tmp_path):
    import sys

    m = importlib.import_module("tools.benchmark.native_entry_dependencies")
    row = m._run_tool(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys,time; print('partial',flush=True); print('error-tail',file=sys.stderr,flush=True); time.sleep(30)",
        ],
        {},
    )
    m.write_manifest(tmp_path / "owned-python-timeout.json", row)
    assert b"partial" in bytes.fromhex(row["stdout_hex"])
    assert b"error-tail" in bytes.fromhex(row["stderr_hex"])
    assert "TimeoutExpired" in row["error"]
    assert row["cleanup"]["terminate_sent"] is True and row["cleanup"]["exit"] is not None
    assert row["reader_complete"] is True and row["elapsed_ns"] >= 10_000_000_000


def test_real_owned_python_stream_cap_is_bounded_and_refused(tmp_path):
    import sys

    m = importlib.import_module("tools.benchmark.native_entry_dependencies")
    row = m._run_tool([sys.executable, "-c", "import os; os.write(1,b'x'*(3*1024*1024))"], {})
    m.write_manifest(tmp_path / "owned-python-output-cap.json", row)
    assert len(bytes.fromhex(row["stdout_hex"])) <= 2 * 1024 * 1024
    assert row["output_limit_exceeded"] is True and row["error"] is not None
    with pytest.raises(ValueError):
        m._successful(row)


@pytest.mark.parametrize("corrupt", ["coverage", "command", "monotonic", "writer"])
def test_real_bill_refuses_trace_and_journal_faults(tmp_path, monkeypatch, corrupt):
    m, paths, _, run = fixture(tmp_path, monkeypatch)

    def faulty(argv, env):
        row = run(argv, env)
        if argv[0] == str(paths["ldd"]) and argv[-1] != "--version":
            if corrupt == "coverage":
                row["stdout_hex"] = b"".join(
                    line for line in bytes.fromhex(row["stdout_hex"]).splitlines(keepends=True) if b"Planar" not in line
                ).hex()
            elif corrupt == "command":
                row["argv"] = ["undeclared"]
            elif corrupt == "monotonic":
                row["end_monotonic_ns"] = 1
        return row

    monkeypatch.setattr(m, "_run_tool", faulty)
    if corrupt == "writer":
        write = m.write_manifest

        def failing(path, data):
            if path.name.startswith("query-"):
                raise OSError("fixture journal failure")
            return write(path, data)

        monkeypatch.setattr(m, "write_manifest", failing)
    with pytest.raises((ValueError, OSError)):
        produce(m, paths, tmp_path / "bill")
    saved = json.loads((tmp_path / "bill/entry-bill.json").read_text())
    assert saved["complete"] is False and saved["error"] is not None


def test_candidate_only_and_extra_bill_file_never_gain_entry_eligibility(tmp_path, monkeypatch):
    m, paths, calls, _ = fixture(tmp_path, monkeypatch)
    other = tmp_path / "unused.so"
    other.write_bytes(b"\x7fELFunused")
    bill = m.discover_entry_dependencies(
        {"renderer": [str(paths["libgz-rendering8-ogre2.so.8.2.3"])]}, [str(other)], [], str(other.parent), tmp_path / "bill"
    )
    assert bill["candidates"][0]["classification"] == "candidate_only"
    assert all(str(other) not in argv for argv, _ in calls)
    extra = tmp_path / "extra.so"
    extra.write_bytes(b"\x7fELFextra")
    row = m.file_record(extra)
    bill["files"].append(row)
    bill["files_after"].append(row)
    with pytest.raises(ValueError, match="extra"):
        m.audit_entry_bill(bill, bill["files"])


def test_tool_mutation_between_commands_is_refused_even_if_later_restored(tmp_path, monkeypatch):
    m, paths, calls, run = fixture(tmp_path, monkeypatch)
    original = paths["readelf"].read_bytes()

    def changing(argv, env):
        row = run(argv, env)
        if argv == [str(paths["ldd"]), "--version"]:
            paths["readelf"].write_bytes(b"\x7fELFchanged-tool")
        if argv == [str(paths["readelf"]), "--version"]:
            paths["readelf"].write_bytes(original)
        return row

    monkeypatch.setattr(m, "_run_tool", changing)
    with pytest.raises(ValueError, match="changed"):
        produce(m, paths, tmp_path / "bill")

    assert not any(argv == [str(paths["readelf"]), "--version"] for argv, _ in calls)


def test_self_consistent_substituted_ldd_cannot_pass_fixed_tool_audit(tmp_path, monkeypatch):
    m, paths, _, _ = fixture(tmp_path, monkeypatch)
    bill = produce(m, paths, tmp_path / "bill")
    replacement = tmp_path / "other-ldd"
    replacement.write_bytes(b"\x7fELFother")
    old = str(paths["ldd"])
    new = str(replacement)
    newrow = m.file_record(new)
    for key in ("tools_before", "tools_after"):
        bill[key]["ldd"] = newrow
    for key in ("files", "files_after"):
        bill[key] = [newrow if r["requested"] == old else r for r in bill[key]]
    for q in bill["queries"]:
        if q["argv"][0] == old:
            q["argv"][0] = new
            for key in ("input_before", "input_after"):
                q[key].pop(old)
                q[key][new] = newrow
    with pytest.raises(ValueError, match="tool"):
        m.audit_entry_bill(bill, bill["files"])


def test_journal_failure_does_not_replace_dependency_primary_error(tmp_path, monkeypatch):
    m, paths, _, run = fixture(tmp_path, monkeypatch)

    def failed(argv, env):
        row = run(argv, env)
        row["exit"] = 2
        row["cleanup"]["exit"] = 2
        row["error"] = "actual fixture dependency failure"
        return row

    monkeypatch.setattr(m, "_run_tool", failed)
    write = m.write_manifest

    def broken(path, data):
        if path.name.startswith("query-"):
            raise OSError("fixture journal failure")
        return write(path, data)

    monkeypatch.setattr(m, "write_manifest", broken)
    with pytest.raises(ValueError, match="dependency"):
        produce(m, paths, tmp_path / "bill")
    saved = json.loads((tmp_path / "bill/entry-bill.json").read_text())
    assert "dependency" in saved["error"] and "journal_error" in saved["queries"][0]


def test_terminate_exception_still_waits_and_escalates_owned_child(monkeypatch):
    import io
    import subprocess

    m = importlib.import_module("tools.benchmark.native_entry_dependencies")
    calls = []

    class Process:
        pid = 99
        stdout = io.BytesIO()
        stderr = io.BytesIO()
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            calls.append("terminate")
            raise OSError("fixture terminate refused")

        def kill(self):
            calls.append("kill")
            self.returncode = -9

        def wait(self, timeout):
            calls.append(("wait", timeout))
            if self.returncode is None:
                raise subprocess.TimeoutExpired("fixture", timeout)
            return self.returncode

    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: Process())

    def thread(*a, **k):
        raise RuntimeError("fixture reader bootstrap failed")

    monkeypatch.setattr(m.threading, "Thread", thread)
    row = m._run_tool(["fixture"], {})
    assert calls == ["terminate", ("wait", 5), "kill", ("wait", 5)]
    assert row["cleanup"]["exit"] == -9 and "terminate_error" in row["cleanup"]
