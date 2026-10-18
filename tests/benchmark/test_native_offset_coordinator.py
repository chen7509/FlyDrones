"""Only the new once/receipt lifecycle; process/resource boundaries are inert."""

import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def denied(*a, **k):
        raise AssertionError("native/network/resource execution forbidden")

    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(os, "system", denied)


def facts():
    return dict(
        windows_available=4 * 1024**3,
        wsl=dict(available=4 * 1024**3, processes=[]),
        windows_processes=[],
        blocked_processes=[],
        docker_exit=0,
        docker_running="",
    )


def test_consumed_precedes_dispatch_and_survives_failure(tmp_path):
    from tools.benchmark import native_offset_once as once

    output = tmp_path / "fixed"

    def launch(stage, *a):
        assert (stage / "consumed.json").is_file()
        raise RuntimeError("inert dispatcher failure after boundary")

    args = dict(collect=facts, verify=lambda *a: {"bound": True}, launch=launch, attempt=output)
    result = once.execute_once(Path("request"), "a" * 64, Path("review"), "b" * 64, "build", **args)
    assert result["consumed"] is True and "dispatcher failure" in result["error"]
    assert (output / "build/completion.json").is_file()
    with pytest.raises(FileExistsError):
        once.execute_once(Path("renamed-request"), "c" * 64, Path("review"), "b" * 64, "build", **args)


def test_refusal_saved_without_dispatch_and_cannot_repoll(tmp_path):
    from tools.benchmark import native_offset_once as once

    calls = []
    args = dict(
        collect=lambda: calls.append("collect") or dict(facts(), windows_available=1),
        verify=lambda *a: calls.append("verify"),
        launch=lambda *a: calls.append("launch"),
        attempt=tmp_path / "fixed",
    )
    result = once.execute_once(Path("r"), "a" * 64, Path("v"), "b" * 64, "build", **args)
    assert result["consumed"] is False and calls == ["collect"]
    assert (tmp_path / "fixed/build/firstfacts.json").is_file()
    with pytest.raises(FileExistsError):
        once.execute_once(Path("r"), "a" * 64, Path("v"), "b" * 64, "build", **args)
    assert calls == ["collect"]


def test_changed_selection_never_dispatches(tmp_path):
    from tools.benchmark import native_offset_once as once

    values = iter([{"source": "a"}, {"source": "b"}])
    calls = []
    result = once.execute_once(
        Path("r"),
        "a" * 64,
        Path("v"),
        "b" * 64,
        "run",
        collect=facts,
        verify=lambda *a: next(values),
        launch=lambda *a: calls.append("launch"),
        attempt=tmp_path / "fixed",
    )
    assert result["consumed"] is False and calls == [] and "changed" in result["error"]


def test_override_dependencies_must_be_complete(tmp_path):
    from tools.benchmark import native_offset_once as once

    with pytest.raises(ValueError):
        once.execute_once(Path("r"), "a" * 64, Path("v"), "b" * 64, "build", collect=facts, attempt=tmp_path)


def fixture_build(tmp_path):
    from tools.benchmark.native_offset_build_receipt import file_pin

    build = tmp_path / "build"
    build.mkdir()
    source = tmp_path / "openvins_online_probe_v2.cpp"
    source.write_text("modeled source")
    compiler = tmp_path / "g++"
    compiler.write_bytes(b"modeled compiler, never executed")
    header = tmp_path / "header.h"
    header.write_text("modeled header")
    library = tmp_path / "library.so"
    library.write_text("modeled library")
    (build / "CMakeFiles/openvins_offset_reset_v2.dir").mkdir(parents=True)
    (build / "CMakeFiles/openvins_offset_reset_v2.dir/probe.o").write_bytes(b"modeled object, never executed")
    target = build / "openvins_offset_reset_v2"
    target.write_bytes(b"\x7fELF" + b"\0" * 60)
    (build / "CMakeCache.txt").write_text(
        "CMAKE_BUILD_TYPE:STRING=Release\nCMAKE_CXX_COMPILER:FILEPATH=" + compiler.as_posix() + "\n"
    )
    (build / "compile_commands.json").write_text(
        json.dumps(
            [
                dict(
                    directory=str(build),
                    file=source.as_posix(),
                    arguments=[
                        compiler.as_posix(),
                        "-std=c++17",
                        "-O2",
                        "-MD",
                        "-c",
                        source.as_posix(),
                        "-o",
                        "CMakeFiles/openvins_offset_reset_v2.dir/probe.o",
                    ],
                )
            ]
        )
    )
    (build / "CMakeFiles/openvins_offset_reset_v2.dir/probe.o.d").write_text(
        "probe.o: " + source.as_posix() + " " + header.as_posix() + "\n"
    )
    (build / "CMakeFiles/openvins_offset_reset_v2.dir/link.txt").write_text(
        compiler.as_posix()
        + " CMakeFiles/openvins_offset_reset_v2.dir/probe.o "
        + library.as_posix()
        + " -o openvins_offset_reset_v2\n"
    )
    (build / "cmake-trace.jsonl").write_text(json.dumps(dict(file=header.as_posix(), cmd="set", args=[])) + "\n")
    request = dict(
        bindings=dict(exclusive_build_dir=str(build), pinned_gxx=compiler.as_posix()),
        input_pins={p.as_posix(): file_pin(p) for p in (source, compiler, header, library)},
        source=source.as_posix(),
    )
    steps = [dict(name=n, exit=0, command=[n], cleanup=dict(exit=0)) for n in ("configure", "build")]
    return request, build, steps, header, target


