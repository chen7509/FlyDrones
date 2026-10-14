"""Entry-context dependency production. File traces grant no runtime/source authority."""

from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal
from tools.benchmark.declared_runtime_snapshot import file_record, write_manifest

SCHEMA = "raw-entry-dependency-bill-v1"
QUALIFICATION = {
    k: False for k in ("source", "clock", "measured_calibration", "accuracy", "teacher", "fusion", "training", "flight")
}
LIMIT = 2 * 1024**2
OGRE_NAMES = {"libOgreNextMain.so.2.3.1", "libOgreNextPlanarReflections.so.2.3.1", "libOgreNextHlmsPbs.so.2.3.1"}
OGRE_DIR = "/usr/lib/x86_64-linux-gnu/OGRE-2.3"
BASE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def tool_paths():
    return dict(ldd="/usr/bin/ldd", readelf="/usr/bin/readelf", python=sys.executable, loader="/lib64/ld-linux-x86-64.so.2")


def _run_tool(argv, env):
    """Bound owned Popen and each stream; escaped descendants remain unknown."""
    start = time.monotonic_ns()
    row = dict(
        argv=argv,
        environment=env,
        pid=None,
        start_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        end_utc=None,
        start_monotonic_ns=start,
        end_monotonic_ns=None,
        elapsed_ns=None,
        exit=None,
        stdout_hex="",
        stderr_hex="",
        error=None,
        cleanup=None,
        output_limit_exceeded=False,
        reader_complete=False,
    )
    process = None
    streams = [bytearray(), bytearray()]
    exceeded = threading.Event()
    readers, read_errors = [], []

    def read(pipe, bucket):
        try:
            while chunk := os.read(pipe.fileno(), 65536):
                remaining = LIMIT - len(bucket)
                bucket.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded.set()
                    return
        except Exception as exc:
            read_errors.append(repr(exc))

    try:
        process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        row["pid"] = process.pid
        for pipe, bucket in zip((process.stdout, process.stderr), streams, strict=True):
            thread = threading.Thread(target=read, args=(pipe, bucket), daemon=True)
            thread.start()
            readers.append(thread)
        deadline = time.monotonic() + 10
        while process.poll() is None:
            if exceeded.is_set():
                raise ValueError("dependency command output cap exceeded")
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(argv, 10)
            exceeded.wait(0.02)
        row["exit"] = process.returncode
    except BaseException as exc:
        row["error"] = repr(exc)
    finally:
        if process is not None:
            cleanup = dict(before=process.poll(), exit=None, descendants="unknown")
            if cleanup["before"] is None:
                try:
                    process.terminate()
                    cleanup["terminate_sent"] = True
                except Exception as exc:
                    cleanup["terminate_error"] = repr(exc)
            try:
                cleanup["exit"] = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    cleanup["kill_sent"] = True
                except Exception as exc:
                    cleanup["kill_error"] = repr(exc)
                try:
                    cleanup["exit"] = process.wait(timeout=5)
                except Exception as exc:
                    cleanup["error"] = repr(exc)
            except Exception as exc:
                cleanup["error"] = repr(exc)
            if row["exit"] is None:
                row["exit"] = cleanup["exit"]
            if cleanup.get("error"):
                row["error"] = row["error"] or cleanup["error"]
            row["cleanup"] = cleanup
            deadline = time.monotonic() + 1
            for thread in readers:
                thread.join(timeout=max(0, deadline - time.monotonic()))
            row["reader_complete"] = not any(t.is_alive() for t in readers)
            # Never block closing a pipe held by a still-live reader. That case
            # refuses the whole bill; enclosing scope bounds residual resources.
            if row["reader_complete"]:
                for pipe in (process.stdout, process.stderr):
                    pipe.close()
            else:
                row["error"] = row["error"] or "owned stream readers incomplete; residual descendants unknown"
        row["output_limit_exceeded"] = exceeded.is_set()
        if exceeded.is_set() or read_errors:
            row["error"] = row["error"] or (repr(read_errors) if read_errors else "output cap exceeded")
        row.update(
            stdout_hex=streams[0].hex(),
            stderr_hex=streams[1].hex(),
            end_monotonic_ns=time.monotonic_ns(),
            end_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        row["elapsed_ns"] = row["end_monotonic_ns"] - start
    return row


def _absolute(path):
    if type(path) is not str or not Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError("absolute non-traversing declared path required")
    return path


def _successful(row):
    if (
        type(row["exit"]) is not int
        or row["exit"] != 0
        or row["error"] is not None
        or row["output_limit_exceeded"] is not False
        or row["reader_complete"] is not True
        or type(row["pid"]) is not int
        or row["pid"] <= 0
    ):
        raise ValueError("dependency command failed/partial/exceeded")
    start, end, elapsed = (row[k] for k in ("start_monotonic_ns", "end_monotonic_ns", "elapsed_ns"))
    if any(type(n) is not int or n < 0 for n in (start, end, elapsed)) or end < start or end - start != elapsed:
        raise ValueError("dependency command local monotonic facts invalid")
    if len(bytes.fromhex(row["stdout_hex"])) > LIMIT or len(bytes.fromhex(row["stderr_hex"])) > LIMIT:
        raise ValueError("dependency retained output exceeded")
    if (
        row.get("kind", "").startswith("version:")
        and not (bytes.fromhex(row["stdout_hex"]) + bytes.fromhex(row["stderr_hex"])).strip()
    ):
        raise ValueError("dependency tool version output missing")
    if row["cleanup"].get("exit") != row["exit"] or row["cleanup"].get("descendants") != "unknown":
        raise ValueError("dependency owned cleanup facts differ")


def _ldd(data):
    lines = data.decode("utf8", errors="strict").splitlines()
    paths, nonfiles = [], []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"linux-vdso\S* \(0x[0-9a-fA-F]+\)", line):
            nonfiles.append(line)
            continue
        match = re.fullmatch(r"(?:[^\s]+ => )?(.+?) \(0x[0-9a-fA-F]+\)", line)
        if match is None:
            raise ValueError("unresolved or malformed dependency line: " + line)
        path = _absolute(match[1])
        if path in paths:
            raise ValueError("duplicate dependency selected path")
        paths.append(path)
    if not paths:
        raise ValueError("no complete ELF dependency paths")
    return dict(selected=paths, nonfiles=nonfiles)


