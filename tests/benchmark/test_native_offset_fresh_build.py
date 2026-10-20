"""Fresh-source software behavior only: no compiler, Linux, resources or network."""

import json
import os
import socket
import subprocess
from pathlib import Path

import pytest

from tools.benchmark import native_offset_once as once
from tools.benchmark.native_offset_build_receipt import file_pin, produce


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("native/resource/network boundary forbidden")

    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(os, "system", denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(once, "collect_resources", denied)


def bindings(tmp_path):
    return {
        key: str(tmp_path / key)
        for key in (
            "pinned_cmake",
            "deployed_repo",
            "exclusive_build_dir",
            "pinned_gxx",
            "pinned_make",
            "toolchain_file",
            "upstream_source_tree",
            "eigen_config_dir",
            "opencv4_config_dir",
            "boost_config_dir",
            "ceres_config_dir",
        )
    }


def test_build_commands_need_no_existing_library_and_build_it_before_adapter(tmp_path):
    # Catch falling back to an external library or skipping the new library target.
    b = bindings(tmp_path)
    commands = once.build_commands(b)
    assert len(commands) == 3
    assert commands[1][-4:] == ["--target", "ov_msckf_lib", "--parallel", "1"]
    assert commands[2][-4:] == ["--target", "openvins_offset_reset_v2", "--parallel", "1"]
    assert "-DCMAKE_CXX_FLAGS_RELEASE=-O2" in commands[0]
    assert not any("OV_MSCKF=" in arg or "OPENVINS_LIBRARY_DIR=" in arg for arg in commands[0])


def test_old_library_bindings_refused_even_if_commands_could_ignore_them(tmp_path):
    b = bindings(tmp_path)
    b["openvins_library_file"] = "/old/libov_msckf_lib.so"
    with pytest.raises(ValueError, match="existing library"):
        once.build_commands(b)


def test_fixed_recipe_is_exclusive_and_contains_no_arbitrary_extra_translation_unit(tmp_path):
    from tools.benchmark.native_offset_fresh_build import prepare_sources

    build = tmp_path / "build"
    build.mkdir()
    path = prepare_sources(build, tmp_path / "source")
    text = path.read_text()
    assert text.count('.cpp"') == 34
    assert 'ov_msckf/src/state/Propagator.cpp"' in text
    assert 'ov_core/src/track/TrackKLT.cpp"' in text
    assert "/src/test_" not in text and "GLOB" not in text
    with pytest.raises(FileExistsError):
        prepare_sources(build, tmp_path / "other")


def fixture_fresh(tmp_path):
    from tools.benchmark.native_offset_fresh_build import SOURCES, prepare_sources

    build = tmp_path / "build"
    build.mkdir()
    upstream = tmp_path / "upstream"
    adapter = tmp_path / "probe.cpp"
    compiler = tmp_path / "g++"
    header = tmp_path / "header.h"
    for path in (adapter, compiler, header):
        path.write_text("inert fixture, never executed")
    entries = []
    for index, relative in enumerate((*SOURCES, None)):
        source = upstream / relative if relative else adapter
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("modeled source " + str(index))
        target = "ov_msckf_lib" if relative else "openvins_offset_reset_v2"
        directory = build / ("CMakeFiles/" + target + ".dir")
        directory.mkdir(parents=True, exist_ok=True)
        obj = directory / (str(index) + ".o")
        obj.write_bytes(b"inert object " + str(index).encode())
        (directory / (obj.name + ".d")).write_text(obj.as_posix() + ": " + source.as_posix() + " " + header.as_posix() + "\n")
        entries.append(
            dict(
                directory=build.as_posix(),
                file=source.as_posix(),
                arguments=[
                    compiler.as_posix(),
                    "-std=c++17",
                    "-O2",
                    "-MD",
                    "-DROS_AVAILABLE=0",
                    "-DENABLE_ARUCO_TAGS=0",
                    "-c",
                    source.as_posix(),
                    "-o",
                    obj.relative_to(build).as_posix(),
                ],
            )
        )
    library = build / "libov_msckf_lib.so"
    library.write_bytes(b"\x7fELF" + b"modeled shared library")
    binary = build / "openvins_offset_reset_v2"
    binary.write_bytes(b"\x7fELF" + b"modeled adapter")
    for target, selected, output in (
        ("ov_msckf_lib", entries[:-1], "libov_msckf_lib.so"),
        ("openvins_offset_reset_v2", entries[-1:], "openvins_offset_reset_v2"),
    ):
        tokens = [compiler.as_posix(), *[e["arguments"][-1] for e in selected]]
        tokens += ["-shared"] if target == "ov_msckf_lib" else ["libov_msckf_lib.so"]
        (build / ("CMakeFiles/" + target + ".dir/link.txt")).write_text(" ".join([*tokens, "-o", output]))
    (build / "CMakeCache.txt").write_text(
        "CMAKE_BUILD_TYPE:STRING=Release\nCMAKE_CXX_COMPILER:FILEPATH=" + compiler.as_posix() + "\n"
    )
    prepare_sources(build, upstream)
    (build / "compile_commands.json").write_text(json.dumps(entries))
    (build / "cmake-trace.jsonl").write_text(json.dumps(dict(file=header.as_posix())) + "\n")
    inputs = [adapter, compiler, header, *[upstream / name for name in SOURCES]]
    request = dict(
        build_profile="fixed-source-openvins-v1",
        upstream_commit=once.UPSTREAM,
        source=adapter.as_posix(),
        input_pins={str(p): file_pin(p) for p in inputs},
        bindings=dict(exclusive_build_dir=str(build), upstream_source_tree=str(upstream), pinned_gxx=compiler.as_posix()),
    )
    steps = [
        dict(name=name, exit=0, command=[name], cleanup=dict(exit=0)) for name in ("configure", "openvins-library", "adapter")
    ]
    steps[1]["library"] = file_pin(library)
    return request, build, steps


def test_receipt_binds_all_new_objects_both_links_and_generated_library(tmp_path):
    request, build, steps = fixture_fresh(tmp_path)
    result = produce(request, build, steps)
    assert result["complete"] is True, result["errors"]
    assert len(result["translation_units"]) == 35
    assert len(result["objects"]) == 35
    assert result["library"] == file_pin(build / "libov_msckf_lib.so")
    assert result["links"]["openvins_offset_reset_v2"]["library"] == result["library"]
    assert result["native_qualified"] is False and result["runtime_closure_qualified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "missing-tu",
        "extra-tu",
        "duplicate-tu",
        "old-library",
        "missing-link-object",
        "missing-depfile",
        "unknown-header",
        "failed-library",
        "cleanup",
        "oversize",
        "missing-checkpoint",
        "conflicting-ros",
        "missing-source-dependency",
    ],
)
def test_fresh_receipt_fails_closed_without_losing_partial_result(tmp_path, fault, monkeypatch):
    from tools.benchmark import native_offset_build_receipt as receipts

    request, build, steps = fixture_fresh(tmp_path)
    path = build / "compile_commands.json"
    entries = json.loads(path.read_text())
    if fault == "missing-tu":
        entries.pop(0)
    if fault == "extra-tu":
        entries[0]["file"] = str(tmp_path / "unselected.cpp")
    if fault == "duplicate-tu":
        entries[0] = entries[1]
    if fault == "conflicting-ros":
        entries[0]["arguments"].append("-DROS_AVAILABLE=1")
    path.write_text(json.dumps(entries))
    link = build / "CMakeFiles/openvins_offset_reset_v2.dir/link.txt"
    if fault == "old-library":
        link.write_text(link.read_text().replace("libov_msckf_lib.so", "/old/libov_msckf_lib.so"))
    if fault == "missing-link-object":
        liblink = build / "CMakeFiles/ov_msckf_lib.dir/link.txt"
        liblink.write_text(liblink.read_text().replace("CMakeFiles/ov_msckf_lib.dir/0.o", ""))
    if fault == "missing-depfile":
        (build / "CMakeFiles/ov_msckf_lib.dir/0.o.d").unlink()
    if fault == "missing-source-dependency":
        p = build / "CMakeFiles/ov_msckf_lib.dir/0.o.d"
        p.write_text(p.read_text().replace(entries[0]["file"], ""))
    if fault == "unknown-header":
        request["input_pins"].pop(str(tmp_path / "header.h"))
    if fault == "failed-library":
        steps[1]["exit"] = 2
        steps.pop()
    if fault == "cleanup":
        steps[1]["cleanup"]["exit"] = None
    if fault == "missing-checkpoint":
        steps[1].pop("library")
    if fault == "oversize":
        original = receipts.file_pin

        def pin(path):
            if Path(path).name == "libov_msckf_lib.so":
                raise ValueError("regular bounded file required")
            return original(path)

        monkeypatch.setattr(receipts, "file_pin", pin)
    result = produce(request, build, steps)
    assert result["complete"] is False and result["errors"]
    assert result["native_qualified"] is False
    assert (build / "build-receipt.json").is_file()