def test_receipt_keeps_success_separate_from_native_qualification(tmp_path):
    from tools.benchmark.native_offset_build_receipt import produce

    request, build, steps, _, target = fixture_build(tmp_path)
    result = produce(request, build, steps)
    assert result["complete"] is True and result["native_qualified"] is False
    assert result["binary"]["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert (build / "build-receipt.json").is_file()
    assert len(result["depfiles"]) == 1


@pytest.mark.parametrize("fault", ["failed", "missing", "drift", "unknown-header", "std", "cleanup", "trace", "link"])
def test_receipt_refuses_partial_or_unbound_build(tmp_path, fault):
    from tools.benchmark.native_offset_build_receipt import produce

    request, build, steps, header, target = fixture_build(tmp_path)
    if fault == "failed":
        steps[1]["exit"] = 2
    if fault == "missing":
        target.unlink()
    if fault == "drift":
        header.write_text("changed")
    if fault == "unknown-header":
        request["input_pins"].pop(header.as_posix())
    if fault == "std":
        path = build / "compile_commands.json"
        path.write_text(path.read_text().replace("c++17", "c++14"))
    if fault == "cleanup":
        steps[1]["cleanup"]["exit"] = None
    if fault == "trace":
        (build / "cmake-trace.jsonl").unlink()
    if fault == "link":
        (build / "CMakeFiles/openvins_offset_reset_v2.dir/link.txt").unlink()
    result = produce(request, build, steps)
    assert result["complete"] is False and result["errors"] and result["native_qualified"] is False
    assert (build / "build-receipt.json").is_file()


def test_fixed_commands_cannot_select_legacy_binary_or_extra_target(tmp_path):
    from tools.benchmark.native_offset_once import build_commands

    b = {
        key: str(tmp_path / key)
        for key in (
            "pinned_cmake",
            "deployed_repo",
            "exclusive_build_dir",
            "pinned_gxx",
            "pinned_make",
            "toolchain_file",
            "upstream_source_tree",
            "openvins_library_dir",
            "openvins_library_file",
            "eigen_config_dir",
            "opencv4_config_dir",
            "boost_config_dir",
            "ceres_config_dir",
        )
    }
    configure, build = build_commands(b)
    assert build == [
        b["pinned_cmake"],
        "--build",
        b["exclusive_build_dir"],
        "--target",
        "openvins_offset_reset_v2",
        "--parallel",
        "1",
    ]
    assert "-DCMAKE_CXX_FLAGS_RELEASE=-O2" in configure and "--trace-format=json-v1" in configure


@pytest.mark.parametrize("stage,tasks,memory", [("build", "64", 1024**3), ("run", "256", 4 * 1024**3)])
def test_scope_budget_matches_original_and_unknown_identity_refuses(stage, tasks, memory):
    from tools.benchmark.native_offset_once_scope import verify_scope

    unit = "fly-offset-" + "a" * 24 + ".scope"
    group = "/user.slice/" + unit
    limits = {"memory.max": str(memory), "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": tasks}
    props = dict(ControlGroup=group, InvocationID="owned")
    verify_scope(unit, group, limits, props, stage)
    with pytest.raises(ValueError):
        verify_scope(unit, group, dict(limits, **{"memory.swap.max": "1"}), props, stage)
    with pytest.raises(ValueError):
        verify_scope(unit, group, limits, dict(props, InvocationID=""), stage)


def test_unknown_scope_is_never_stopped(tmp_path, monkeypatch):
    from tools.benchmark import native_offset_once_scope as scope

    calls = []

    def query(*a, **k):
        calls.append(a)
        return subprocess.CompletedProcess(a, 0, b"InvocationID=other\nControlGroup=/user/fly-offset-a.scope\n", b"")

    monkeypatch.setattr(scope, "wsl", query)
    with pytest.raises(RuntimeError, match="unknown scope"):
        scope.stop_scope(
            tmp_path,
            "fly-offset-a.scope",
            dict(
                cgroup="/user/fly-offset-a.scope", systemd_properties="InvocationID=own\nControlGroup=/user/fly-offset-a.scope\n"
            ),
        )
    assert len(calls) == 1 and not any("stop" in c for c in calls)


def request_fixture(tmp_path, monkeypatch):
    from tools.benchmark import native_offset_once as once
    from tools.benchmark.native_offset_build_receipt import file_pin

    monkeypatch.setattr(once, "ROOT", tmp_path)
    monkeypatch.setattr(once, "ATTEMPT", tmp_path / "results/native-offset-once-attempt-v1")
    # Windows fixture models the external 143-file receipt boundary, not a Linux build tree.
    monkeypatch.setattr(once, "verify_upstream", lambda *a: None)
    source = {}
    for name in (*once.SOURCE_NAMES, "native_offset_reset_v2/CMakeLists.txt"):
        p = tmp_path / "tools/benchmark" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# modeled input\n")
        source[str(p)] = file_pin(p)
    b = {key: str(tmp_path / key) for key in once.BUILD_KEYS}
    b.update(
        deployed_repo=str(tmp_path),
        capture_script=str(tmp_path / "tools/benchmark/capture_disarmed_sensors.py"),
        exclusive_build_dir=str(once.ATTEMPT / "build/artifacts"),
    )
    dirs = (
        "deployed_repo",
        "upstream_source_tree",
        "openvins_library_dir",
        "eigen_config_dir",
        "opencv4_config_dir",
        "boost_config_dir",
        "ceres_config_dir",
        "exclusive_build_dir",
    )
    for key, path in b.items():
        if key not in dirs and not Path(path).exists():
            Path(path).write_text("{}")
    Path(b["current_linux_source_manifest"]).write_text(json.dumps(dict(schema="native-offset-current-source-v1", files=source)))
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
    Path(b["library_source_build_receipt"]).write_text(
        json.dumps(
            dict(
                schema="openvins-no-ros-current-build-v1",
                upstream_commit=once.UPSTREAM,
                no_ros=True,
                opencv_major=4,
                abi="modeled-not-proven",
                library=file_pin(b["openvins_library_file"]),
                source_pins=source,
            )
        )
    )
    pins = dict(source)
    for key, path in b.items():
        if key not in dirs:
            pins[path] = file_pin(path)
    tools = []
    for name in ("env", "time", "timeout", "systemd-run", "systemctl"):
        p = tmp_path / name
        p.write_text("inert scope tool")
        tools.append(str(p))
        pins[str(p)] = file_pin(p)
    monkeypatch.setattr(once, "SCOPE_TOOLS", tuple(tools))
    request = dict(
        schema="native-offset-once-request-v1",
        stage="build",
        target=once.TARGET,
        upstream_commit=once.UPSTREAM,
        bindings=b,
        input_pins=pins,
        build_environment={"HOME": "/home/test", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    path = tmp_path / "request.json"
    review = tmp_path / "review.json"

    def save():
        path.write_text(json.dumps(request))
        sha = file_pin(path)["sha256"]
        review.write_text(
            json.dumps(
                dict(
                    schema="native-offset-once-admission-v1",
                    decision="allow-once",
                    stage=request["stage"],
                    request_sha256=sha,
                    covers=once.COVERS,
                    created_unix=100,
                    expires_unix=400,
                )
            )
        )
        return path, sha, review, file_pin(review)["sha256"], "build"

    monkeypatch.setattr(once.time, "time", lambda: 101)
    return once, request, save


def test_success_receipt_does_not_release_run_after_failed_scope(tmp_path, monkeypatch):
    once, request, save = request_fixture(tmp_path, monkeypatch)
    from tools.benchmark.native_offset_build_receipt import file_pin

    build = Path(request["bindings"]["exclusive_build_dir"])
    build.mkdir(parents=True)
    binary = build / once.TARGET
    binary.write_bytes(b"\x7fELF" + b"modeled bytes")
    receipt = build / "build-receipt.json"
    receipt.write_text(
        json.dumps(dict(complete=True, native_qualified=False, binary=file_pin(binary), input_pins=dict(request["input_pins"])))
    )
    completion = once.ATTEMPT / "build/completion.json"
    completion.write_text(json.dumps(dict(consumed=True, error=None, launch=dict(exit=2, owned_group_released=True))))
    inside = once.ATTEMPT / "build/inside-completion.json"
    inside.write_text(json.dumps(dict(exit=0, errors=[], elapsed_s=1)))
    for path in (completion, inside):
        request["input_pins"][str(path)] = file_pin(path)
    request["build_receipt"] = file_pin(receipt)
    request["stage"] = "run"
    args = list(save())
    args[-1] = "run"
    with pytest.raises(ValueError, match="build stage failed"):
        once.verify_request(*args)


def test_current_build_selection_is_bound_without_dispatch(tmp_path, monkeypatch):
    once, request, save = request_fixture(tmp_path, monkeypatch)
    result = once.verify_request(*save())
    assert result["command"][1][-3:] == ["openvins_offset_reset_v2", "--parallel", "1"]
    assert result["qualification"] is False


def test_real_selection_survives_json_boundary(tmp_path, monkeypatch):
    once, _, save = request_fixture(tmp_path, monkeypatch)
    selection = once.verify_request(*save())
    assert selection == json.loads(json.dumps(selection))


def test_request_replaced_between_pin_and_parse_is_refused(tmp_path, monkeypatch):
    once, request, save = request_fixture(tmp_path, monkeypatch)
    args = save()
    original = once.read_json

    def replaced(path, *a, **kwargs):
        if Path(path) == args[0]:
            Path(path).write_text(json.dumps(dict(request, comment="concurrent replacement")))
        return original(path, *a, **kwargs)

    monkeypatch.setattr(once, "read_json", replaced)
    with pytest.raises(ValueError):
        once.verify_request(*args)


def test_redirected_once_root_is_refused_before_observation(tmp_path, monkeypatch):
    from tools.benchmark import native_offset_once as once

    root = tmp_path / "fixed"
    redirect = tmp_path / "other"
    original = Path.resolve
    calls = []

    def resolve(path, *a, **kwargs):
        return redirect if path == root else original(path, *a, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="redirect"):
        once.execute_once(
            Path("r"),
            "a" * 64,
            Path("v"),
            "b" * 64,
            "build",
            collect=lambda: calls.append("query") or facts(),
            verify=lambda *a: {},
            launch=lambda *a: None,
            attempt=root,
        )
    assert calls == [] and not redirect.exists()


def test_unclaimed_scope_refuses_before_linux_queries(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from tools.benchmark import native_offset_once_scope as scope

    monkeypatch.setitem(sys.modules, "resource", SimpleNamespace())

    def forbidden(*a, **k):
        raise AssertionError("unclaimed entry queried Linux")

    monkeypatch.setattr(Path, "read_text", forbidden)
    with pytest.raises(ValueError, match="claim"):
        scope.run_inside(dict(stage="build", output=str(tmp_path / "elsewhere"), unit="fly-offset-" + "a" * 24 + ".scope"))


def test_controls_share_outer_deadline_and_reserve_cleanup(monkeypatch):
    from tools.benchmark import native_offset_once_scope as scope

    clock = [0]
    calls = []
    monkeypatch.setattr(scope.time, "monotonic", lambda: clock[0])

    def slow(*a, **k):
        calls.append(k["timeout"])
        clock[0] += 9
        return subprocess.CompletedProcess(a, 0, b"", b"")

    monkeypatch.setattr(scope, "wsl", slow)
    control = scope.DeadlineControl(20)
    control("show")
    with pytest.raises(TimeoutError):
        control("stop")
    assert len(calls) == 1 and calls[0] <= 4 and clock[0] <= 20


@pytest.mark.parametrize("suffix", [" ../extra.a", " -Wl,@../extra.rsp", " -Wl,-T,../extra.ld"])
def test_explicit_unpinned_link_inputs_refuse_receipt(tmp_path, suffix):
    from tools.benchmark.native_offset_build_receipt import produce

    request, build, steps, _, _ = fixture_build(tmp_path)
    for name in ("extra.a", "extra.rsp", "extra.ld"):
        (tmp_path / name).write_text("undeclared input")
    link = build / "CMakeFiles/openvins_offset_reset_v2.dir/link.txt"
    link.write_text(link.read_text() + suffix)
    result = produce(request, build, steps)
    assert result["complete"] is False and result["errors"]


def test_generated_cmake_module_and_response_file_are_retained(tmp_path):
    from tools.benchmark.native_offset_build_receipt import produce

    request, build, steps, _, _ = fixture_build(tmp_path)
    module = build / "CMakeFiles/generated-compiler.cmake"
    module.write_text("# modeled generated compiler selection")
    with (build / "cmake-trace.jsonl").open("a") as stream:
        stream.write(json.dumps(dict(file=module.as_posix(), cmd="set", args=[])) + "\n")
    link = build / "CMakeFiles/openvins_offset_reset_v2.dir/link.txt"
    tokens = link.read_text().split()
    response = build / "link.rsp"
    response.write_text(" ".join(tokens[1:]))
    link.write_text(tokens[0] + " @" + response.as_posix())
    result = produce(request, build, steps)
    assert result["complete"] is True
    assert "link.rsp" in result["artifacts"]
    assert "CMakeFiles/generated-compiler.cmake" in result["artifacts"]


@pytest.mark.parametrize("configure_exit", [0, 2])
@pytest.mark.parametrize("resource_fault", ["none", "oom", "timeout"])
def test_production_scoped_build_retains_steps_and_never_falls_through(tmp_path, monkeypatch, configure_exit, resource_fault):
    import sys
    from types import SimpleNamespace

    from tools.benchmark import native_offset_once_scope as scope

    request, template, _, _, _ = fixture_build(tmp_path)
    build = tmp_path / "actual-artifacts"
    request["bindings"]["exclusive_build_dir"] = str(build)
    commands = [["inert-cmake", "configure"], ["inert-cmake", "--build"]]
    selected = dict(request=request, source=request["source"], command=commands, environment={"PATH": "/usr/bin:/bin"})
    monkeypatch.setattr(scope, "verify_request", lambda *a, **k: selected)
    monkeypatch.setattr(scope, "require_consumed_claim", lambda *a: None, raising=False)
    monkeypatch.setattr(scope, "manager_environment", lambda: {})
    monkeypatch.setitem(sys.modules, "resource", SimpleNamespace(RLIMIT_FSIZE=1, setrlimit=lambda *a: None))
    unit = "fly-offset-" + "a" * 24 + ".scope"
    group = "/user.slice/" + unit
    original = Path.read_text

    def read(path, *a, **k):
        spelling = path.as_posix()
        if spelling == "/proc/self/cgroup":
            return "0::" + group + "\n"
        if spelling.startswith("/sys/fs/cgroup"):
            return {
                "memory.max": str(1024**3),
                "memory.swap.max": "0",
                "cpu.max": "100000 100000",
                "pids.max": "64",
                "memory.events": ("oom 1\noom_kill 0\n" if resource_fault == "oom" else "oom 0\noom_kill 0\n"),
                "memory.peak": "1024",
            }[path.name]
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="InvocationID=owned\nControlGroup=" + group + "\n")
    )
    launched = []
    clock = [0]
    monkeypatch.setattr(scope.time, "monotonic", lambda: clock[0])

    class Process:
        pid = 42

        def __init__(self, command, **kwargs):
            launched.append(command)
            if len(launched) == 1:
                for path in template.rglob("*"):
                    if path.is_file():
                        target = build / path.relative_to(template)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        raw = (
                            path.read_bytes()
                            .replace(str(template).encode(), str(build).encode())
                            .replace(template.as_posix().encode(), build.as_posix().encode())
                        )
                        target.write_bytes(raw)
                entries = json.loads((build / "compile_commands.json").read_text())
                entries[0]["directory"] = str(build)
                (build / "compile_commands.json").write_text(json.dumps(entries))

        def wait(self, **kwargs):
            if resource_fault == "timeout":
                clock[0] = 301
            return configure_exit if len(launched) == 1 else 0

        def poll(self):
            return configure_exit if len(launched) == 1 else 0

    monkeypatch.setattr(subprocess, "Popen", Process)
    output = tmp_path / "scope"
    output.mkdir()
    profile = dict(
        output=str(output),
        unit=unit,
        stage="build",
        request="inert",
        sha256="a" * 64,
        review="inert",
        review_sha256="b" * 64,
        verified=selected,
    )
    code = scope.run_inside(profile)
    receipt = json.loads((build / "build-receipt.json").read_text())
    if configure_exit == 0 and resource_fault == "none":
        assert code == 0 and len(launched) == 2 and receipt["complete"] is True
    else:
        assert code == 2 and receipt["complete"] is False
        if configure_exit != 0 or resource_fault == "timeout":
            assert len(launched) == 1
    assert (output / "configure.return.json").is_file()
    assert receipt["outputs_present"] or receipt.get("inventory_skipped")
    assert receipt["native_qualified"] is False


@pytest.mark.parametrize("fault", ["missing-tool", "missing-source", "null-binding", "old-target", "review", "output"])
def test_real_request_gate_refuses_missing_current_inputs(tmp_path, monkeypatch, fault):
    once, request, save = request_fixture(tmp_path, monkeypatch)
    if fault == "missing-tool":
        request["input_pins"].pop(request["bindings"]["pinned_gxx"])
    if fault == "missing-source":
        request["input_pins"].pop(str(tmp_path / "tools/benchmark/native_offset_once.py"))
    if fault == "null-binding":
        request["bindings"]["pinned_cmake"] = None
    if fault == "old-target":
        request["target"] = "openvins_online_probe"
    if fault == "output":
        Path(request["bindings"]["exclusive_build_dir"]).mkdir(parents=True)
    args = save()
    if fault == "review":
        monkeypatch.setattr(once.time, "time", lambda: 401)
    with pytest.raises((ValueError, FileExistsError)):
        once.verify_request(*args)


def test_real_fixed_claim_matches_and_is_exclusive(tmp_path, monkeypatch):
    from tools.benchmark import native_offset_once as once
    from tools.benchmark import native_offset_once_scope as scope

    root = tmp_path / "fixed"
    output = root / "build"
    output.mkdir(parents=True)
    monkeypatch.setattr(once, "ATTEMPT", root)
    profile = dict(
        output=str(output),
        stage="build",
        unit="fly-offset-" + "a" * 24 + ".scope",
        sha256="a" * 64,
        review_sha256="b" * 64,
        verified={"selection": "modeled"},
    )
    claim = dict(
        stage="build",
        unit=profile["unit"],
        request_sha256=profile["sha256"],
        review_sha256=profile["review_sha256"],
        state="CONSUMED_DISPATCH_BOUNDARY",
    )
    (output / "consumed.json").write_text(json.dumps(claim))
    for name in ("firstfacts.json", "secondfacts.json"):
        (output / name).write_text(json.dumps(dict(facts=facts(), admitted=True)))
    for name in ("verified-first.json", "verified-second.json"):
        (output / name).write_text(json.dumps(profile["verified"]))
    scope.require_consumed_claim(profile)
    with pytest.raises(FileExistsError):
        scope.require_consumed_claim(profile)
    (output / "completion.json").write_text("{}")
    with pytest.raises(ValueError, match="terminal"):
        scope.require_consumed_claim(profile)


def test_launcher_cleanup_cannot_wait_past_remaining_outer_budget(tmp_path, monkeypatch):
    from tools.benchmark import native_offset_once_scope as scope

    clock = [0]
    waits = []
    kills = []
    monkeypatch.setattr(scope.time, "monotonic", lambda: clock[0])

    class Process:
        pid = 42

        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            kills.append(True)

        def wait(self, timeout):
            waits.append(timeout)
            clock[0] += timeout
            raise subprocess.TimeoutExpired("inert", timeout)

    result = scope.finish_launcher(tmp_path, Process(), 3)
    assert clock[0] == 3 and waits == [3] and kills == [True] and result["exit_code"] is None and result["cleanup_error"]


def test_pinned_relative_script_is_consumed_and_its_bytes_retained(tmp_path):
    from tools.benchmark.native_offset_build_receipt import file_pin, produce

    request, build, steps, _, _ = fixture_build(tmp_path)
    script = tmp_path / "layout.ld"
    script.write_bytes(b"modeled linker script, not executed")
    request["input_pins"][str(script)] = file_pin(script)
    link = build / "CMakeFiles/openvins_offset_reset_v2.dir/link.txt"
    link.write_text(link.read_text() + " -Wl,-T,../layout.ld")
    result = produce(request, build, steps)
    assert result["complete"] is True
    assert bytes.fromhex(result["explicit_text_inputs"][str(script.resolve())]["raw_hex"]) == script.read_bytes()