def _dynamic(data):
    text = data.decode("utf8", errors="strict")
    if "Dynamic section" not in text:
        raise ValueError("ELF dynamic metadata missing")
    return dict(
        needed=re.findall(r"\(NEEDED\).*\[([^\]\n]+)\]", text),
        runpath=re.findall(r"\(RUNPATH\).*\[([^\]\n]*)\]", text),
        rpath=re.findall(r"\(RPATH\).*\[([^\]\n]*)\]", text),
        soname=re.findall(r"\(SONAME\).*\[([^\]\n]+)\]", text),
    )


def _environment(path, agent_paths, agent_lib):
    result = dict(BASE_ENV)
    if path in agent_paths:
        if Path(path).parent.resolve() not in {Path(agent_lib).resolve(), Path(agent_lib).parent / "bin"}:
            raise ValueError("Agent selected entry outside declared directory")
        result["LD_LIBRARY_PATH"] = agent_lib
    return result


def _coverage(entries):
    renderer = [r for r in entries if Path(r["file"]["requested"]).name == "libgz-rendering8-ogre2.so.8.2.3"]
    if len(renderer) != 1:
        raise ValueError("actual renderer entry coverage required")
    row = renderer[0]
    if not OGRE_NAMES.issubset({Path(p).name for p in row["selected"]}):
        raise ValueError("renderer OGRE dependency coverage missing")
    if not OGRE_NAMES.issubset(set(row["dynamic"]["needed"])) or OGRE_DIR not in row["dynamic"]["runpath"]:
        raise ValueError("renderer direct dependency/RUNPATH relation changed")


