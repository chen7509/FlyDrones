"""Receipt production for the sole v2 adapter. Never invokes a compiler or ELF loader."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
from pathlib import Path

CAP = 64 * 1024**2


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def file_pin(path):
    path = Path(path)
    resolved = path.resolve(strict=True)
    with resolved.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > CAP:
            raise ValueError("regular bounded file required: " + str(path))
        digest = hashlib.sha256()
        size = 0
        while block := stream.read(1024**2):
            size += len(block)
            if size > CAP:
                raise ValueError("file grew beyond cap")
            digest.update(block)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
    if any(getattr(before, k) != getattr(after, k) for k in fields) or path.resolve(strict=True) != resolved:
        raise ValueError("file changed during read: " + str(path))
    return dict(path=str(path), resolved=str(resolved), bytes=size, sha256=digest.hexdigest())


def read_json(path, *, expected=None, sha=None):
    from tools.benchmark.capture_contract import _unique_pairs

    path = Path(path)
    before = file_pin(path)
    with path.open("rb") as stream:
        raw = stream.read(CAP + 1)
    if len(raw) > CAP or len(raw) != before["bytes"] or hashlib.sha256(raw).hexdigest() != before["sha256"]:
        raise ValueError("JSON bytes changed between pin and parse")
    if (expected is not None and before != expected) or (sha is not None and before["sha256"] != sha):
        raise ValueError("JSON expected bytes differ")
    value = json.loads(raw, object_pairs_hook=_unique_pairs)
    if type(value) is not dict or file_pin(path) != before:
        raise ValueError("JSON mapping changed during exact-byte read")
    return value


def verify_pins(pins):
    if type(pins) is not dict or not pins:
        raise ValueError("nonempty explicit current input pins required")
    for name, expected in pins.items():
        if not Path(name).is_absolute() or file_pin(name) != expected:
            raise ValueError("input drift or nonabsolute pin: " + str(name))
    return pins


def produce(request, build, steps, *, stage_errors=(), deadline=None):
    """Keep failure/partial outputs. Completeness is a build record, never ABI/runtime admission."""
    if request.get("build_profile") == "fixed-source-openvins-v1":
        from tools.benchmark.native_offset_fresh_receipt import produce_fresh

        return produce_fresh(request, build, steps, stage_errors=stage_errors, deadline=deadline)
    build = Path(build).resolve()
    result = dict(
        schema="native-offset-build-receipt-v1",
        complete=False,
        native_qualified=False,
        runtime_closure_qualified=False,
        steps=steps,
        errors=[],
        artifacts={},
        depfiles=[],
        binary=None,
    )
    result["stage_errors"] = list(stage_errors)
    if deadline is not None:
        import time

        if time.monotonic() >= deadline:
            result.update(
                errors=["stage deadline exhausted; bounded minimal incomplete receipt"],
                inventory_skipped=True,
                outputs_present={},
            )
            write(build / "build-receipt.json", result)
            return result
    try:
        if stage_errors:
            raise ValueError("failed stage; incomplete build receipt")
        pins = verify_pins(request["input_pins"])
        result["input_pins"] = pins
        if [s["name"] for s in steps] != ["configure", "build"] or any(
            type(s.get("exit")) is not int or s["exit"] != 0 or s.get("cleanup", {}).get("exit") != 0 for s in steps
        ):
            raise ValueError("configure/build exit or owned cleanup incomplete")

        def known(name):
            path = Path(name).resolve(strict=True)
            if path.is_relative_to(build):
                result["artifacts"][path.relative_to(build).as_posix()] = file_pin(path)
                return
            if str(path) not in {str(Path(p).resolve()) for p in pins}:
                raise ValueError("undeclared consumed input: " + str(path))

        def artifact(path):
            record = file_pin(path)
            result["artifacts"][Path(path).relative_to(build).as_posix()] = record
            raw = Path(path).read_bytes()
            if len(raw) > CAP or hashlib.sha256(raw).hexdigest() != record["sha256"] or file_pin(path) != record:
                raise ValueError("build artifact changed between pin and parse")
            return raw.decode("utf-8")

        def expand(tokens, depth=0, seen=()):
            if depth > 4 or len(tokens) > 65536:
                raise ValueError("response expansion bound")
            expanded = []
            for token in tokens:
                if token.startswith("@"):
                    path = (build / token[1:]).resolve(strict=True)
                    if path in seen:
                        raise ValueError("cyclic response file")
                    known(path)
                    text = artifact(path) if path.is_relative_to(build) else retain_text(path).decode("utf-8")
                    expanded.extend(expand(shlex.split(text), depth + 1, (*seen, path)))
                else:
                    expanded.append(token)
            return expanded

        def retain_text(path):
            path = Path(path).resolve(strict=True)
            record = file_pin(path)
            if record["bytes"] > 1024**2:
                raise ValueError("explicit response/script exceeds 1MiB")
            with path.open("rb") as stream:
                raw = stream.read(1024**2 + 1)
            if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"] or file_pin(path) != record:
                raise ValueError("explicit response/script changed")
            saved = result.setdefault("explicit_text_inputs", {})
            saved[str(path)] = dict(pin=record, raw_hex=raw.hex())
            if sum(row["pin"]["bytes"] for row in saved.values()) > 4 * 1024**2:
                raise ValueError("explicit response/script total exceeds 4MiB")
            return raw

        cache = artifact(build / "CMakeCache.txt")
        if "CMAKE_BUILD_TYPE:STRING=Release" not in cache or request["bindings"]["pinned_gxx"] not in cache:
            raise ValueError("unexpected configured compiler/build type")
        commands = json.loads(artifact(build / "compile_commands.json"))
        if type(commands) is not list or len(commands) != 1:
            raise ValueError("adapter must have exactly one compilation unit")
        entry = commands[0]
        argv = expand(entry.get("arguments") or shlex.split(entry["command"]))
        if (
            Path(entry["file"]).resolve() != Path(request["source"]).resolve()
            or Path(argv[0]).resolve() != Path(request["bindings"]["pinned_gxx"]).resolve()
            or "-std=c++17" not in argv
            or "-O2" not in argv
            or "-MD" not in argv
            or any(a.startswith("-std=") and a != "-std=c++17" for a in argv)
            or any(a.startswith("-O") and a != "-O2" for a in argv)
        ):
            raise ValueError("unexpected compiler/source/standard/O2/system-depfile command")
        known(entry["file"])
        known(argv[0])
        target_dir = build / "CMakeFiles/openvins_offset_reset_v2.dir"
        object_path = (Path(entry["directory"]) / argv[argv.index("-o") + 1]).resolve(strict=True)
        if not object_path.is_relative_to(target_dir) or object_path.suffix != ".o":
            raise ValueError("unexpected adapter object output")
        known(object_path)
        depfiles = list(target_dir.rglob("*.d"))
        if not depfiles:
            raise ValueError("missing compiler depfiles including system headers")
        for path in depfiles:
            text = artifact(path).replace("\\\n", "")
            dependencies = shlex.split(text.split(": ", 1)[1])
            if not dependencies:
                raise ValueError("empty depfile")
            for name in dependencies:
                known(Path(entry["directory"]) / name)
            result["depfiles"].append(dict(path=str(path), dependencies=dependencies))
        trace = artifact(build / "cmake-trace.jsonl")
        if not trace.strip():
            raise ValueError("missing CMake consumed module trace")
        for line in trace.splitlines():
            row = json.loads(line)
            if "file" in row:
                known(row["file"])
        original_link = shlex.split(artifact(target_dir / "link.txt"))
        tokens = []
        for token in original_link:
            if token.startswith("-Wl,"):
                tokens.extend(token[4:].split(","))
            elif token != "-Xlinker":
                tokens.append(token)
        link = expand(tokens)
        if not link or Path(link[0]).resolve() != Path(argv[0]).resolve():
            raise ValueError("unexpected link driver")
        resolutions = request.get("link_resolutions", {})
        inputs = iter(link[1:])
        file_flags = (
            "-T",
            "--script",
            "--version-script",
            "--dynamic-list",
            "--retain-symbols-file",
            "--just-symbols",
            "-include",
            "-imacros",
            "-specs",
            "--specs",
            "-fplugin",
        )
        lookup_flags = (
            "-L",
            "-rpath",
            "--rpath",
            "-rpath-link",
            "--rpath-link",
            "--sysroot",
            "-sysroot",
            "-z",
            "-soname",
            "--soname",
            "-m",
        )
        for token in inputs:
            if token == "-o":
                if (build / next(inputs)).resolve() != build / "openvins_offset_reset_v2":
                    raise ValueError("unexpected link output")
                continue
            if token in file_flags:
                selected = build / next(inputs)
                known(selected)
                retain_text(selected)
                continue
            if token in lookup_flags:
                next(inputs)
                continue
            matched = False
            for flag in file_flags:
                if token.startswith(flag + "=") or (flag == "-T" and token.startswith("-T") and len(token) > 2):
                    selected = build / (token.split("=", 1)[1] if "=" in token else token[2:])
                    known(selected)
                    retain_text(selected)
                    matched = True
                    break
            if matched:
                continue
            if token.startswith("-l"):
                if token not in resolutions or not resolutions[token]:
                    raise ValueError("unresolved linker library: " + token)
                for name in resolutions[token]:
                    known(name)
            elif not token.startswith("-"):
                known(build / token)
            elif "/" in token and not token.startswith(("-L", "-rpath=", "--rpath=", "--sysroot=")):
                raise ValueError("unsupported explicit linker path flag: " + token)
        result["driver_link_argv"] = original_link
        result["compiler_argv"], result["link_argv"] = argv, link
        if not any((build / token).resolve() == object_path for token in link if not token.startswith("-")):
            raise ValueError("link does not consume the recorded adapter object")
        binary = build / "openvins_offset_reset_v2"
        result["binary"] = file_pin(binary)
        result["objects"] = {p.relative_to(build).as_posix(): file_pin(p) for p in target_dir.rglob("*.o")}
        with binary.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                raise ValueError("new target is not ELF")
        # Neither ELF magic nor these bytes assert ABI, NEEDED resolution or lazy maps.
        verify_pins(pins)
        for name, pin in result["artifacts"].items():
            if file_pin(build / name) != pin:
                raise ValueError("generated build evidence changed while consumed")
        result["complete"] = True
    except Exception as exc:
        result["errors"].append(repr(exc))
    result["outputs_present"] = {}
    try:
        total = 0
        for index, path in enumerate(sorted(build.rglob("*"))):
            if deadline is not None:
                import time

                if time.monotonic() >= deadline:
                    result["inventory_skipped"] = True
                    raise TimeoutError("partial inventory exhausted stage budget")
            if not path.is_file():
                continue
            if index >= 512:
                raise ValueError("partial build output inventory exceeds 512 entries")
            total += path.stat().st_size
            if total > CAP:
                raise ValueError("partial build output inventory exceeds 64MiB")
            result["outputs_present"][path.relative_to(build).as_posix()] = file_pin(path)
    except Exception as exc:
        result["complete"] = False
        result["errors"].append(repr(exc))
    write(build / "build-receipt.json", result)
    return result
