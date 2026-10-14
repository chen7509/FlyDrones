"""Real v3 bill, explicit readelf/ldd protocol fixtures; no Linux/SDK acceptance."""

import copy
import importlib
import json
from pathlib import Path

import pytest


def fixture(tmp_path, monkeypatch):
    m = importlib.import_module("tools.benchmark.native_entry_context_v3")
    root = tmp_path / "installed"
    root.mkdir()
    names = [
        "libgz-rendering8-ogre2.so.8.2.3",
        "libOgreNextMain.so.2.3.1",
        "libOgreNextPlanarReflections.so.2.3.1",
        "libOgreNextHlmsPbs.so.2.3.1",
        "ldd",
        "readelf",
        "python",
        "loader",
        "_fixture.cpython-312-x86_64-linux-gnu.so",
        "unused.so",
    ]
    paths = {n: root / n for n in names}
    for n, p in paths.items():
        p.write_bytes(b"\x7fELF" + n.encode())
    tools = {k: str(paths[k]) for k in ["ldd", "readelf", "python", "loader"]}
    monkeypatch.setattr(m, "tool_paths", lambda: tools)
    target = str(paths[names[-2]])
    origin = m.file_record(target)
    context = dict(
        schema="python-extension-context-v1",
        pid=123,
        interpreter=m.file_record(tools["python"]),
        implementation="cpython",
        version="fixture Python3.12.3",
        version_info=[3, 12, 3],
        soabi="cpython-312-x86_64-linux-gnu",
        ext_suffix=".cpython-312-x86_64-linux-gnu.so",
        dlopen_flags=2,
        modules=[
            dict(
                name="_fixture",
                origin=origin,
                module_file=target,
                spec_origin=target,
                loader="_frozen_importlib_external.ExtensionFileLoader",
            )
        ],
    )
    observed_context = copy.deepcopy(context)
    monkeypatch.setattr(m, "collect_python_context", lambda: copy.deepcopy(observed_context))
    selected = [str(paths[n]) for n in names[1:4]]
    calls = []

    def run(argv, env):
        calls.append((argv, env))
        if argv[-1] == "--version":
            data = b"fixture version1\n"
        elif argv[1] == "-d":
            data = (
                b"Dynamic section at offset 0x1 contains 1 entries:\n 0x0 (NULL) 0x0\n"
                if argv[-1] == target
                else b"Dynamic section at offset 0x1 contains 5 entries:\n"
                + b"".join((" 0x1 (NEEDED) Shared library: [" + Path(p).name + "]\n").encode() for p in selected)
                + b" 0x1d (RUNPATH) Library runpath: [/usr/lib/x86_64-linux-gnu/OGRE-2.3]\n 0x0 (NULL) 0x0\n"
            )
        elif argv[1] == "-W":
            data = b"ELF Header:\n  Class: ELF64\n  Data: 2's complement, little endian\n  Type: DYN (Shared object file)\n  Machine: Advanced Micro Devices X86-64\n  Number of program headers: 2\nProgram Headers:\n  Type Offset VirtAddr PhysAddr FileSiz MemSiz Flg Align\n  LOAD 0 0 0 1 1 R 1\n  DYNAMIC 0 0 0 1 1 RW 1\n Section to Segment mapping:\nSymbol table '.dynsym' contains 4 entries:\n Num: Value Size Type Bind Vis Ndx Name\n 0: 0 0 NOTYPE LOCAL DEFAULT UND\n 1: 0 0 NOTYPE GLOBAL DEFAULT UND PyDict_New\n 2: 0 0 NOTYPE WEAK DEFAULT UND __gmon_start__\n 3: 10 16 FUNC GLOBAL DEFAULT 1 PyInit__fixture\n"
        elif argv[-1] == target:
            data = b"\tstatically linked\n"
        else:
            data = b"".join((Path(p).name + " => " + p + " (0x002)\n").encode() for p in selected)
        return dict(
            argv=argv,
            environment=env,
            pid=321,
            start_utc="fixture",
            end_utc="fixture",
            start_monotonic_ns=10,
            end_monotonic_ns=20,
            elapsed_ns=10,
            exit=0,
            stdout_hex=data.hex(),
            stderr_hex="",
            error=None,
            cleanup=dict(exit=0, descendants="unknown"),
            output_limit_exceeded=False,
            reader_complete=True,
        )

    monkeypatch.setattr(m, "_run_tool", run)
    entries = {"renderer": [str(paths[names[0]])], "current-python": [target]}
    return m, paths, context, entries, calls, run


