"""Current fresh-source build record, never historical proof, ABI or runtime admission."""

import hashlib
import json
import os
import shlex
import time
from pathlib import Path

from tools.benchmark import native_offset_build_receipt as io
from tools.benchmark.native_offset_fresh_build import LIBRARY, PROFILE, SOURCES, STEP_NAMES, source_recipe


class Evidence:
    def __init__(self, build, pins, result, deadline):
        self.build, self.pins, self.result, self.deadline = build, pins, result, deadline
        self.resolved_inputs = {Path(p).resolve(): v for p, v in pins.items()}

    def check(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("shared build deadline exhausted")

    def pin(self, path):
        self.check()
        pin = io.file_pin(path)
        self.check()
        return pin

    def known(self, path):
        path = Path(path).resolve(strict=True)
        if path.is_relative_to(self.build):
            self.result["artifacts"][path.relative_to(self.build).as_posix()] = self.pin(path)
        elif path not in self.resolved_inputs or self.pin(self.resolved_inputs[path]["path"]) != self.resolved_inputs[path]:
            raise ValueError("undeclared/drifted consumed input: " + str(path))
        return path

    def text(self, path, *, explicit=False):
        path = self.known(path)
        pin = self.pin(path)
        cap = 1024**2 if explicit else io.CAP
        if pin["bytes"] > cap:
            raise ValueError("bounded text input exceeded")
        with path.open("rb") as stream:
            raw = stream.read(cap + 1)
        if len(raw) != pin["bytes"] or hashlib.sha256(raw).hexdigest() != pin["sha256"] or self.pin(path) != pin:
            raise ValueError("consumed build evidence changed")
        if explicit:
            saved = self.result.setdefault("explicit_text_inputs", {})
            saved[str(path)] = dict(pin=pin, raw_hex=raw.hex())
            if sum(row["pin"]["bytes"] for row in saved.values()) > 4 * 1024**2:
                raise ValueError("explicit response/script total exceeds 4MiB")
        return raw.decode("utf-8")

    def expand(self, tokens, depth=0, seen=()):
        if depth > 4 or len(tokens) > 65536:
            raise ValueError("response expansion bound")
        result = []
        for token in tokens:
            self.check()
            if token.startswith("@"):
                path = (self.build / token[1:]).resolve(strict=True)
                if path in seen:
                    raise ValueError("cyclic response input")
                result.extend(self.expand(shlex.split(self.text(path, explicit=True)), depth + 1, (*seen, path)))
            else:
                result.append(token)
            if len(result) > 65536:
                raise ValueError("expanded token bound")
        return result


def collect_link(evidence, request, target, objects, output, library=None):
    build = evidence.build
    original = shlex.split(evidence.text(build / f"CMakeFiles/{target}.dir/link.txt"))
    tokens = []
    for token in original:
        if token.startswith("-Wl,"):
            tokens.extend(token[4:].split(","))
        elif token != "-Xlinker":
            tokens.append(token)
    argv = evidence.expand(tokens)
    if not argv or Path(argv[0]).resolve() != Path(request["bindings"]["pinned_gxx"]).resolve():
        raise ValueError("unexpected link driver")
    evidence.known(argv[0])
    selected = set()
    resolved_library = None
    declared_output = None
    inputs = iter(argv[1:])
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
    lookup = (
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

    def consumed(name):
        nonlocal resolved_library
        path = evidence.known(build / name)
        if path.suffix == ".o":
            if path in selected:
                raise ValueError("duplicate linked object")
            selected.add(path)
        if path.name == LIBRARY:
            if library is None or path != build / LIBRARY:
                raise ValueError("existing library cannot substitute new output")
            resolved_library = evidence.pin(path)

    for token in inputs:
        if token == "-o":
            if declared_output is not None:
                raise ValueError("duplicate link output")
            declared_output = (build / next(inputs)).resolve()
        elif token in file_flags:
            evidence.text(build / next(inputs), explicit=True)
        elif token in lookup:
            next(inputs)
        elif any(token.startswith(flag + "=") for flag in file_flags):
            evidence.text(build / token.split("=", 1)[1], explicit=True)
        elif token.startswith("-T") and len(token) > 2:
            evidence.text(build / token[2:], explicit=True)
        elif token.startswith("-l"):
            names = request.get("link_resolutions", {}).get(token)
            if not names:
                raise ValueError("unresolved linker input: " + token)
            for name in names:
                consumed(name)
        elif not token.startswith("-"):
            consumed(token)
        elif "/" in token and not token.startswith(("-L", "-rpath=", "--rpath=", "--sysroot=")):
            raise ValueError("unsupported explicit linker path flag: " + token)
    if declared_output != build / output or selected != set(objects):
        raise ValueError("link output/object coverage differs")
    if library is not None and resolved_library != library:
        raise ValueError("adapter does not link the exact new library")
    if target == "ov_msckf_lib" and "-shared" not in argv:
        raise ValueError("new library is not a shared-library link")
    return dict(driver_argv=original, argv=argv, output=evidence.pin(build / output), library=resolved_library)


def produce_fresh(request, build, steps, *, stage_errors=(), deadline=None):
    build = Path(build).resolve()
    result = dict(
        schema="native-offset-fresh-source-build-receipt-v1",
        build_profile=PROFILE,
        upstream_commit=request.get("upstream_commit"),
        complete=False,
        native_qualified=False,
        runtime_closure_qualified=False,
        abi_verified=False,
        historical_old_library_proven=False,
        stage_errors=list(stage_errors),
        errors=[],
        steps=steps,
        artifacts={},
        depfiles=[],
        translation_units=[],
        objects={},
        links={},
        library=None,
        binary=None,
        outputs_present={},
    )
    evidence = Evidence(build, {}, result, deadline)
    try:
        evidence.check()
        if stage_errors:
            raise ValueError("failed stage; incomplete fresh build receipt")
        if [s["name"] for s in steps] != list(STEP_NAMES) or any(
            type(s.get("exit")) is not int or s["exit"] != 0 or s.get("cleanup", {}).get("exit") != 0 for s in steps
        ):
            raise ValueError("configure/library/adapter or owned cleanup incomplete")
        pins = io.verify_pins(request["input_pins"])
        result["input_pins"] = pins
        evidence = Evidence(build, pins, result, deadline)
        if any(Path(p).resolve().is_relative_to(build) for p in pins):
            raise ValueError("generated outputs cannot be predeclared build inputs")
        cache = evidence.text(build / "CMakeCache.txt")
        if "CMAKE_BUILD_TYPE:STRING=Release" not in cache or request["bindings"]["pinned_gxx"] not in cache:
            raise ValueError("unexpected configured compiler/build type")
        upstream = Path(request["bindings"]["upstream_source_tree"]).resolve()
        if evidence.text(build / "openvins-fixed-sources.cmake") != source_recipe(upstream):
            raise ValueError("fixed source recipe changed")
        expected = {upstream / name for name in SOURCES}
        adapter = Path(request["source"]).resolve()
        commands = json.loads(evidence.text(build / "compile_commands.json"))
        if type(commands) is not list or len(commands) != 35:
            raise ValueError("expected 34 library plus one adapter translation unit")
        seen, objects = set(), {"ov_msckf_lib": [], "openvins_offset_reset_v2": []}
        for entry in commands:
            source = Path(entry["file"]).resolve()
            if source in seen or source not in expected | {adapter} or Path(entry["directory"]).resolve() != build:
                raise ValueError("duplicate/unselected source or build directory")
            seen.add(source)
            target = "openvins_offset_reset_v2" if source == adapter else "ov_msckf_lib"
            argv = evidence.expand(entry.get("arguments") or shlex.split(entry["command"]))
            if (
                Path(argv[0]).resolve() != Path(request["bindings"]["pinned_gxx"]).resolve()
                or not {"-std=c++17", "-O2", "-MD", "-DROS_AVAILABLE=0", "-DENABLE_ARUCO_TAGS=0", "-c"}.issubset(argv)
                or any(a.startswith("-std=") and a != "-std=c++17" for a in argv)
                or any(a.startswith("-O") and a != "-O2" for a in argv)
                or any(a.startswith("-DROS_AVAILABLE=") and a != "-DROS_AVAILABLE=0" for a in argv)
                or any(a.startswith("-DENABLE_ARUCO_TAGS=") and a != "-DENABLE_ARUCO_TAGS=0" for a in argv)
                or "-MMD" in argv
                or argv.count("-o") != 1
                or argv.count("-c") != 1
                or (build / argv[argv.index("-c") + 1]).resolve() != source
            ):
                raise ValueError("unexpected source/compiler/C++17/O2/NO_ROS/depfile command")
            evidence.known(source)
            evidence.known(argv[0])
            obj = (build / argv[argv.index("-o") + 1]).resolve(strict=True)
            if not obj.is_relative_to(build / f"CMakeFiles/{target}.dir") or obj.suffix != ".o":
                raise ValueError("unexpected new object output")
            if obj in objects[target]:
                raise ValueError("duplicate compilation output")
            objects[target].append(obj)
            evidence.known(obj)
            depfile = Path(str(obj) + ".d")
            text = evidence.text(depfile).replace("\\\n", "")
            target_text, deps = text.split(": ", 1)
            dependencies = shlex.split(deps)
            if not dependencies or (build / shlex.split(target_text)[0]).resolve() != obj:
                raise ValueError("empty/mismatched system depfile")
            for name in dependencies:
                evidence.known(build / name)
            if source not in {(build / name).resolve() for name in dependencies}:
                raise ValueError("source missing from its depfile")
            result["depfiles"].append(dict(path=str(depfile), dependencies=dependencies))
            result["translation_units"].append(dict(source=str(source), object=str(obj), target=target, argv=argv))
            result["objects"][obj.relative_to(build).as_posix()] = evidence.pin(obj)
        if seen != expected | {adapter}:
            raise ValueError("fixed source coverage incomplete")
        trace = evidence.text(build / "cmake-trace.jsonl")
        if not trace.strip():
            raise ValueError("missing CMake consumed module trace")
        for line in trace.splitlines():
            row = json.loads(line)
            if "file" in row:
                evidence.known(row["file"])
        library = build / LIBRARY
        for path in (library, build / "openvins_offset_reset_v2"):
            evidence.known(path)
            with path.open("rb") as stream:
                if stream.read(4) != b"\x7fELF":
                    raise ValueError("new output lacks ELF magic (not ABI verification)")
        result["library"] = evidence.pin(library)
        if steps[1].get("library") != result["library"]:
            raise ValueError("library drifted after its successful stage")
        for target, output, selected_library in (
            ("ov_msckf_lib", LIBRARY, None),
            ("openvins_offset_reset_v2", "openvins_offset_reset_v2", result["library"]),
        ):
            result["links"][target] = collect_link(evidence, request, target, objects[target], output, selected_library)
        result["binary"] = result["links"]["openvins_offset_reset_v2"]["output"]
        io.verify_pins(pins)
        for name, pin in result["artifacts"].items():
            if evidence.pin(build / name) != pin:
                raise ValueError("generated evidence changed while consumed")
        evidence.check()
        result["complete"] = True
    except Exception as exc:
        result["errors"].append(repr(exc))
    try:
        evidence.check()
        total, count = 0, 0
        pending = [build]
        while pending:
            evidence.check()
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    evidence.check()
                    count += 1
                    if count > 512:
                        raise ValueError("partial output inventory exceeds 512 entries")
                    path = Path(entry.path)
                    if entry.is_symlink() or getattr(path, "is_junction", lambda: False)():
                        raise ValueError("redirected build output inventory entry")
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        raise ValueError("nonregular build output inventory entry")
                    total += entry.stat(follow_symlinks=False).st_size
                    if total > io.CAP:
                        raise ValueError("partial output inventory exceeds 64MiB")
                    result["outputs_present"][path.relative_to(build).as_posix()] = evidence.pin(path)
    except Exception as exc:
        result["complete"] = False
        result["inventory_skipped"] = True
        result["errors"].append(repr(exc))
    io.write(build / "build-receipt.json", result)
    return result