def discover_entry_dependencies(entries, candidates, agent_paths, agent_lib, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("entry dependency output already exists; no replay")
    output.mkdir()
    bill = dict(
        schema=SCHEMA,
        input_entries=entries,
        input_candidates=candidates,
        agent_paths=agent_paths,
        agent_lib=agent_lib,
        entries=[],
        candidates=[],
        files=[],
        tools_before={},
        tools_after={},
        files_after=[],
        queries=[],
        complete=False,
        error=None,
        runtime_closure_qualified=False,
        qualification=dict(QUALIFICATION),
    )
    files = {}
    primary = None

    def remember(path):
        row = file_record(path)
        if path in files and not _typed_equal(files[path], row):
            raise ValueError("dependency file changed while discovering")
        files[path] = row
        bill["files"] = list(files.values())
        return row

    def invoke(kind, argv, env):
        row = dict(kind=kind, argv=argv, environment=env, invoked=False, input_before={}, input_after={}, error=None)
        before = {}
        primary = None
        inputs = [argv[0]] + ([] if kind.startswith("version:") else [argv[-1]])
        try:
            before = {p: remember(p) for p in inputs}
            row["input_before"] = before
            observed = _run_tool(argv, env)
            row.update(observed, kind=kind, invoked=observed["pid"] is not None)
            row["input_after"] = {p: remember(p) for p in inputs}
            _successful(row)
            return row
        except BaseException as exc:
            primary = exc
            row["error"] = row["error"] or repr(exc)
            raise
        finally:
            bill["queries"].append(row)
            try:
                write_manifest(output / f"query-{len(bill['queries']):04d}.json", row)
            except Exception as exc:
                row["journal_error"] = repr(exc)
                if primary is None:
                    raise
                primary.add_note("query persistence failure: " + repr(exc))

    try:
        if (
            type(entries) is not dict
            or not entries
            or any(type(k) is not str or not k or type(v) is not list or not v for k, v in entries.items())
        ):
            raise ValueError("nonempty typed entry roles required")
        requested = [_absolute(p) for paths in entries.values() for p in paths]
        if len(set(requested)) != len(requested):
            raise ValueError("duplicate requested entry")
        if (
            not 1 <= len(requested) <= 256
            or type(candidates) is not list
            or len(candidates) > 4096
            or len(set(candidates)) != len(candidates)
        ):
            raise ValueError("bounded unique entries/candidates required")
        for path in candidates:
            _absolute(path)
        if (
            type(agent_paths) is not list
            or len(set(agent_paths)) != len(agent_paths)
            or not set(agent_paths).issubset(set(requested))
        ):
            raise ValueError("Agent paths must be unique selected entries")
        _absolute(agent_lib)
        for path in requested + candidates:
            remember(path)
        tools = tool_paths()
        if set(tools) != {"ldd", "readelf", "python", "loader"}:
            raise ValueError("fixed dependency tools required")
        bill["tools_before"] = {key: remember(_absolute(path)) for key, path in tools.items()}
        for name, tool in tools.items():
            invoke("version:" + name, [tool, "--version"], dict(BASE_ENV))
        seen = set()
        for role, paths in entries.items():
            for path in paths:
                record = files[path]
                resolved = record["resolved"]
                with Path(path).open("rb") as stream:
                    elf = stream.read(4) == b"\x7fELF"
                row = dict(
                    role=role,
                    file=record,
                    elf=elf,
                    alias_of=None,
                    ldd_query=None,
                    dynamic_query=None,
                    selected=[],
                    nonfiles=[],
                    dynamic=None,
                )
                bill["entries"].append(row)
                if resolved in seen:
                    original = next(r for r in bill["entries"][:-1] if r["file"]["resolved"] == resolved)
                    if _environment(path, agent_paths, agent_lib) != _environment(
                        original["file"]["requested"], agent_paths, agent_lib
                    ):
                        raise ValueError("entry aliases have different loader contexts")
                    row.update(
                        alias_of=original["file"]["requested"],
                        selected=original["selected"],
                        nonfiles=original["nonfiles"],
                        dynamic=original["dynamic"],
                    )
                    continue
                seen.add(resolved)
                if not elf:
                    continue
                env = _environment(path, agent_paths, agent_lib)
                dynamic = invoke("dynamic", [tools["readelf"], "-d", path], env)
                row.update(dynamic_query=len(bill["queries"]), dynamic=_dynamic(bytes.fromhex(dynamic["stdout_hex"])))
                traced = invoke("ldd", [tools["ldd"], path], env)
                row.update(ldd_query=len(bill["queries"]), **_ldd(bytes.fromhex(traced["stdout_hex"])))
                for selected in row["selected"]:
                    remember(selected)
        selected_resolved = {files[p]["resolved"] for row in bill["entries"] for p in row["selected"]}
        bill["candidates"] = [
            dict(
                file=files[p],
                classification="selected_from_entry_trace" if files[p]["resolved"] in selected_resolved else "candidate_only",
            )
            for p in candidates
        ]
        _coverage(bill["entries"])
        bill["files_after"] = [file_record(path) for path in files]
        if not _typed_equal(bill["files"], bill["files_after"]):
            raise ValueError("dependency input/tool changed after trace")
        bill["tools_after"] = {key: file_record(path) for key, path in tools.items()}
        if not _typed_equal(bill["tools_before"], bill["tools_after"]):
            raise ValueError("dependency tool changed")
        bill["complete"] = True
        audit_entry_bill(bill, bill["files"])
        return bill
    except BaseException as exc:
        primary = exc
        bill.update(complete=False, error=repr(exc))
        raise
    finally:
        try:
            write_manifest(output / "entry-bill.json", bill)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("aggregate persistence failure: " + repr(exc))


def audit_entry_bill(bill, baseline):
    """Recompute joins from retained raw calls; no caller eligibility assertion."""
    keys = {
        "schema",
        "input_entries",
        "input_candidates",
        "agent_paths",
        "agent_lib",
        "entries",
        "candidates",
        "files",
        "tools_before",
        "tools_after",
        "files_after",
        "queries",
        "complete",
        "error",
        "runtime_closure_qualified",
        "qualification",
    }
    if (
        type(bill) is not dict
        or set(bill) != keys
        or bill["schema"] != SCHEMA
        or bill["complete"] is not True
        or bill["error"] is not None
        or bill["runtime_closure_qualified"] is not False
        or not _typed_equal(bill["qualification"], QUALIFICATION)
    ):
        raise ValueError("complete exact entry dependency bill required")
    files = {r["requested"]: r for r in bill["files"]}
    known = {r["requested"]: {k: v for k, v in r.items() if k != "role"} for r in baseline}
    if (
        len(files) != len(bill["files"])
        or len(known) != len(baseline)
        or any(not _typed_equal(row, known.get(path)) for path, row in files.items())
    ):
        raise ValueError("entry files absent/duplicate/different baseline")
    if not _typed_equal(bill["files"], bill["files_after"]) or not _typed_equal(bill["tools_before"], bill["tools_after"]):
        raise ValueError("entry tool/input post identity differs")
    expected_entries = [(role, p) for role, paths in bill["input_entries"].items() for p in paths]
    if len(expected_entries) > 256 or len({p for _, p in expected_entries}) != len(expected_entries):
        raise ValueError("duplicate/bounded entry inputs required")
    if [(r["role"], r["file"]["requested"]) for r in bill["entries"]] != expected_entries:
        raise ValueError("entry role/member set differs")
    tools = bill["tools_before"]
    if set(tools) != {"ldd", "readelf", "python", "loader"} or any(
        not _typed_equal(r, files.get(r["requested"])) for r in tools.values()
    ):
        raise ValueError("exact tool identity join required")
    fixed_tools = tool_paths()
    if set(fixed_tools) != set(tools) or any(tools[k]["requested"] != fixed_tools[k] for k in tools):
        raise ValueError("entry fixed tool path differs from current producer")
    expected_calls = [("version:" + k, [v["requested"], "--version"], dict(BASE_ENV)) for k, v in tools.items()]
    used = {r["requested"] for r in tools.values()} | set(bill["input_candidates"])
    seen = {}
    for row in bill["entries"]:
        path = row["file"]["requested"]
        _absolute(path)
        used.add(path)
        if not _typed_equal(row["file"], files.get(path)) or type(row["elf"]) is not bool:
            raise ValueError("entry identity differs")
        resolved = row["file"]["resolved"]
        env = _environment(path, bill["agent_paths"], bill["agent_lib"])
        if resolved in seen:
            original = seen[resolved]
            if (
                row["alias_of"] != original["file"]["requested"]
                or row["ldd_query"] is not None
                or row["dynamic_query"] is not None
            ):
                raise ValueError("alias entry invoked twice")
            if env != _environment(original["file"]["requested"], bill["agent_paths"], bill["agent_lib"]):
                raise ValueError("alias context differs")
            for key in ("elf", "dynamic", "selected", "nonfiles"):
                if not _typed_equal(row[key], original[key]):
                    raise ValueError("alias inherited trace differs")
        else:
            seen[resolved] = row
            if row["alias_of"] is not None:
                raise ValueError("undeclared alias")
            if row["elf"]:
                expected_calls.append(("dynamic", [tools["readelf"]["requested"], "-d", path], env))
                dynamic_number = len(expected_calls)
                expected_calls.append(("ldd", [tools["ldd"]["requested"], path], env))
                ldd_number = len(expected_calls)
                if row["dynamic_query"] != dynamic_number or row["ldd_query"] != ldd_number:
                    raise ValueError("entry raw query index differs")
                dynamic = _dynamic(bytes.fromhex(bill["queries"][dynamic_number - 1]["stdout_hex"]))
                traced = _ldd(bytes.fromhex(bill["queries"][ldd_number - 1]["stdout_hex"]))
                if not _typed_equal(row["dynamic"], dynamic) or any(not _typed_equal(row[k], traced[k]) for k in traced):
                    raise ValueError("entry raw dependency/dynamic trace differs")
            elif any(row[k] not in (None, []) for k in ("ldd_query", "dynamic_query", "dynamic", "selected", "nonfiles")):
                raise ValueError("non-ELF entry claims a trace")
        used.update(row["selected"])
    if len(expected_calls) != len(bill["queries"]):
        raise ValueError("extra/missing dependency command")
    for row, (kind, argv, env) in zip(bill["queries"], expected_calls, strict=True):
        _successful(row)
        inputs = [argv[0]] + ([] if kind.startswith("version:") else [argv[-1]])
        pins = {p: files[p] for p in inputs}
        if (
            row.get("invoked") is not True
            or not _typed_equal(row.get("input_before"), pins)
            or not _typed_equal(row.get("input_after"), pins)
        ):
            raise ValueError("per-command tool/entry pin join differs")
        if row["kind"] != kind or row["argv"] != argv or row["environment"] != env:
            raise ValueError("entry actual command/context differs")
    selected = {files[p]["resolved"] for row in bill["entries"] for p in row["selected"]}
    expected_candidates = [
        dict(file=files[p], classification="selected_from_entry_trace" if files[p]["resolved"] in selected else "candidate_only")
        for p in bill["input_candidates"]
    ]
    if (
        len(expected_candidates) > 4096
        or len(set(bill["input_candidates"])) != len(expected_candidates)
        or not _typed_equal(bill["candidates"], expected_candidates)
    ):
        raise ValueError("candidate identity/classification differs")
    if set(files) != used:
        raise ValueError("extra/missing entry dependency file")
    _coverage(bill["entries"])
    return dict(
        entry_trace_consistent=True,
        candidate_only=sum(r["classification"] == "candidate_only" for r in bill["candidates"]),
        runtime_closure_qualified=False,
        qualification=dict(QUALIFICATION),
    )