def produce(m, paths, context, entries, out):
    return m.discover_entry_context(entries, [str(paths["unused.so"])], context, [], str(paths["ldd"].parent), out)


def test_real_producer_accepts_typed_zero_needed_without_faking_resolution(tmp_path, monkeypatch):
    m, p, c, e, calls, _ = fixture(tmp_path, monkeypatch)
    bill = produce(m, p, c, e, tmp_path / "bill")
    row = bill["entries"][1]
    assert row["entry_kind"] == "python_extension_entry" and row["trace_kind"] == "zero_direct_needed_python_extension"
    assert row["selected"] == [] and row["dynamic"]["needed"] == []
    assert row["symbols_resolved"] is False and row["runtime_import_verified"] is False
    assert [r["name"] for r in row["elf_metadata"]["symbols"] if r["ndx"] == "UND" and r["name"]] == [
        "PyDict_New",
        "__gmon_start__",
    ]
    assert bill["candidates"][0]["classification"] == "candidate_only"
    assert not any(argv[-1] == str(p["unused.so"]) for argv, _ in calls)
    assert m.audit_entry_context_bill(bill, baseline_files=bill["files"], python_context=c)["entry_trace_consistent"]


@pytest.mark.parametrize(
    "fault", ["empty", "extra", "nonzero", "nonpython", "initializer", "origin", "abi", "metadata", "stderr"]
)
def test_real_bill_refuses_inconsistent_zero_context_and_retains_call(tmp_path, monkeypatch, fault):
    m, p, c, e, _, run = fixture(tmp_path, monkeypatch)
    target = e["current-python"][0]
    if fault == "nonpython":
        c["modules"] = []
        monkeypatch.setattr(m, "collect_python_context", lambda: copy.deepcopy(c))
    if fault == "origin":
        c["modules"][0]["spec_origin"] = str(p["unused.so"])
    if fault == "abi":
        c["soabi"] = "cpython-311-x86_64-linux-gnu"

    def broken(argv, env):
        r = run(argv, env)
        if argv[-1] == target:
            b = bytes.fromhex(r["stdout_hex"])
            if argv[1] == "-d" and fault == "nonzero":
                b = b.replace(b"contains 1 entries", b"contains 2 entries").replace(
                    b" 0x0 (NULL)", b" 0x1 (NEEDED) Shared library: [libmissing.so]\n 0x0 (NULL)", 1
                )
            if argv[1] == "-W" and fault == "initializer":
                b = b.replace(b"PyInit__fixture", b"PyInit_other")
            if argv[1] == "-W" and fault == "metadata":
                b = b.replace(b"DYNAMIC", b"INTERP")
            if argv[0] == str(p["ldd"]):
                if fault == "empty":
                    b = b""
                if fault == "extra":
                    b += b"extra\n"
                if fault == "stderr":
                    r["stderr_hex"] = b"warning".hex()
            r["stdout_hex"] = b.hex()
        return r

    monkeypatch.setattr(m, "_run_tool", broken)
    with pytest.raises(ValueError):
        produce(m, p, c, e, tmp_path / "bill")
    saved = json.loads((tmp_path / "bill/entry-bill.json").read_bytes())
    assert saved["complete"] is False and saved["error"]
    if fault in ["empty", "extra", "nonzero", "nonpython", "stderr"]:
        assert saved["entries"][-1]["ldd_query"] == len(saved["queries"])


def test_auditor_recomputes_context_metadata_and_empty_self_membership(tmp_path, monkeypatch):
    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    bill = produce(m, p, c, e, tmp_path / "bill")
    for fault in ["context", "symbol", "query", "baseline"]:
        changed = copy.deepcopy(bill)
        base = changed["files"]
        if fault == "context":
            changed["python_context"]["modules"][0]["name"] = "other"
        if fault == "symbol":
            changed["entries"][1]["elf_metadata"]["symbols"][0]["name"] = "changed"
        if fault == "query":
            changed["entries"][1]["ldd_query"] = None
        if fault == "baseline":
            base = [r for r in base if r["requested"] != e["current-python"][0]]
        with pytest.raises(ValueError):
            m.audit_entry_context_bill(changed, baseline_files=base, python_context=c)