def test_deadline_keeps_minimal_failure_receipt_without_inventory(tmp_path):
    request = dict(build_profile="fixed-source-openvins-v1")
    result = produce(request, tmp_path, [], deadline=0)
    assert result["complete"] is False and result["inventory_skipped"] is True
    assert result["outputs_present"] == {}


def request_fixture(tmp_path, monkeypatch):
    from tools.benchmark.native_offset_fresh_build import SOURCES

    monkeypatch.setattr(once, "ROOT", tmp_path)
    monkeypatch.setattr(once, "ATTEMPT", tmp_path / "results/native-offset-once-attempt-v1")
    source_pins = {}
    for name in (*once.SOURCE_NAMES, "native_offset_reset_v2/CMakeLists.txt"):
        path = tmp_path / "tools/benchmark" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("inert production input")
        source_pins[str(path)] = file_pin(path)
    b = bindings(tmp_path)
    b.update({key: str(tmp_path / key) for key in once.BUILD_KEYS if key not in b})
    b.update(
        deployed_repo=str(tmp_path),
        capture_script=str(tmp_path / "tools/benchmark/capture_disarmed_sensors.py"),
        exclusive_build_dir=str(once.ATTEMPT / "build/artifacts"),
    )
    dirs = {
        "deployed_repo",
        "upstream_source_tree",
        "exclusive_build_dir",
        "eigen_config_dir",
        "opencv4_config_dir",
        "boost_config_dir",
        "ceres_config_dir",
    }
    for key, name in b.items():
        if key not in dirs and not Path(name).exists():
            Path(name).write_text("inert tool/receipt")
    Path(b["current_linux_source_manifest"]).write_text(
        json.dumps(dict(schema="native-offset-current-source-v1", files=source_pins))
    )
    Path(b["header_package_manifest"]).write_text(
        json.dumps(
            dict(
                schema="native-offset-build-input-closure-v1",
                groups={
                    key: [b["pinned_gxx"]]
                    for key in ("tools", "system_headers", "cmake_modules", "link_implicit", "libraries", "packages")
                },
            )
        )
    )
    manifest = dict(commit=once.UPSTREAM, files={})
    # Inert 143-file declaration tests the gate, not actual upstream or Linux provenance.
    for relative in (*SOURCES, *[f"ov_core/model-{i}.h" for i in range(109)]):
        p = Path(b["upstream_source_tree"]) / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("modeled fixed input")
        manifest["files"][relative] = file_pin(p)
    mpath = tmp_path / "results/native-offset-run-plan-20261018/upstream-build-source-manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest))
    monkeypatch.setattr(once, "UPSTREAM_MANIFEST_SHA", file_pin(mpath)["sha256"])
    pins = dict(source_pins)
    pins.update(
        {
            str(Path(b["upstream_source_tree"]) / name): file_pin(Path(b["upstream_source_tree"]) / name)
            for name in manifest["files"]
        }
    )
    pins.update({name: file_pin(name) for key, name in b.items() if key not in dirs})
    pins[str(mpath)] = file_pin(mpath)
    scope_tools = []
    for name in ("env", "time", "timeout", "systemd-run", "systemctl"):
        path = tmp_path / name
        path.write_text("inert scope tool")
        scope_tools.append(str(path))
        pins[str(path)] = file_pin(path)
    monkeypatch.setattr(once, "SCOPE_TOOLS", tuple(scope_tools))
    request = dict(
        schema="native-offset-fresh-source-request-v1",
        build_profile="fixed-source-openvins-v1",
        stage="build",
        target=once.TARGET,
        upstream_commit=once.UPSTREAM,
        bindings=b,
        input_pins=pins,
        build_environment={"HOME": "/home/test", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    monkeypatch.setattr(once.time, "time", lambda: 101)

    def save():
        path, review = tmp_path / "request.json", tmp_path / "review.json"
        path.write_text(json.dumps(request))
        sha = file_pin(path)["sha256"]
        review.write_text(
            json.dumps(
                dict(
                    schema="native-offset-fresh-source-admission-v1",
                    decision="allow-once",
                    request_sha256=sha,
                    stage=request["stage"],
                    covers=once.COVERS,
                    created_unix=100,
                    expires_unix=400,
                )
            )
        )
        return path, sha, review, file_pin(review)["sha256"], request["stage"]

    return request, save


def test_real_request_gate_selects_fresh_source_build_without_preexisting_outputs(tmp_path, monkeypatch):
    request, save = request_fixture(tmp_path, monkeypatch)
    selection = once.verify_request(*save())
    assert len(selection["command"]) == 3
    assert selection["qualification"] is False
    assert not Path(request["bindings"]["exclusive_build_dir"]).exists()
    assert json.loads(json.dumps(selection)) == selection


@pytest.mark.parametrize("fault", ["legacy-schema", "old-library", "source-drift", "terminal-output"])
def test_fresh_request_does_not_admit_legacy_or_drifted_inputs(tmp_path, monkeypatch, fault):
    request, save = request_fixture(tmp_path, monkeypatch)
    if fault == "legacy-schema":
        request["schema"] = "native-offset-once-request-v1"
    if fault == "old-library":
        request["bindings"]["openvins_library_file"] = "/old/never-open.so"
    if fault == "source-drift":
        (Path(request["bindings"]["upstream_source_tree"]) / "ov_core/src/cpi/CpiV1.cpp").write_text("changed")
    if fault == "terminal-output":
        Path(request["bindings"]["exclusive_build_dir"]).mkdir(parents=True)
    with pytest.raises((ValueError, FileExistsError)):
        once.verify_request(*save())


@pytest.mark.parametrize("fault", ["legacy-receipt", "wrong-library", "failed-build-scope", "missing-new-abi"])
def test_run_gate_cannot_use_old_or_failed_build_result(tmp_path, monkeypatch, fault):
    request, save = request_fixture(tmp_path, monkeypatch)
    request["stage"] = "run"
    build = Path(request["bindings"]["exclusive_build_dir"])
    build.mkdir(parents=True)
    for name in ("libov_msckf_lib.so", once.TARGET, "other.so"):
        (build / name).write_bytes(b"inert fixture output")
    receipt = dict(
        schema="native-offset-fresh-source-build-receipt-v1",
        build_profile="fixed-source-openvins-v1",
        upstream_commit=once.UPSTREAM,
        complete=True,
        native_qualified=False,
        binary=file_pin(build / once.TARGET),
        library=file_pin(build / "libov_msckf_lib.so"),
        input_pins=dict(request["input_pins"]),
    )
    if fault == "legacy-receipt":
        receipt["schema"] = "native-offset-build-receipt-v1"
    if fault == "wrong-library":
        receipt["library"] = file_pin(build / "other.so")
    (build / "build-receipt.json").write_text(json.dumps(receipt))
    request["build_receipt"] = file_pin(build / "build-receipt.json")
    for name, value in (
        (
            "completion.json",
            dict(consumed=True, error=None, launch=dict(exit=0 if fault == "missing-new-abi" else 2, owned_group_released=True)),
        ),
        ("inside-completion.json", dict(exit=0, errors=[], elapsed_s=1)),
    ):
        path = once.ATTEMPT / "build" / name
        path.write_text(json.dumps(value))
        request["input_pins"][str(path)] = file_pin(path)
    with pytest.raises(ValueError, match="ABI" if fault == "missing-new-abi" else None):
        once.verify_request(*save())


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("none", 3),
        ("configure", 1),
        ("library", 2),
        ("adapter", 3),
        ("cleanup", 2),
        ("deadline", 2),
        ("library-cap", 2),
        ("revalidate-deadline", 0),
    ],
)
def test_scoped_chain_stops_at_failed_leg_retains_cleanup_and_shares_budget(tmp_path, monkeypatch, fault, expected):
    import sys
    from types import SimpleNamespace

    from tools.benchmark import native_offset_once_scope as scope

    request, template, _ = fixture_fresh(tmp_path)
    build = tmp_path / "actual-artifacts"
    request["bindings"]["exclusive_build_dir"] = str(build)
    commands = [["inert-cmake", name] for name in ("configure", "library", "adapter")]
    selection = dict(request=request, command=commands, source=request["source"], environment={"PATH": "/usr/bin:/bin"})
    verified_calls = [0]

    def verify(*args, **kwargs):
        verified_calls[0] += 1
        if fault == "revalidate-deadline" and verified_calls[0] == 2:
            clock[0] = 301
        return selection

    monkeypatch.setattr(scope, "verify_request", verify)
    monkeypatch.setattr(scope, "require_consumed_claim", lambda profile: None)
    monkeypatch.setattr(scope, "manager_environment", lambda: {})
    limits_record = []
    monkeypatch.setitem(
        sys.modules, "resource", SimpleNamespace(RLIMIT_FSIZE=1, setrlimit=lambda *args: limits_record.append(args))
    )
    unit = "fly-offset-" + "a" * 24 + ".scope"
    group = "/user.slice/" + unit
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if path.as_posix() == "/proc/self/cgroup":
            return "0::" + group + "\n"
        if path.as_posix().startswith("/sys/fs/cgroup"):
            return {
                "memory.max": str(1024**3),
                "memory.swap.max": "0",
                "cpu.max": "100000 100000",
                "pids.max": "64",
                "memory.events": "oom 0\noom_kill 0\n",
                "memory.peak": "1234",
            }[path.name]
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)

    def systemctl(command, **kwargs):
        assert command[:3] == ["systemctl", "--user", "show"]
        return SimpleNamespace(stdout="InvocationID=owned\nControlGroup=" + group + "\n")

    monkeypatch.setattr(subprocess, "run", systemctl)
    launched, cleaned = [], []
    clock = [0]
    monkeypatch.setattr(scope.time, "monotonic", lambda: clock[0])

    class Process:
        pid = 42

        def __init__(self, command, **kwargs):
            self.name = command[-1]
            assert command[:2] == ["/usr/bin/time", "-v"]
            self.remaining = float(command[-3].removesuffix("s"))
            launched.append(self)
            if self.name == "library":
                for path in template.rglob("*"):
                    if not path.is_file() or path.name == "openvins-fixed-sources.cmake":
                        continue
                    destination = build / path.relative_to(template)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    raw = path.read_bytes().replace(template.as_posix().encode(), build.as_posix().encode())
                    destination.write_bytes(raw)

        def wait(self, **kwargs):
            clock[0] += 301 if fault == "deadline" and self.name == "library" else 10
            return 2 if self.name == fault else 0

    monkeypatch.setattr(subprocess, "Popen", Process)

    def cleanup(process):
        cleaned.append(process.name)
        return dict(exit=None if fault == "cleanup" and process.name == "library" else 0)

    monkeypatch.setattr(scope, "cleanup_owned", cleanup)
    if fault == "library-cap":

        def refuse(path):
            raise ValueError("regular bounded file required")

        monkeypatch.setattr(scope, "file_pin", refuse)
    output = tmp_path / "scope"
    output.mkdir()
    result = scope.run_inside(
        dict(
            stage="build",
            output=str(output),
            unit=unit,
            request="inert",
            sha256="a" * 64,
            review="inert",
            review_sha256="b" * 64,
            verified=selection,
        )
    )
    receipt = json.loads((build / "build-receipt.json").read_text())
    assert len(launched) == expected
    assert cleaned == [p.name for p in launched]
    assert [p.remaining for p in launched] == [300, 290, 280][:expected]
    assert limits_record == [(1, (67108864, 67108864))]
    assert (output / "inside-completion.json").is_file()
    if fault == "none":
        assert result == 0 and receipt["complete"] is True, receipt["errors"]
    else:
        assert result == 2 and receipt["complete"] is False
    assert receipt["native_qualified"] is False


