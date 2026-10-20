"""Independent v4 entry producer. Metadata is never import/source qualification.

Used only inside a future admitted SDK preparation. No CLI or SDK import here;
consumed v1/v2/v3 producers are neither imported nor executed. The test-body
process boundary is separate from the pending SDK admission bootstrap.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path

from tools.benchmark import native_loader_paths_v4 as paths
from tools.benchmark.declared_runtime_snapshot import file_record

SCHEMA = "native-entry-context-bill-v4"
LIMITS = dict(stream_bytes=2097152, timeout_seconds=10, terminate_seconds=5, kill_seconds=5)
QUALIFICATION = {
    k: False for k in ("source", "clock", "measured_calibration", "accuracy", "teacher", "fusion", "training", "flight")
}
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
TOOL_ORDER = ("ldd", "readelf", "python", "loader")
OGRE_DIR = "/usr/lib/x86_64-linux-gnu/OGRE-2.3"
OGRE_NAMES = {"libOgreNextMain.so.2.3.1", "libOgreNextHlmsPbs.so.2.3.1", "libOgreNextPlanarReflections.so.2.3.1"}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _bytes(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False, ensure_ascii=False).encode("utf-8")


def context_digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _input_evidence(value):
    try:
        _bytes(value)
        return copy.deepcopy(value)
    except Exception as exc:
        try:
            description = repr(value)[:4096]
        except Exception:
            description = "<representation unavailable>"
        return dict(
            unserializable_input=True,
            python_type=type(value).__name__,
            error_type=type(exc).__name__,
            representation_prefix=description,
            scope="bounded diagnostic only;not complete serialized input bytes",
        )


def _invalid_inventory():
    raise ValueError("final candidate inventory unavailable: inputs invalid")


def _same(a, b):
    return _bytes(a) == _bytes(b)


def _strict(path):
    paths._declared(path)
    return path


def query_cwd():
    return _strict(os.getcwd())


def tool_paths():
    return dict(ldd="/usr/bin/ldd", readelf="/usr/bin/readelf", python=sys.executable, loader="/lib64/ld-linux-x86-64.so.2")


def _validate_pin(record):
    _require(
        type(record) is dict
        and set(record) == {"requested", "resolved", "links", "identity", "path_identity", "bytes", "sha256"},
        "complete declared file record required",
    )
    paths._pin(record)
    _require(record["resolved"] == _strict(record["resolved"]), "canonical file path required")
    paths._valid_identity(record["path_identity"])
    _require(_same(record["identity"], record["path_identity"]), "path/descriptor identity mismatch")
    _require(type(record["links"]) is list and len(record["links"]) <= 40, "bounded declared link inventory required")
    for link in record["links"]:
        _require(type(link) is dict and set(link) == {"path", "target", "identity"}, "complete link record required")
        _strict(link["path"])
        paths._spelling(link["target"], absolute=False)
        identity = link["identity"]
        _require(
            type(identity) is dict
            and set(identity) == set(record["identity"])
            and all(type(v) is int for v in identity.values())
            and stat.S_ISLNK(identity["mode"]),
            "declared link identity required",
        )


def _same_object(a, b):
    return all(_same(a[k], b[k]) for k in ("resolved", "identity", "bytes", "sha256"))


def validate_python_context(value):
    keys = {
        "schema",
        "pid",
        "interpreter",
        "implementation",
        "version",
        "version_info",
        "soabi",
        "ext_suffix",
        "dlopen_flags",
        "modules",
    }
    _require(
        type(value) is dict and set(value) == keys and value["schema"] == "python-extension-context-v1",
        "exact current Python context required",
    )
    version = value["version_info"]
    _validate_pin(value["interpreter"])
    _require(
        type(version) is list and len(version) == 3 and all(type(n) is int and n >= 0 for n in version),
        "Python version fields required",
    )
    _require(
        type(value["pid"]) is int
        and value["pid"] > 0
        and value["implementation"] == "cpython"
        and type(value["version"]) is str
        and value["version"]
        and type(value["dlopen_flags"]) is int
        and value["dlopen_flags"] >= 0,
        "Python interpreter/flags context invalid",
    )
    _require(
        type(value["soabi"]) is str
        and value["soabi"].startswith(f"cpython-{version[0]}{version[1]}-")
        and value["ext_suffix"] == "." + value["soabi"] + ".so",
        "Python ABI differs",
    )
    _require(type(value["modules"]) is list and len(value["modules"]) <= 4096, "bounded current module inventory required")
    names = set()
    for module in value["modules"]:
        _require(
            type(module) is dict and set(module) == {"name", "origin", "module_file", "spec_origin", "loader"},
            "exact module origin required",
        )
        name = module["name"]
        _validate_pin(module["origin"])
        _require(
            type(name) is str and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", name, re.ASCII) and name not in names,
            "unique ASCII initializer module required",
        )
        names.add(name)
        _require(
            module["loader"] == "_frozen_importlib_external.ExtensionFileLoader"
            and module["module_file"] == module["spec_origin"] == module["origin"]["requested"],
            "actual loader/spec/file origin mismatch",
        )


def collect_python_context():
    """Read already present modules, never import a selected target for a witness."""
    modules = []
    for name, module in sorted(tuple(sys.modules.items())):
        spec = getattr(module, "__spec__", None)
        loader = getattr(spec, "loader", None)
        cls = type(loader)
        if cls.__module__ + "." + cls.__name__ != "_frozen_importlib_external.ExtensionFileLoader":
            continue
        origin = getattr(spec, "origin", None)
        module_file = getattr(module, "__file__", None)
        _require(origin == module_file, "current SDK spec/file spelling differs")
        modules.append(
            dict(
                name=name,
                origin=file_record(_strict(origin)),
                module_file=module_file,
                spec_origin=origin,
                loader=cls.__module__ + "." + cls.__name__,
            )
        )
    value = dict(
        schema="python-extension-context-v1",
        pid=os.getpid(),
        interpreter=file_record(_strict(sys.executable)),
        implementation=sys.implementation.name,
        version=sys.version,
        version_info=list(sys.version_info[:3]),
        soabi=sysconfig.get_config_var("SOABI"),
        ext_suffix=sysconfig.get_config_var("EXT_SUFFIX"),
        dlopen_flags=sys.getdlopenflags(),
        modules=modules,
    )
    validate_python_context(value)
    return value


def _module(context, file):
    matches = [m for m in context["modules"] if m["origin"]["resolved"] == file["resolved"]]
    _require(len(matches) <= 1, "ambiguous current module origin")
    if not matches:
        return None
    _require(_same(matches[0]["origin"], file), "entry spelling/pin differs from current module origin")
    return matches[0]


def _fd_identity(info):
    return dict(
        device=info.st_dev,
        inode=info.st_ino,
        mode=info.st_mode,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def _file_witness(path):
    """Prefix and full digest from one owned read, joined to strict path pins.

    Controlled static observation, not an adversarial filesystem snapshot.
    An independently supplied baseline must preserve this observer's provenance.
    """
    initial = file_record(_strict(path))
    _validate_pin(initial)
    stream = open(path, "rb")
    primary = None
    try:
        before = _fd_identity(os.fstat(stream.fileno()))
        _require(stat.S_ISREG(before["mode"]) and _same(before, initial["identity"]), "witness opened identity differs")
        digest = hashlib.sha256()
        count = 0
        prefix = b""
        while block := stream.read(65536):
            count += len(block)
            _require(count <= initial["bytes"], "witness exceeded pinned size")
            prefix = (prefix + block[:4])[:4]
            digest.update(block)
        after = _fd_identity(os.fstat(stream.fileno()))
        final = file_record(path)
        _require(
            _same(before, after)
            and _same(initial, final)
            and count == initial["bytes"]
            and digest.hexdigest() == initial["sha256"],
            "witness read/path mutation",
        )
        return dict(
            initial,
            byte_witness=dict(
                schema="native-file-byte-witness-v4",
                prefix_hex=prefix.hex(),
                bytes=count,
                sha256=digest.hexdigest(),
                fd_before=before,
                fd_after=after,
                file_before=initial,
                file_after=final,
            ),
        )
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            stream.close()
        except BaseException as exc:
            if primary is None:
                raise
            primary.add_note("witness close secondary: " + repr(exc))


def _validate_baseline_file(row):
    _require(type(row) is dict and "byte_witness" in row, "independent baseline byte witness required")
    pin = {k: v for k, v in row.items() if k != "byte_witness"}
    _validate_pin(pin)
    proof = row["byte_witness"]
    _require(
        type(proof) is dict
        and set(proof) == {"schema", "prefix_hex", "bytes", "sha256", "fd_before", "fd_after", "file_before", "file_after"},
        "exact byte witness required",
    )
    _require(
        proof["schema"] == "native-file-byte-witness-v4"
        and type(proof["prefix_hex"]) is str
        and re.fullmatch(r"[0-9a-f]*", proof["prefix_hex"]) is not None
        and len(proof["prefix_hex"]) == 2 * min(4, pin["bytes"])
        and proof["bytes"] == pin["bytes"]
        and proof["sha256"] == pin["sha256"]
        and all(_same(proof[k], pin["identity"]) for k in ("fd_before", "fd_after"))
        and all(_same(proof[k], pin) for k in ("file_before", "file_after")),
        "byte witness/pinned baseline differs",
    )
    return proof["prefix_hex"] == "7f454c46"


def parse_dynamic(data):
    text = data.decode("utf-8", errors="strict")
    lines = [x for x in text.splitlines() if x.strip()]
    _require(
        lines and re.fullmatch(r"Dynamic section at offset 0x[0-9a-fA-F]+ contains ([0-9]+) entries:", lines[0]),
        "complete dynamic header required",
    )
    count = int(re.fullmatch(r".* contains ([0-9]+) entries:", lines[0])[1])
    _require(1 <= count <= 65536, "dynamic count bound")
    rows = []
    result = dict(needed=[], runpath=[], rpath=[], soname=[])
    for line in lines[1:]:
        if re.fullmatch(r"\s*Tag\s+Type\s+Name/Value\s*", line):
            continue
        match = re.fullmatch(r"\s*(0x[0-9a-fA-F]+)\s+\(([A-Z0-9_]+)\)\s*(.*)", line)
        _require(match is not None, "malformed dynamic row")
        tag = match[2]
        rows.append(dict(tag=tag, value=match[3]))
        if tag in ("NEEDED", "RUNPATH", "RPATH", "SONAME"):
            label = {
                "NEEDED": "Shared library",
                "RUNPATH": "Library runpath",
                "RPATH": "Library rpath",
                "SONAME": "Library soname",
            }[tag]
            found = re.fullmatch(re.escape(label) + r": \[([^\[\]\r\n]*)\]", match[3])
            _require(found is not None and (found[1] or tag in ("RUNPATH", "RPATH")), "malformed dynamic string")
            _require(not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in found[1]), "dynamic control character")
            result[{"NEEDED": "needed", "RUNPATH": "runpath", "RPATH": "rpath", "SONAME": "soname"}[tag]].append(found[1])
    _require(len(rows) == count and rows[-1]["tag"] == "NULL", "incomplete dynamic records")
    result["records"] = rows
    return result


def parse_extension_metadata(data, module):
    _require(module is not None, "zero needed requires actual Python module")
    text = data.decode("utf-8", errors="strict")
    expected = {
        "Class": "ELF64",
        "Data": "2's complement, little endian",
        "Type": "DYN (Shared object file)",
        "Machine": "Advanced Micro Devices X86-64",
    }
    for label, value in expected.items():
        matches = re.findall(r"^\s*" + re.escape(label) + r":\s*(.*?)\s*$", text, re.MULTILINE)
        _require(matches == [value], "unique supported ELF header required")
    declared = re.findall(r"^\s*Number of program headers:\s*([0-9]+)\s*$", text, re.MULTILINE)
    _require(
        len(declared) == 1
        and 1 <= int(declared[0]) <= 65536
        and text.count("Program Headers:") == 1
        and text.count("Section to Segment mapping:") == 1,
        "complete ELF program header required",
    )
    program_text = text.split("Program Headers:", 1)[1].split("Section to Segment mapping:", 1)[0]
    programs = []
    for line in program_text.splitlines():
        if not line.strip() or line.strip().startswith("Type "):
            continue
        p = line.split()
        _require(len(p) in (8, 9) and re.fullmatch("[A-Z_0-9]+", p[0]), "malformed program row")
        _require(all(re.fullmatch("(0x)?[0-9a-fA-F]+", x) for x in [*p[1:6], p[-1]]), "program numeric field invalid")
        flags = "".join(p[6:-1])
        _require(flags and all(c in "RWE" for c in flags), "program flags invalid")
        programs.append(
            dict(type=p[0], offset=p[1], virtual=p[2], physical=p[3], file_size=p[4], memory_size=p[5], flags=flags, align=p[-1])
        )
    kinds = [p["type"] for p in programs]
    _require(
        len(programs) == int(declared[0]) and "LOAD" in kinds and kinds.count("DYNAMIC") == 1 and "INTERP" not in kinds,
        "complete LOAD/PT_DYNAMIC/noPT_INTERP required",
    )
    headers = list(re.finditer(r"Symbol table '\.dynsym' contains ([0-9]+) entries:\n", text))
    _require(len(headers) == 1, "one complete dynsym table required")
    head = headers[0]
    count = int(head[1])
    _require(1 <= count <= 65536, "symbol count bound")
    symbols = []
    for line in text[head.end() :].splitlines():
        if not line.strip() or line.strip().startswith("Num:"):
            continue
        p = line.split()
        _require(len(p) in (7, 8) and re.fullmatch("[0-9]+:", p[0]), "malformed full symbol table")
        _require(
            int(p[0][:-1]) == len(symbols) and re.fullmatch("[0-9a-fA-F]+", p[1]) and p[2].isdigit(), "symbol index/value invalid"
        )
        symbols.append(
            dict(
                index=len(symbols),
                value=p[1],
                size=int(p[2]),
                type=p[3],
                bind=p[4],
                visibility=p[5],
                ndx=p[6],
                name=p[7] if len(p) == 8 else "",
            )
        )
    _require(len(symbols) == count, "incomplete dynamic symbols")
    initializer = "PyInit_" + module["name"].rsplit(".", 1)[-1]
    chosen = [s for s in symbols if s["name"] == initializer]
    _require(
        len(chosen) == 1
        and chosen[0]["type"] == "FUNC"
        and chosen[0]["bind"] == "GLOBAL"
        and chosen[0]["visibility"] in ("DEFAULT", "PROTECTED")
        and chosen[0]["ndx"].isdigit()
        and int(chosen[0]["ndx"]) > 0,
        "expected defined Python initializer missing",
    )
    return dict(
        elf_class="ELF64",
        machine="x86-64",
        elf_type="ET_DYN",
        program_headers=programs,
        pt_dynamic=True,
        pt_interp=False,
        initializer=initializer,
        symbols=symbols,
        symbols_resolved=False,
    )


def parse_trace(data):
    _require(type(data) is bytes and data and len(data) <= LIMITS["stream_bytes"], "empty/oversize trace")
    data.decode("utf-8", errors="strict")
    tokens = []
    nonfiles = []
    offset = 0
    for line in data.splitlines(keepends=True):
        match = re.fullmatch(rb"[\t ]*(?:([^\s]+) => )?(/[^\r\n]+) \(0x[0-9a-fA-F]+\)\n", line)
        if match:
            token = match[2].decode("utf-8")
            paths._spelling(token)
            soname = match[1].decode("utf-8") if match[1] else None
            _require(
                soname is None or all(not c.isspace() and ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in soname),
                "malformed SONAME",
            )
            tokens.append(
                dict(
                    path=token,
                    soname=soname,
                    line_span=[offset, offset + len(line)],
                    token_span=[offset + match.start(2), offset + match.end(2)],
                )
            )
        else:
            _require(
                re.fullmatch(rb"[\t ]*linux-vdso[a-zA-Z0-9_.-]* \(0x[0-9a-fA-F]+\)\n", line),
                "malformed/unresolved/extra trace line",
            )
            nonfiles.append(dict(raw_utf8_hex=line.hex(), line_span=[offset, offset + len(line)]))
        offset += len(line)
    _require(tokens, "no selected dependency files")
    return tokens, nonfiles


def _environment(path, agent_paths, agent_lib):
    env = dict(ENV)
    if path in agent_paths:
        _require(
            posixpath.dirname(path) in (agent_lib, posixpath.dirname(agent_lib) + "/bin"), "Agent entry outside pinned deployment"
        )
        env["LD_LIBRARY_PATH"] = agent_lib
    return env


def _inputs(entries, candidates, agent_paths, agent_lib):
    _require(
        type(entries) is dict and entries and all(type(k) is str and k and type(v) is list and v for k, v in entries.items()),
        "nonempty entry roles required",
    )
    flat = [(role, _strict(p)) for role, values in entries.items() for p in values]
    _require(
        1 <= len(flat) <= 256 and all(len(set(v)) == len(v) for v in entries.values()), "bounded/unique role entries required"
    )
    _require(
        type(candidates) is list and len(candidates) <= 4096 and len(set(candidates)) == len(candidates),
        "bounded unique candidates required",
    )
    for p in candidates:
        _strict(p)
    _require(
        type(agent_paths) is list and len(set(agent_paths)) == len(agent_paths) and set(agent_paths) <= {p for _, p in flat},
        "Agent paths must be actual entries",
    )
    _strict(agent_lib)
    for _, p in flat:
        _environment(p, agent_paths, agent_lib)
    return flat


def _coverage(rows):
    renderers = [
        r
        for r in rows
        if posixpath.basename(r["file"]["requested"]) == "libgz-rendering8-ogre2.so.8.2.3" and r["alias_of"] is None
    ]
    _require(len(renderers) == 1, "one current renderer entry required")
    r = renderers[0]
    _require(
        r["elf"]
        and r["dynamic"] is not None
        and OGRE_NAMES <= set(r["dynamic"]["needed"])
        and OGRE_DIR in r["dynamic"]["runpath"]
        and OGRE_NAMES <= {posixpath.basename(p) for p in r["selected"]},
        "current renderer Main/Pbs/Planar/directNEEDED/RUNPATH coverage missing",
    )


def _write_json(path, value):
    data = _bytes(value)
    with Path(path).open("xb") as stream:
        _require(stream.write(data) == len(data), "short evidence write")
        stream.flush()
    _require(Path(path).read_bytes() == data, "evidence writer byte mismatch")
    return dict(query_path=str(Path(path).absolute()), query_sha256=hashlib.sha256(data).hexdigest())


def _fallback(path, value):
    # Independent exclusive fallback; failure remains a failure, never acceptance.
    data = _bytes(value)
    with Path(path).open("xb") as stream:
        if stream.write(data) != len(data):
            raise OSError("short fallback write")


def _publish_completion(prepared, final):
    # Exclusive atomic namespace publication is the commit point. Keep staging
    # evidence; no fallible cleanup follows successful publication.
    os.link(prepared, final, follow_symlinks=False)


def audit_entry_context_bill_v4(bill, *, baseline_files, python_context, artifact_reader=None):
    _audit_content_v4(bill, baseline_files=baseline_files, python_context=python_context, artifact_reader=artifact_reader)
    aggregate_text = bill["aggregate_path"]
    final_text = bill["completion_path"]
    aggregate = Path(aggregate_text)
    final = Path(final_text)
    if artifact_reader is None:
        valid = (
            aggregate.is_absolute()
            and aggregate.name == "entry-bill.json"
            and final == aggregate.with_name("entry-bill-terminal.json")
        )
    else:
        valid = (
            type(aggregate_text) is str
            and type(final_text) is str
            and (aggregate_text.startswith("/") or os.path.isabs(aggregate_text))
            and ".." not in re.split(r"[/\\]", aggregate_text)
            and re.split(r"[/\\]", aggregate_text)[-1] == "entry-bill.json"
            and final_text == aggregate_text[: -len("entry-bill.json")] + "entry-bill-terminal.json"
        )
    _require(valid, "fixed sibling terminal/aggregate references required")
    expected = _bytes(bill)
    receipt = dict(
        schema="native-entry-context-terminal-v4",
        aggregate_path=aggregate_text,
        aggregate_bytes=len(expected),
        aggregate_sha256=hashlib.sha256(expected).hexdigest(),
    )
    try:
        if artifact_reader is None:
            with final.open("rb") as stream:
                actual_receipt = stream.read(16385)
        else:
            receipt_bytes = _bytes(receipt)
            actual_receipt = artifact_reader(
                dict(query_path=final_text, query_sha256=hashlib.sha256(receipt_bytes).hexdigest()), 16384
            )
        _require(actual_receipt == _bytes(receipt), "terminal receipt missing/malformed/different")
        if artifact_reader is None:
            with aggregate.open("rb") as stream:
                actual = stream.read(len(expected) + 1)
        else:
            actual = artifact_reader(
                dict(query_path=aggregate_text, query_sha256=hashlib.sha256(expected).hexdigest()), len(expected)
            )
        _require(actual == expected, "terminal aggregate bytes differ")
    except OSError as exc:
        raise ValueError("committed terminal evidence unavailable") from exc


def _run(argv, env, cwd):
    """Own only the returned Popen. Reader/escaped descendant limits stay explicit."""
    start = time.monotonic_ns()
    row = dict(
        argv=copy.deepcopy(argv),
        env=copy.deepcopy(env),
        cwd=cwd,
        pid=None,
        returncode=None,
        error=None,
        timed_out=False,
        output_limited=False,
        owned_child_waited=False,
        reader_complete=False,
        cleanup=None,
        stdout_hex="",
        stderr_hex="",
        started_monotonic_ns=start,
        started_utc_ns=time.time_ns(),
        limits=dict(LIMITS),
        secondary_errors=[],
    )
    process = None
    buffers = [bytearray(), bytearray()]
    threads = []
    overflow = threading.Event()
    reader_errors = []

    def reader(pipe, bucket):
        try:
            while block := os.read(pipe.fileno(), 65536):
                available = LIMITS["stream_bytes"] - len(bucket)
                bucket.extend(block[:available])
                if len(block) > available:
                    overflow.set()
                    break
        except Exception as exc:
            reader_errors.append(repr(exc))

    def secondary(label, exc):
        row["secondary_errors"].append(label + ": " + repr(exc))

    try:
        _require(os.name == "posix", "native entry queries require admitted POSIX SDK context")
        process = subprocess.Popen(
            argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        row["pid"] = process.pid
        for pipe, bucket in zip((process.stdout, process.stderr), buffers, strict=True):
            t = threading.Thread(target=reader, args=(pipe, bucket), daemon=True)
            threads.append(t)
            t.start()
        while process.poll() is None:
            if overflow.is_set():
                raise ValueError("query hard stream cap exceeded")
            if time.monotonic_ns() - start >= 10_000_000_000:
                row["timed_out"] = True
                raise TimeoutError("query10s timeout")
            overflow.wait(0.01)
    except BaseException as exc:
        row["error"] = repr(exc)
    finally:
        if process is not None:
            cleanup = dict(exit=None, descendants="unknown")
            row["cleanup"] = cleanup
            try:
                running = process.poll() is None
            except Exception as exc:
                running = True
                secondary("poll", exc)
            if running:
                try:
                    process.terminate()
                    cleanup["terminate_sent"] = True
                except Exception as exc:
                    secondary("terminate", exc)
            try:
                cleanup["exit"] = process.wait(timeout=5)
                row["owned_child_waited"] = True
            except Exception as exc:
                secondary("wait", exc)
                try:
                    process.kill()
                    cleanup["kill_sent"] = True
                except Exception as exc:
                    secondary("kill", exc)
                try:
                    cleanup["exit"] = process.wait(timeout=5)
                    row["owned_child_waited"] = True
                except Exception as exc:
                    secondary("kill-wait", exc)
            row["returncode"] = cleanup["exit"]
            deadline = start + (20_000_000_000 if row["timed_out"] else 10_000_000_000)
            join_failed = False
            for t in threads:
                try:
                    t.join(timeout=max(0, (deadline - time.monotonic_ns()) / 1e9))
                except Exception as exc:
                    join_failed = True
                    secondary("reader-join", exc)
            active = False
            for t in threads:
                try:
                    active = active or t.is_alive()
                except Exception as exc:
                    active = True
                    secondary("reader-state", exc)
            row["reader_complete"] = len(threads) == 2 and not join_failed and not active
            if not active:
                for pipe in (process.stdout, process.stderr):
                    try:
                        pipe.close()
                    except Exception as exc:
                        secondary("pipe-close", exc)
            else:
                row["error"] = row["error"] or "stream readers incomplete; residual descendants unknown"
        row["output_limited"] = overflow.is_set()
        if overflow.is_set() or reader_errors or row["secondary_errors"]:
            row["error"] = row["error"] or repr(reader_errors or row["secondary_errors"] or ["stream cap"])
        row.update(
            stdout_hex=buffers[0].hex(),
            stderr_hex=buffers[1].hex(),
            ended_monotonic_ns=time.monotonic_ns(),
            ended_utc_ns=time.time_ns(),
        )
    return row


def _successful(q):
    paths._outcome(q)
    _require(
        type(q["pid"]) is int
        and q["pid"] > 0
        and q["reader_complete"] is True
        and q["cleanup"]["exit"] == q["returncode"]
        and q["cleanup"]["descendants"] == "unknown",
        "owned query terminal/stream facts incomplete",
    )
    _require(
        not bytes.fromhex(q["stderr_hex"]) and len(bytes.fromhex(q["stdout_hex"])) <= LIMITS["stream_bytes"],
        "query stderr or stream overflow",
    )
    _require(type(q["started_utc_ns"]) is int and type(q["ended_utc_ns"]) is int, "query UTC fields missing")
    paths._environment(q["env"])
    _strict(q["cwd"])


def discover_entry_context_v4(entries, candidates, python_context, agent_paths, agent_lib, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("v4 entry output already exists; no replay")
    output.mkdir()
    bill = dict(
        schema=SCHEMA,
        aggregate_path=str((output / "entry-bill.json").absolute()),
        completion_path=str((output / "entry-bill-terminal.json").absolute()),
        input_entries=_input_evidence(entries),
        input_entry_order=[],
        input_candidates=_input_evidence(candidates),
        python_context=_input_evidence(python_context),
        python_context_sha256=None,
        observed_context_before=None,
        observed_context_after=None,
        agent_paths=_input_evidence(agent_paths),
        agent_lib=_input_evidence(agent_lib),
        cwd=None,
        entries=[],
        candidates=[],
        files=[],
        files_after=[],
        declared_before=[],
        declared_after=[],
        tools_before={},
        tools_after={},
        versions={},
        queries=[],
        selected_paths=[],
        selected_paths_after=[],
        path_attempts=[],
        first_observed_query={},
        final_observations={},
        complete=False,
        error=None,
        secondary_errors=[],
        runtime_closure_qualified=False,
        qualification=dict(QUALIFICATION),
    )
    declared = {}
    canonical = {}
    toolset = {}
    primary = None
    inputs_validated = False

    def remember(path, index=0):
        record = file_record(_strict(path))
        _validate_pin(record)
        if path in declared:
            _require(_same(record, declared[path]), "declared input/tool mutation")
        else:
            declared[path] = record
            bill["declared_before"] = list(declared.values())
        p = record["resolved"]
        current = _file_witness(p)
        _validate_baseline_file(current)
        _require(
            current["requested"] == current["resolved"] == p and _same_object(record, current),
            "canonical/requested identity disagreement",
        )
        if p in canonical:
            _require(_same(canonical[p], current), "canonical file mutation")
        else:
            canonical[p] = current
            bill["files"] = list(canonical.values())
            bill["first_observed_query"][p] = index
        return record

    def secondary(label, exc):
        bill["secondary_errors"].append(label + ": " + repr(exc))

    def invoke(kind, argv, env, entry=None, role=None, tool_name=None):
        index = len(bill["queries"]) + 1
        q = dict(
            schema="native-tool-version-query-v4" if kind == "version" else "native-entry-query-v4",
            kind=kind,
            index=index,
            entry=entry,
            role=role,
            tool_name=tool_name,
            argv=copy.deepcopy(argv),
            cwd=bill["cwd"],
            env=copy.deepcopy(env),
            tool_before=None,
            tool_after=None,
            input_before=None,
            input_after=None,
            returncode=None,
            error=None,
            observer_error=None,
            stdout_hex="",
            stderr_hex="",
            pid=None,
            reader_complete=False,
            owned_child_waited=False,
            timed_out=False,
            output_limited=False,
            cleanup=None,
            limits=dict(LIMITS),
            started_monotonic_ns=None,
            ended_monotonic_ns=None,
            started_utc_ns=None,
            ended_utc_ns=None,
        )
        if kind != "version":
            q["tool_version"] = copy.deepcopy(bill["queries"][bill["versions"][tool_name] - 1]["artifact"])
        wrapper = dict(record=q, artifact=None, journal_error=None)
        bill["queries"].append(wrapper)
        failure = None
        try:
            q["tool_before"] = remember(argv[0], index)
            if entry is not None:
                q["input_before"] = remember(entry["requested"], index)
            observed = _run(argv, env, bill["cwd"])
            _require(
                observed["argv"] == argv and observed["env"] == env and observed["cwd"] == bill["cwd"],
                "backend actual invocation mismatch",
            )
            allowed = {
                "pid",
                "returncode",
                "error",
                "timed_out",
                "output_limited",
                "owned_child_waited",
                "reader_complete",
                "cleanup",
                "stdout_hex",
                "stderr_hex",
                "started_monotonic_ns",
                "ended_monotonic_ns",
                "started_utc_ns",
                "ended_utc_ns",
                "limits",
                "secondary_errors",
            }
            q.update({k: v for k, v in observed.items() if k in allowed})
            # Command outcome precedes any subsequent observer/writer failure.
            _successful(q)
        except BaseException as exc:
            failure = exc
            q["observer_error"] = repr(exc)
        finally:
            for key, path in [("tool_after", argv[0])] + ([] if entry is None else [("input_after", entry["requested"])]):
                try:
                    q[key] = file_record(path)
                except Exception as exc:
                    if failure is None:
                        failure = exc
                        q["observer_error"] = repr(exc)
                    else:
                        secondary("query-postpin:" + key, exc)
            try:
                if failure is None:
                    _require(
                        _same(q["tool_before"], q["tool_after"]) and _same(q["input_before"], q["input_after"]),
                        "query input/tool mutation",
                    )
                    _successful(q)
                    if kind == "version":
                        _require(bytes.fromhex(q["stdout_hex"]).strip(), "tool version output empty")
            except BaseException as exc:
                failure = exc
                q["observer_error"] = repr(exc)
            try:
                wrapper["artifact"] = _write_json(output / f"query-{index:04d}.json", q)
            except Exception as exc:
                wrapper["journal_error"] = repr(exc)
                if failure is None:
                    failure = exc
                else:
                    secondary("query-writer", exc)
                try:
                    _fallback(output / f"query-{index:04d}-fallback.json", wrapper)
                except Exception as other:
                    secondary("query-fallback-unavailable", other)
        if failure is not None:
            raise failure
        return q

    try:
        flat = _inputs(entries, candidates, agent_paths, agent_lib)
        inputs_validated = True
        bill["input_entry_order"] = [list(pair) for pair in flat]
        validate_python_context(python_context)
        bill["python_context_sha256"] = context_digest(python_context)
        bill["cwd"] = query_cwd()
        _strict(bill["cwd"])
        bill["observed_context_before"] = collect_python_context()
        validate_python_context(bill["observed_context_before"])
        _require(_same(bill["observed_context_before"], python_context), "current SDK Python context differs")
        for _, p in flat:
            remember(p)
        for p in candidates:
            remember(p)
        for record in [python_context["interpreter"], *[m["origin"] for m in python_context["modules"]]]:
            _require(_same(remember(record["requested"]), record), "Python context current-file pin differs")
        _require(
            {m["origin"]["requested"] for m in python_context["modules"]} <= {p for _, p in flat},
            "current Python modules missing actual entries",
        )
        toolset = tool_paths()
        _require(set(toolset) == {"ldd", "readelf", "python", "loader"}, "exact fixed tools required")
        bill["tools_before"] = {k: remember(p) for k, p in toolset.items()}
        _require(_same(bill["tools_before"]["python"], python_context["interpreter"]), "Python interpreter/tool mismatch")
        known = {}
        by_object = {}
        for source_role, p in flat:
            f = declared[p]
            module = _module(python_context, f)
            kind = "python_extension_entry" if module else "dependency_entry"
            invocation = dict(
                path=p,
                env=_environment(p, agent_paths, agent_lib),
                cwd=bill["cwd"],
                entry_kind=kind,
                python_context_sha256=bill["python_context_sha256"],
            )
            identity = (f["identity"]["device"], f["identity"]["inode"])
            canonical_key = f["resolved"]
            for key in [("inode", identity), ("canonical", canonical_key)]:
                if key in by_object:
                    _require(_same(invocation, by_object[key]), "conflicting entry alias/load-origin invocation")
                else:
                    by_object[key] = invocation
            alias = known.get(p)
            known.setdefault(p, len(bill["entries"]))
            elf = _validate_baseline_file(canonical[f["resolved"]])
            _require(not module or elf, "current Python module requires ELF")
            bill["entries"].append(
                dict(
                    source_role=source_role,
                    file=f,
                    entry_kind=kind,
                    elf=elf,
                    invocation=invocation,
                    alias_of=alias,
                    dynamic_query=None,
                    metadata_query=None,
                    ldd_query=None,
                    dynamic=None,
                    elf_metadata=None,
                    trace_kind=None,
                    selected=[],
                    path_records=[],
                    nonfiles=[],
                    runtime_import_verified=False,
                    symbols_resolved=False,
                )
            )
        for name in TOOL_ORDER:
            path = toolset[name]
            bill["versions"][name] = len(bill["queries"]) + 1
            invoke("version", [path, "--version"], dict(ENV), tool_name=name)
        for row in bill["entries"]:
            if row["alias_of"] is not None:
                original = bill["entries"][row["alias_of"]]
                for key in ("dynamic", "elf_metadata", "trace_kind", "selected", "path_records", "nonfiles"):
                    row[key] = copy.deepcopy(original[key])
                continue
            if not row["elf"]:
                continue
            path = row["file"]["requested"]
            env = row["invocation"]["env"]
            role = row["entry_kind"]
            file = row["file"]
            row["dynamic_query"] = len(bill["queries"]) + 1
            q = invoke("dynamic", [toolset["readelf"], "-d", path], env, file, role, "readelf")
            row["dynamic"] = parse_dynamic(bytes.fromhex(q["stdout_hex"]))
            if role == "python_extension_entry" and not row["dynamic"]["needed"]:
                row["metadata_query"] = len(bill["queries"]) + 1
                q = invoke("elf-metadata", [toolset["readelf"], "-W", "-h", "-l", "--dyn-syms", path], env, file, role, "readelf")
                row["elf_metadata"] = parse_extension_metadata(bytes.fromhex(q["stdout_hex"]), _module(python_context, file))
            row["ldd_query"] = len(bill["queries"]) + 1
            q = invoke("ldd", [toolset["ldd"], path], env, file, role, "ldd")
            data = bytes.fromhex(q["stdout_hex"])
            if row["elf_metadata"] is not None:
                _require(data == b"\tstatically linked\n", "exact zero-needed Python phrase required")
                row["trace_kind"] = "zero_direct_needed_python_extension"
            else:
                tokens, nonfiles = parse_trace(data)
                row["trace_kind"] = "dynamic_dependencies"
                row["nonfiles"] = nonfiles
                for token in tokens:
                    ref = bill["queries"][row["ldd_query"] - 1]["artifact"]
                    origin = dict(
                        schema="native-loader-trace-origin-v4",
                        **ref,
                        query_index=row["ldd_query"],
                        entry=copy.deepcopy(file),
                        role=role,
                        line_span=token["line_span"],
                        token_span=token["token_span"],
                    )
                    attempt = dict(raw_path=token["path"], query_index=row["ldd_query"], origin=origin, record=None, error=None)
                    bill["path_attempts"].append(attempt)
                    try:
                        rec = paths.record_selected_path(token["path"], trace_origin=origin)
                        attempt["record"] = rec
                    except Exception as exc:
                        attempt["record"] = getattr(exc, "partial", None)
                        attempt["error"] = repr(exc)
                        raise
                    canonical_file = remember(rec["canonical_path"], row["ldd_query"])
                    paths.audit_selected_path(
                        rec,
                        trace_origin=origin,
                        baseline_files={canonical_file["resolved"]: canonical[canonical_file["resolved"]]},
                    )
                    row["selected"].append(token["path"])
                    row["path_records"].append(len(bill["selected_paths"]))
                    bill["selected_paths"].append(rec)
        _coverage(bill["entries"])
    except BaseException as exc:
        primary = exc
        bill["error"] = repr(exc)
    finally:
        # Each class is independently attempted even when another final observer fails.
        class PartialObservation(ValueError):
            def __init__(self, value, errors):
                self.value = value
                super().__init__(repr(errors))

        def each(values, observe, *, mapping=False):
            result = {} if mapping else []
            errors = []
            for key in values:
                try:
                    item = observe(key)
                    if mapping:
                        result[key] = item
                    else:
                        result.append(item)
                except Exception as exc:
                    errors.append(
                        dict(
                            key=key if isinstance(key, str) else str(key), error=repr(exc), partial=getattr(exc, "partial", None)
                        )
                    )
            if errors:
                raise PartialObservation(result, errors)
            return result

        operations = {
            "context": lambda: collect_python_context(),
            "declared": lambda: each(declared, file_record),
            "files": lambda: each(canonical, _file_witness),
            "tools": lambda: each(toolset, lambda k: file_record(toolset[k]), mapping=True),
            "candidates": lambda: each(
                candidates if inputs_validated else _invalid_inventory(),
                lambda p: dict(role="candidate_only", file=file_record(p), runtime_closure_qualified=False),
            ),
            "selected_paths": lambda: each(
                range(len(bill["selected_paths"])),
                lambda i: paths.record_selected_path(
                    bill["selected_paths"][i]["raw_path"], trace_origin=bill["selected_paths"][i]["trace"]["origin"]
                ),
            ),
        }
        destinations = {
            "context": "observed_context_after",
            "declared": "declared_after",
            "files": "files_after",
            "tools": "tools_after",
            "candidates": "candidates",
            "selected_paths": "selected_paths_after",
        }
        for label, operation in operations.items():
            status = dict(attempted=True, available=False, error=None)
            bill["final_observations"][label] = status
            try:
                bill[destinations[label]] = operation()
                status["available"] = True
            except Exception as exc:
                if isinstance(exc, PartialObservation):
                    bill[destinations[label]] = exc.value
                status["error"] = repr(exc)
                if primary is None:
                    primary = exc
                    bill["error"] = repr(exc)
                else:
                    secondary("final-" + label, exc)
        if primary is None:
            try:
                bill["complete"] = True
                _audit_content_v4(bill, baseline_files=bill["files"], python_context=python_context)
            except BaseException as exc:
                primary = exc
                bill.update(complete=False, error=repr(exc))
        try:
            aggregate = output / "entry-bill.json"
            _write_json(aggregate, bill)
            if primary is None:
                data = _bytes(bill)
                receipt = dict(
                    schema="native-entry-context-terminal-v4",
                    aggregate_path=bill["aggregate_path"],
                    aggregate_bytes=len(data),
                    aggregate_sha256=hashlib.sha256(data).hexdigest(),
                )
                staged = output / "entry-bill-terminal.prepared.json"
                _write_json(staged, receipt)
                _publish_completion(staged, output / "entry-bill-terminal.json")
        except Exception as exc:
            bill["complete"] = False
            if primary is None:
                primary = exc
                bill["error"] = repr(exc)
            else:
                secondary("aggregate-writer", exc)
            try:
                _fallback(output / "entry-bill-fallback.json", bill)
            except Exception as other:
                secondary("aggregate-fallback-unavailable", other)
    if primary is not None:
        primary.bill = bill
        for note in bill["secondary_errors"]:
            primary.add_note(note)
        raise primary
    return bill


def _audit_content_v4(bill, *, baseline_files, python_context, artifact_reader=None):
    expected_keys = {
        "schema",
        "aggregate_path",
        "completion_path",
        "input_entries",
        "input_entry_order",
        "input_candidates",
        "python_context",
        "python_context_sha256",
        "observed_context_before",
        "observed_context_after",
        "agent_paths",
        "agent_lib",
        "cwd",
        "entries",
        "candidates",
        "files",
        "files_after",
        "declared_before",
        "declared_after",
        "tools_before",
        "tools_after",
        "versions",
        "queries",
        "selected_paths",
        "selected_paths_after",
        "path_attempts",
        "first_observed_query",
        "final_observations",
        "complete",
        "error",
        "secondary_errors",
        "runtime_closure_qualified",
        "qualification",
    }
    _require(type(bill) is dict and set(bill) == expected_keys, "exact v4 bill schema membership required")
    _require(
        bill["schema"] == SCHEMA
        and bill["complete"] is True
        and bill["error"] is None
        and not bill["secondary_errors"]
        and bill["runtime_closure_qualified"] is False
        and _same(bill["qualification"], QUALIFICATION),
        "complete unqualified v4 bill required",
    )
    _inputs(bill["input_entries"], bill["input_candidates"], bill["agent_paths"], bill["agent_lib"])
    order = bill["input_entry_order"]
    grouped = {}
    _require(type(order) is list and 1 <= len(order) <= 256, "explicit bounded entry order required")
    for pair in order:
        _require(
            type(pair) is list and len(pair) == 2 and all(type(x) is str for x in pair), "typed explicit entry order required"
        )
        grouped.setdefault(pair[0], []).append(pair[1])
    _require(_same(grouped, bill["input_entries"]), "entry order/role inventory mismatch")
    flat = [tuple(pair) for pair in order]
    validate_python_context(python_context)
    _require(
        _same(bill["python_context"], python_context) and bill["python_context_sha256"] == context_digest(python_context),
        "context bytes/digest mismatch",
    )
    for k in ("observed_context_before", "observed_context_after"):
        validate_python_context(bill[k])
        _require(_same(bill[k], python_context), "current before/after SDK context mismatch")
    _require(
        set(bill["final_observations"]) == {"context", "declared", "files", "tools", "candidates", "selected_paths"}
        and all(s == dict(attempted=True, available=True, error=None) for s in bill["final_observations"].values()),
        "final observation unavailable",
    )
    declared = {r["requested"]: r for r in bill["declared_before"]}
    files = {r["requested"]: r for r in bill["files"]}
    _require(len(declared) == len(bill["declared_before"]) and len(files) == len(bill["files"]), "duplicate file membership")
    base = {r["requested"]: {k: v for k, v in r.items() if k != "role"} for r in baseline_files}
    _require(
        len(base) == len(baseline_files) and all(_same(v, base.get(k)) for k, v in files.items()),
        "canonical/self baseline missing/different",
    )
    _require(
        _same(bill["declared_before"], bill["declared_after"])
        and _same(bill["files"], bill["files_after"])
        and _same(bill["tools_before"], bill["tools_after"]),
        "global file/tool postcheck mismatch",
    )
    for row in declared.values():
        _validate_pin(row)
        _require(row["resolved"] in files and _same_object(row, files[row["resolved"]]), "declared/canonical file join mismatch")
    _require(set(files) == set(bill["first_observed_query"]), "first-observed membership mismatch")
    for row in files.values():
        _validate_baseline_file(row)
        _require(row["requested"] == row["resolved"], "canonical baseline spelling required")
    fixed = dict(
        ldd="/usr/bin/ldd",
        readelf="/usr/bin/readelf",
        loader="/lib64/ld-linux-x86-64.so.2",
        python=python_context["interpreter"]["requested"],
    )
    tools = bill["tools_before"]
    _require(set(tools) == {"ldd", "readelf", "python", "loader"} == set(fixed), "fixed tools required")
    _require(
        all(r["requested"] == fixed[k] and _same(r, declared.get(fixed[k])) for k, r in tools.items()),
        "tool identity/substitution mismatch",
    )
    _require(_same(tools["python"], python_context["interpreter"]), "interpreter/tool join mismatch")
    for r in [python_context["interpreter"], *[m["origin"] for m in python_context["modules"]]]:
        _require(_same(r, declared.get(r["requested"])), "Python self/module baseline missing")
    _require([(r["source_role"], r["file"]["requested"]) for r in bill["entries"]] == flat, "exact entry membership mismatch")
    _require({m["origin"]["requested"] for m in python_context["modules"]} <= {p for _, p in flat}, "module not a current entry")
    calls = []
    used_declared = (
        set(fixed.values())
        | {p for _, p in flat}
        | set(bill["input_candidates"])
        | {m["origin"]["requested"] for m in python_context["modules"]}
        | {python_context["interpreter"]["requested"]}
    )
    first_seen = {declared[p]["resolved"]: 0 for p in used_declared}

    def expected(kind, argv, env, entry=None, role=None, name=None):
        index = len(calls) + 1
        calls.append((kind, argv, env, entry, role, name))
        return index

    _require(set(bill["versions"]) == set(tools), "exact version inventory required")
    for name in TOOL_ORDER:
        tool = tools[name]
        _require(
            bill["versions"][name] == expected("version", [tool["requested"], "--version"], dict(ENV), name=name),
            "version query index mismatch",
        )
    seen = {}
    object_context = {}
    used_paths = []
    for index, row in enumerate(bill["entries"]):
        file = row["file"]
        path = file["requested"]
        _require(_same(file, declared[path]), "entry pin mismatch")
        module = _module(python_context, file)
        kind = "python_extension_entry" if module else "dependency_entry"
        invocation = dict(
            path=path,
            env=_environment(path, bill["agent_paths"], bill["agent_lib"]),
            cwd=bill["cwd"],
            entry_kind=kind,
            python_context_sha256=bill["python_context_sha256"],
        )
        _require(
            row["entry_kind"] == kind
            and _same(row["invocation"], invocation)
            and row["runtime_import_verified"] is False
            and row["symbols_resolved"] is False
            and type(row["elf"]) is bool,
            "entry context/flags mismatch",
        )
        _require(
            row["elf"] == _validate_baseline_file(files[file["resolved"]]),
            "entry ELF classification differs from independent byte witness",
        )
        _require(not module or row["elf"], "Python entry requires ELF")
        for key in [("inode", (file["identity"]["device"], file["identity"]["inode"])), ("canonical", file["resolved"])]:
            if key in object_context:
                _require(_same(object_context[key], invocation), "conflicting load-origin aliases")
            else:
                object_context[key] = invocation
        if path in seen:
            original = bill["entries"][seen[path]]
            _require(
                row["alias_of"] == seen[path] and all(row[k] is None for k in ("dynamic_query", "metadata_query", "ldd_query")),
                "identical-context alias queried twice",
            )
            _require(
                all(
                    _same(row[k], original[k])
                    for k in ("dynamic", "elf_metadata", "trace_kind", "selected", "path_records", "nonfiles")
                ),
                "alias trace inheritance differs",
            )
            continue
        seen[path] = index
        _require(row["alias_of"] is None, "undeclared alias")
        if not row["elf"]:
            _require(
                all(
                    row[k] is None
                    for k in ("dynamic_query", "metadata_query", "ldd_query", "dynamic", "elf_metadata", "trace_kind")
                )
                and not row["selected"]
                and not row["path_records"]
                and not row["nonfiles"],
                "nonELF claims a trace",
            )
            continue
        dynamic_index = expected("dynamic", [fixed["readelf"], "-d", path], invocation["env"], file, kind, "readelf")
        _require(row["dynamic_query"] == dynamic_index, "dynamic index mismatch")
        dynamic = parse_dynamic(bytes.fromhex(bill["queries"][dynamic_index - 1]["record"]["stdout_hex"]))
        _require(_same(dynamic, row["dynamic"]), "dynamic raw bytes mismatch")
        zero = kind == "python_extension_entry" and not dynamic["needed"]
        if zero:
            metadata_index = expected(
                "elf-metadata", [fixed["readelf"], "-W", "-h", "-l", "--dyn-syms", path], invocation["env"], file, kind, "readelf"
            )
            _require(row["metadata_query"] == metadata_index, "metadata index mismatch")
            metadata = parse_extension_metadata(
                bytes.fromhex(bill["queries"][metadata_index - 1]["record"]["stdout_hex"]), module
            )
            _require(_same(metadata, row["elf_metadata"]), "metadata raw symbols/program mismatch")
        else:
            _require(row["elf_metadata"] is None and row["metadata_query"] is None, "unexpected Python metadata")
        ldd_index = expected("ldd", [fixed["ldd"], path], invocation["env"], file, kind, "ldd")
        _require(row["ldd_query"] == ldd_index, "ldd index mismatch")
        data = bytes.fromhex(bill["queries"][ldd_index - 1]["record"]["stdout_hex"])
        if zero:
            _require(
                data == b"\tstatically linked\n"
                and row["trace_kind"] == "zero_direct_needed_python_extension"
                and not row["selected"]
                and not row["path_records"]
                and not row["nonfiles"],
                "zero-needed exact phrase/self semantics mismatch",
            )
        else:
            tokens, nonfiles = parse_trace(data)
            _require(
                row["trace_kind"] == "dynamic_dependencies"
                and row["selected"] == [t["path"] for t in tokens]
                and _same(row["nonfiles"], nonfiles)
                and len(row["path_records"]) == len(tokens),
                "selected raw membership mismatch",
            )
            for token, number in zip(tokens, row["path_records"], strict=True):
                _require(type(number) is int and number == len(used_paths), "exact selected path index membership required")
                used_paths.append(number)
                record = bill["selected_paths"][number]
                origin = dict(
                    schema="native-loader-trace-origin-v4",
                    **bill["queries"][ldd_index - 1]["artifact"],
                    query_index=ldd_index,
                    entry=file,
                    role=kind,
                    line_span=token["line_span"],
                    token_span=token["token_span"],
                )
                paths.audit_selected_path(record, trace_origin=origin, baseline_files=files, artifact_reader=artifact_reader)
                used_declared.add(record["canonical_path"])
                first_seen.setdefault(record["canonical_path"], ldd_index)
    _require(len(used_paths) == len(bill["selected_paths"]), "extra/missing selected aliases")
    _require(_same(first_seen, bill["first_observed_query"]), "first-observed query chronology mismatch")
    _require(len(bill["path_attempts"]) == len(bill["selected_paths"]), "path attempt inventory mismatch")
    for attempt, record in zip(bill["path_attempts"], bill["selected_paths"], strict=True):
        _require(
            attempt["error"] is None
            and attempt["raw_path"] == record["raw_path"]
            and attempt["query_index"] == record["trace"]["origin"]["query_index"]
            and _same(attempt["origin"], record["trace"]["origin"])
            and _same(attempt["record"], record),
            "path attempt/raw record mismatch",
        )
    _require(len(calls) == len(bill["queries"]), "extra/missing actual query")
    for number, (wrapper, call) in enumerate(zip(bill["queries"], calls, strict=True), 1):
        q = wrapper["record"]
        kind, argv, env, entry, role, name = call
        _require(wrapper["journal_error"] is None and wrapper["artifact"] is not None, "query journal failed")
        raw = paths._retained_query(wrapper["artifact"], artifact_reader)
        _require(_same(q, raw), "bill/query artifact byte join mismatch")
        _successful(q)
        _require(
            q["index"] == number
            and q["kind"] == kind
            and q["argv"] == argv
            and _same(q["env"], env)
            and q["cwd"] == bill["cwd"]
            and q["tool_name"] == name
            and q["role"] == role
            and _same(q["entry"], entry)
            and q["observer_error"] is None,
            "query invocation/context mismatch",
        )
        _require(
            _same(q["tool_before"], tools[name])
            and _same(q["tool_after"], tools[name])
            and _same(q["input_before"], entry)
            and _same(q["input_after"], entry),
            "query pre/post input/tool join mismatch",
        )
        _require(
            q["schema"] == ("native-tool-version-query-v4" if kind == "version" else "native-entry-query-v4"),
            "query schema mismatch",
        )
        if kind == "version":
            _require(bytes.fromhex(q["stdout_hex"]).strip(), "empty version query")
        else:
            _require(
                _same(q["tool_version"], bill["queries"][bill["versions"][name] - 1]["artifact"]),
                "retained tool version join mismatch",
            )
    _require(
        set(declared) == used_declared and set(files) == {r["resolved"] for r in declared.values()},
        "extra/missing canonical/declared file membership",
    )
    expected_candidates = [
        dict(role="candidate_only", file=declared[p], runtime_closure_qualified=False) for p in bill["input_candidates"]
    ]
    _require(_same(bill["candidates"], expected_candidates), "candidate membership/qualification mismatch")
    _require(len(bill["selected_paths_after"]) == len(bill["selected_paths"]), "selected final inventory missing")
    for before, after in zip(bill["selected_paths"], bill["selected_paths_after"], strict=True):
        origin = before["trace"]["origin"]
        paths.audit_selected_path(after, trace_origin=origin, baseline_files=files, artifact_reader=artifact_reader)
        _require(
            all(
                _same(before[k], after[k])
                for k in (
                    "raw_path",
                    "canonical_path",
                    "trace",
                    "walk_before",
                    "walk_after",
                    "fd_before",
                    "fd_after",
                    "canonical_identity",
                    "bytes",
                    "sha256",
                )
            ),
            "selected path mutation in final observation",
        )
    _coverage(bill["entries"])