def test_producer_does_not_skip_nonelf_python_context(tmp_path, monkeypatch):
    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    target = Path(e["current-python"][0])
    target.write_bytes(b"not an ELF")
    c["modules"][0]["origin"] = m.file_record(str(target))
    monkeypatch.setattr(m, "collect_python_context", lambda: copy.deepcopy(c))
    with pytest.raises(ValueError, match="ELF"):
        produce(m, p, c, e, tmp_path / "bill")


def test_zero_needed_requires_complete_dynamic_section_not_only_heading(tmp_path, monkeypatch):
    m, p, c, e, _, run = fixture(tmp_path, monkeypatch)

    def truncated(argv, env):
        r = run(argv, env)
        if argv[1] == "-d" and argv[-1] == e["current-python"][0]:
            r["stdout_hex"] = b"Dynamic section at offset 0x1 contains 1 entries:\n".hex()
        return r

    monkeypatch.setattr(m, "_run_tool", truncated)
    with pytest.raises(ValueError, match="dynamic"):
        produce(m, p, c, e, tmp_path / "bill")
    saved = json.loads((tmp_path / "bill/entry-bill.json").read_bytes())
    assert saved["entries"][-1]["dynamic_query"] == len(saved["queries"])


def test_collect_context_uses_existing_loader_origin_without_importing_target(tmp_path, monkeypatch):
    from importlib.machinery import ExtensionFileLoader
    from types import SimpleNamespace

    from tools.benchmark.native_entry_context_v3 import collect_python_context as collector

    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    target = e["current-python"][0]
    module = SimpleNamespace(
        __file__=target, __spec__=SimpleNamespace(origin=target, loader=ExtensionFileLoader("_fixture", target))
    )
    fake_sys = SimpleNamespace(
        modules={"_fixture": module},
        executable=str(p["python"]),
        implementation=SimpleNamespace(name="cpython"),
        version="fixture Python3.12.3",
        version_info=[3, 12, 3],
        getdlopenflags=lambda: 2,
    )
    monkeypatch.setattr(m, "sys", fake_sys)
    monkeypatch.setattr(m.sysconfig, "get_config_var", lambda key: {"SOABI": c["soabi"], "EXT_SUFFIX": c["ext_suffix"]}[key])
    observed = collector()
    assert observed["modules"] == c["modules"] and observed["pid"] == m.os.getpid()
    assert not hasattr(module, "executed")


def test_retained_elf_metadata_is_consumed_by_new_producer_without_native_command(tmp_path, monkeypatch):
    m, p, c, e, calls, run = fixture(tmp_path, monkeypatch)
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "results/zero-needed-python-entry-research-dev-1701/elf-file-facts.json").read_bytes())
    old = json.loads(
        (
            root / "results/target-bearing-runtime-freeze-v2-dev-1701/frozen-study-v2/sdk/entry-dependencies/query-0057.json"
        ).read_bytes()
    )
    c["modules"][0]["name"] = "_json"
    monkeypatch.setattr(m, "collect_python_context", lambda: copy.deepcopy(c))

    def protocol(argv, env):
        row = run(argv, env)
        if argv[-1] == e["current-python"][0]:
            if argv[1] == "-W":
                row["stdout_hex"] = data["stdout_hex"]
            if argv[1] == "-d":
                row["stdout_hex"] = old["stdout_hex"]
        return row

    monkeypatch.setattr(m, "_run_tool", protocol)
    bill = produce(m, p, c, e, tmp_path / "bill")
    assert len(bill["entries"][1]["elf_metadata"]["symbols"]) == 70
    assert bill["entries"][1]["elf_metadata"]["initializer"] == "PyInit__json"


def test_producer_requires_observed_current_sdk_context_not_only_caller(tmp_path, monkeypatch):
    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "collect_python_context", lambda: dict(c, modules=[]))
    with pytest.raises(ValueError, match="context"):
        produce(m, p, c, e, tmp_path / "bill")