def test_current_alias_pin_is_consumed_without_losing_its_lexical_identity(tmp_path, monkeypatch):
    from tools.benchmark.native_offset_fresh_receipt import Evidence

    target, alias = tmp_path / "g++-13", tmp_path / "g++"
    target.write_text("inert driver")
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        return target if path == alias else original(path, *args, **kwargs)

    # Model Linux alias resolution; Windows fixture does not require symlink privileges.
    monkeypatch.setattr(Path, "resolve", resolve)
    pin = file_pin(alias)
    evidence = Evidence(tmp_path / "build", {str(alias): pin}, dict(artifacts={}), None)
    assert evidence.known(alias) == target
    target.write_text("changed driver")
    with pytest.raises(ValueError, match="drifted"):
        evidence.known(alias)


def test_failure_inventory_stops_during_directory_iteration_at_original_entry_cap(tmp_path, monkeypatch):
    for index in range(520):
        (tmp_path / f"output-{index}").write_bytes(b"inert partial output")
    original = os.scandir
    consumed = [0]

    class Scan:
        def __init__(self, path):
            self.iterator = original(path)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.iterator.close()

        def __iter__(self):
            return self

        def __next__(self):
            item = next(self.iterator)
            consumed[0] += 1
            return item

    monkeypatch.setattr(os, "scandir", Scan)
    result = produce(dict(build_profile="fixed-source-openvins-v1"), tmp_path, [], stage_errors=["inert failed build"])
    assert result["complete"] is False and result["inventory_skipped"] is True
    assert len(result["outputs_present"]) <= 512
    assert consumed[0] <= 513