def test_bill_auditor_requires_agent_paths_to_be_actual_entries(tmp_path, monkeypatch):
    m, p, c, e, _, _ = fixture(tmp_path, monkeypatch)
    bill = produce(m, p, c, e, tmp_path / "bill")
    bill["agent_paths"] = [str(p["unused.so"])]
    with pytest.raises(ValueError, match="Agent"):
        m.audit_entry_context_bill(bill, baseline_files=bill["files"], python_context=c)


def test_producer_rejects_incomplete_program_header_rows(tmp_path, monkeypatch):
    m, p, c, e, _, run = fixture(tmp_path, monkeypatch)

    def truncated(argv, env):
        row = run(argv, env)
        if argv[1] == "-W":
            data = bytes.fromhex(row["stdout_hex"])
            start = data.index(b"  LOAD")
            end = data.index(b" Section to Segment")
            row["stdout_hex"] = (data[:start] + b"  DYNAMIC \n" + data[end:]).hex()
        return row

    monkeypatch.setattr(m, "_run_tool", truncated)
    with pytest.raises(ValueError, match="program|header"):
        produce(m, p, c, e, tmp_path / "bill")


@pytest.mark.parametrize("fault", ["timeout", "cap", "partial", "mutation", "postcontext"])
def test_new_producer_retains_protocol_failures(tmp_path, monkeypatch, fault):
    m, p, c, e, _, run = fixture(tmp_path, monkeypatch)
    target = e["current-python"][0]

    def protocol(argv, env):
        row = run(argv, env)
        if argv[0] == str(p["ldd"]) and argv[-1] == target:
            if fault == "timeout":
                row.update(error="fixture TimeoutExpired", exit=-15, cleanup=dict(exit=-15, descendants="unknown"))
            if fault == "cap":
                row["output_limit_exceeded"] = True
            if fault == "partial":
                row["reader_complete"] = False
            if fault == "mutation":
                Path(target).write_bytes(b"changed fixture input")
            if fault == "postcontext":
                monkeypatch.setattr(m, "collect_python_context", lambda: dict(c, modules=[]))
        return row

    monkeypatch.setattr(m, "_run_tool", protocol)
    with pytest.raises(ValueError):
        produce(m, p, c, e, tmp_path / "bill")
    saved = json.loads((tmp_path / "bill/entry-bill.json").read_bytes())
    assert saved["complete"] is False and saved["error"] and saved["queries"]
    assert saved["entries"][-1]["ldd_query"] == len(saved["queries"])
    if fault == "postcontext":
        assert saved["observed_context_after"]["modules"] == []


def test_query_writer_preserves_primary_and_partial_aggregate(tmp_path, monkeypatch):
    m, p, c, e, _, run = fixture(tmp_path, monkeypatch)
    writer = m.write_manifest

    def protocol(argv, env):
        row = run(argv, env)
        row["reader_complete"] = False
        return row

    def failing(path, data):
        if Path(path).name.startswith("query-"):
            raise OSError("fixture journal writer")
        return writer(path, data)

    monkeypatch.setattr(m, "_run_tool", protocol)
    monkeypatch.setattr(m, "write_manifest", failing)
    with pytest.raises(ValueError, match="partial") as caught:
        produce(m, p, c, e, tmp_path / "bill")
    saved = json.loads((tmp_path / "bill/entry-bill.json").read_bytes())
    assert "fixture journal writer" in saved["queries"][0]["journal_error"]
    assert "partial" in saved["error"] and caught.value.__notes__


@pytest.mark.parametrize("extra", [b"  Type: EXEC (Executable file)\n", b"  Class: ELF32\n", b"  Machine: AArch64\n"])
def test_conflicting_elf_header_labels_refuse(tmp_path, monkeypatch, extra):
    m, p, c, e, _, run = fixture(tmp_path, monkeypatch)

    def protocol(argv, env):
        row = run(argv, env)
        if argv[1] == "-W":
            row["stdout_hex"] = bytes.fromhex(row["stdout_hex"]).replace(b"Program Headers:", extra + b"Program Headers:").hex()
        return row

    monkeypatch.setattr(m, "_run_tool", protocol)
    with pytest.raises(ValueError, match="header"):
        produce(m, p, c, e, tmp_path / "bill")
