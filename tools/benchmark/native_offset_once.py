"""Fixed v2 adapter build/capture coordinator. Importing this module never dispatches."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from tools.benchmark.native_offset_build_receipt import file_pin, read_json, verify_pins, write
from tools.benchmark.native_offset_fresh_build import LIBRARY, PROFILE

ROOT = Path(__file__).resolve().parents[2]
ATTEMPT = ROOT / "results/native-offset-once-attempt-v1"
TARGET = "openvins_offset_reset_v2"
UPSTREAM = "69488123ed9362dd44b6f28e7f4680abbff1442b"
SOURCE_NAMES = (
    "native_offset_once.py",
    "native_offset_once_scope.py",
    "native_offset_build_receipt.py",
    "native_offset_fresh_build.py",
    "native_offset_fresh_receipt.py",
    "openvins_online_probe_v2.cpp",
    "openvins_fast_probe_v2.h",
    "exclusive_probe_output.h",
    "offset_reset_native_source.py",
    "capture_disarmed_sensors.py",
    "capture_contract.py",
)
BUILD_KEYS = (
    "deployed_repo",
    "upstream_source_tree",
    "toolchain_file",
    "toolchain_receipt",
    "pinned_cmake",
    "pinned_gxx",
    "pinned_make",
    "eigen_config_dir",
    "opencv4_config_dir",
    "boost_config_dir",
    "ceres_config_dir",
    "header_package_manifest",
    "current_linux_source_manifest",
    "pinned_python",
    "capture_script",
    "exclusive_build_dir",
)
RUN_PATHS = {
    "shadow_config": "estimator_config",
    "managed_source_config": "managed_source_config",
    "execution_contract": "execution_contract",
    "runtime_binding": "runtime_binding",
    "wire_config": "wire_config",
    "reference_module": "reference_module",
    "agent_runtime_config": "agent_runtime_config",
    "trajectory_gauge_policy": "trajectory_gauge_policy",
}
COVERS = ["current-source", "tool-library-closure", "recipe", "budget", "stops", "once-cleanup", "prefeed"]
SCOPE_TOOLS = ("/usr/bin/env", "/usr/bin/time", "/usr/bin/timeout", "/usr/bin/systemd-run", "/usr/bin/systemctl")
UPSTREAM_MANIFEST_SHA = "19b343211b5ae6b25d9c565095e812f32a265c32997b27100e7eb6bbd3a0ec7f"


def verify_upstream(b, pins):
    path = ROOT / "results/native-offset-run-plan-20261018/upstream-build-source-manifest.json"
    if str(path) not in pins or pins[str(path)]["sha256"] != UPSTREAM_MANIFEST_SHA:
        raise ValueError("frozen upstream build subtree manifest not pinned")
    manifest = read_json(path, expected=pins[str(path)])
    if manifest.get("commit") != UPSTREAM or len(manifest.get("files", {})) != 143:
        raise ValueError("fixed upstream manifest differs")
    for name, expected in manifest["files"].items():
        current = str(Path(b["upstream_source_tree"]) / name)
        record = pins.get(current)
        if not record or record["sha256"] != expected["sha256"] or record["bytes"] != expected["bytes"]:
            raise ValueError("current fixed upstream source binding missing: " + current)


def guard_attempt(path):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ValueError("redirected once ancestor; no observation/dispatch")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or getattr(ancestor, "is_junction", lambda: False)():
            raise ValueError("redirected once ancestor; no observation/dispatch")


def build_commands(b):
    if any(key in b for key in ("openvins_library_file", "openvins_library_dir", "library_source_build_receipt")):
        raise ValueError("existing library bindings forbidden for fresh-source build")
    configure = [
        b["pinned_cmake"],
        "-S",
        b["deployed_repo"] + "/tools/benchmark/native_offset_reset_v2",
        "-B",
        b["exclusive_build_dir"],
        "-G",
        "Unix Makefiles",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_CXX_COMPILER=" + b["pinned_gxx"],
        "-DCMAKE_MAKE_PROGRAM=" + b["pinned_make"],
        "-DCMAKE_CXX_FLAGS_RELEASE=-O2",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        "-DCMAKE_TOOLCHAIN_FILE=" + b["toolchain_file"],
        "-DOPENVINS_SOURCE_DIR=" + b["upstream_source_tree"],
        "-DOPENVINS_FIXED_SOURCES=" + b["exclusive_build_dir"] + "/openvins-fixed-sources.cmake",
        "-DEigen3_DIR=" + b["eigen_config_dir"],
        "-DOpenCV_DIR=" + b["opencv4_config_dir"],
        "-DBoost_DIR=" + b["boost_config_dir"],
        "-DCeres_DIR=" + b["ceres_config_dir"],
        "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
        "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF",
        "--trace-expand",
        "--trace-format=json-v1",
        "--trace-redirect=" + b["exclusive_build_dir"] + "/cmake-trace.jsonl",
    ]
    return [
        configure,
        *[
            [b["pinned_cmake"], "--build", b["exclusive_build_dir"], "--target", target, "--parallel", "1"]
            for target in ("ov_msckf_lib", TARGET)
        ],
    ]


def verify_request(request_path, sha, review_path, review_sha, stage, *, require_absent=True):
    if stage not in ("build", "run"):
        raise ValueError("unknown stage")
    if file_pin(request_path)["sha256"] != sha or file_pin(review_path)["sha256"] != review_sha:
        raise ValueError("request/review bytes differ")
    request, review = read_json(request_path, sha=sha), read_json(review_path, sha=review_sha)
    now = time.time()
    if (
        review.get("schema") != "native-offset-fresh-source-admission-v1"
        or review.get("decision") != "allow-once"
        or review.get("request_sha256") != sha
        or review.get("stage") != stage
        or review.get("covers") != COVERS
        or type(review.get("created_unix")) not in (int, float)
        or type(review.get("expires_unix")) not in (int, float)
        or not review["created_unix"] <= now < review["expires_unix"] <= review["created_unix"] + 300
    ):
        raise ValueError("missing applicable fresh SHA-bound once review; document is not authentication")
    if (
        request.get("schema") != "native-offset-fresh-source-request-v1"
        or request.get("build_profile") != PROFILE
        or request.get("target") != TARGET
        or request.get("upstream_commit") != UPSTREAM
        or request.get("stage") != stage
    ):
        raise ValueError("new fixed target request required")
    pins = verify_pins(request["input_pins"])
    b = request["bindings"]
    # Reject legacy input libraries before selecting/pinning any new build output.
    build_commands(b)
    guard_attempt(ATTEMPT)

    def bound(path):
        return read_json(path, expected=pins[str(path)])

    for key in BUILD_KEYS:
        if type(b.get(key)) is not str or not Path(b[key]).is_absolute():
            raise ValueError("missing absolute binding: " + key)
    if (
        Path(b["deployed_repo"]).resolve() != ROOT
        or Path(b["capture_script"]).resolve() != ROOT / "tools/benchmark/capture_disarmed_sensors.py"
    ):
        raise ValueError("deployed production entry differs")
    build = ATTEMPT / "build/artifacts"
    if Path(b["exclusive_build_dir"]) != build:
        raise ValueError("fixed build directory required; no rename retry")
    required = [ROOT / "tools/benchmark" / name for name in SOURCE_NAMES]
    required += [ROOT / "tools/benchmark/native_offset_reset_v2/CMakeLists.txt"]
    required += [
        Path(b[k])
        for k in BUILD_KEYS
        if k
        not in (
            "deployed_repo",
            "upstream_source_tree",
            "eigen_config_dir",
            "opencv4_config_dir",
            "boost_config_dir",
            "ceres_config_dir",
            "exclusive_build_dir",
        )
    ]
    for path in required:
        if str(path) not in pins:
            raise ValueError("required production/tool/receipt input not pinned: " + str(path))
    current = bound(b["current_linux_source_manifest"])
    if (
        current.get("schema") != "native-offset-current-source-v1"
        or not current.get("files")
        or any(pins.get(name) != record for name, record in current["files"].items())
        or any(str(p) not in current["files"] for p in required[: len(SOURCE_NAMES) + 1])
    ):
        raise ValueError("current production source manifest incomplete")
    for name in SCOPE_TOOLS:
        if name not in pins:
            raise ValueError("scope tool not pinned: " + name)
    # These are external current-byte declarations, not a claim of measured provenance/authentication.
    closure = bound(b["header_package_manifest"])
    if closure.get("schema") != "native-offset-build-input-closure-v1" or set(closure.get("groups", {})) != {
        "tools",
        "system_headers",
        "cmake_modules",
        "link_implicit",
        "libraries",
        "packages",
    }:
        raise ValueError("complete named build input groups required")
    for names in closure["groups"].values():
        if type(names) is not list or not names or any(name not in pins for name in names):
            raise ValueError("build closure contains missing/unpinned inputs")
    verify_upstream(b, pins)
    from tools.benchmark.capture_contract import materialize_launch_environment

    environment = materialize_launch_environment(request["build_environment"])
    if set(environment) != {"HOME", "PATH", "LANG"} or environment["PATH"] != "/usr/bin:/bin" or environment["LANG"] != "C.UTF-8":
        raise ValueError("fixed clean build environment required")
    if stage == "build":
        if require_absent and build.exists():
            raise FileExistsError("build output already exists")
        command = build_commands(b)
    else:
        receipt = read_json(build / "build-receipt.json", expected=request.get("build_receipt"))
        if (
            receipt.get("complete") is not True
            or receipt.get("schema") != "native-offset-fresh-source-build-receipt-v1"
            or receipt.get("build_profile") != PROFILE
            or receipt.get("upstream_commit") != UPSTREAM
            or receipt.get("native_qualified") is not False
            or file_pin(build / "build-receipt.json") != request.get("build_receipt")
            or receipt.get("binary") != file_pin(build / TARGET)
            or receipt.get("library") != file_pin(build / LIBRARY)
            or any(pins.get(k) != v for k, v in receipt["input_pins"].items())
        ):
            raise ValueError("current complete bound build receipt required")
        for key in ("elf_recursive_closure",):
            if b.get(key) in pins:
                evidence = bound(b[key])
                if evidence.get("file_pins", {}).get(str(build / LIBRARY)) != receipt["library"]:
                    raise ValueError("new OpenVINS library absent from current runtime closure")
        for path in (ATTEMPT / "build/completion.json", ATTEMPT / "build/inside-completion.json"):
            if str(path) not in pins:
                raise ValueError("missing complete build lifecycle pin")
        completion = bound(ATTEMPT / "build/completion.json")
        inside = bound(ATTEMPT / "build/inside-completion.json")
        if (
            completion.get("consumed") is not True
            or completion.get("error") is not None
            or completion.get("launch", {}).get("exit") != 0
            or completion["launch"].get("owned_group_released") is not True
            or inside.get("exit") != 0
            or inside.get("errors") != []
            or type(inside.get("elapsed_s")) not in (int, float)
            or not 0 <= inside["elapsed_s"] <= 300
        ):
            raise ValueError("build stage failed/incomplete; receipt cannot release run")
        abi_path = b.get("new_library_abi_receipt")
        if abi_path not in pins:
            raise ValueError("current new-library ABI receipt required before run")
        abi = bound(abi_path)
        if (
            abi.get("schema") != "native-offset-new-library-abi-v1"
            or abi.get("abi_verified") is not True
            or abi.get("library") != receipt["library"]
            or abi.get("binary") != receipt["binary"]
            or abi.get("build_receipt") != request["build_receipt"]
            or not abi.get("file_pins")
            or any(pins.get(k) != v for k, v in abi["file_pins"].items())
        ):
            raise ValueError("new-library ABI declaration not bound to current build/runtime inputs")
        from tools.benchmark.capture_contract import declared_command, derive_launch_environment
        from tools.benchmark.capture_disarmed_sensors import parse_capture_args
        from tools.benchmark.offset_reset_native_source import require_prefeed_phases

        argv = ["--output", str(ATTEMPT / "run/capture"), "--shadow-binary", str(build / TARGET)]
        for flag, key in RUN_PATHS.items():
            if b.get(key) not in pins:
                raise ValueError("missing pinned capture input " + key)
            argv += ["--" + flag.replace("_", "-"), b[key]]
        for flag in ("managed_source_sha256", "reference_sha256"):
            argv += ["--" + flag.replace("_", "-"), b[flag]]
        argv += [
            "--online-estimate-feed",
            "--native-estimate-profile",
            "offset-reset-v2",
            "--disarmed-odometry",
            "--consume-disarmed-odometry-evidence",
            "--record-owned-ulog",
            "--logger-diagnostic-profile",
            "disarmed-receipt-v2",
            "--source-fanout-profile",
            "ready-shadow-heartbeat-estimator-v1",
            "--motion-profile",
            "supported-ready-v1",
            "--physics-trace-profile",
            "substep-ready-v1",
        ]
        args = parse_capture_args(argv)
        binding = bound(b["runtime_binding"])
        require_prefeed_phases(binding.get("runtime_maps", {}).get("owned_roles"))
        environment = materialize_launch_environment(derive_launch_environment(binding))
        command = declared_command(args, b["pinned_python"], b["capture_script"], environment)
        from tools.benchmark.managed_capture_source import load_managed_configuration

        artifact, selected = load_managed_configuration(
            args.managed_source_config, args.managed_source_sha256, args.shadow_config, native_profile="offset-reset-v2"
        )
        if type(b.get("signed_measured_offset_ns")) is not int or not b["signed_measured_offset_ns"]:
            raise ValueError("measured nonzero integral-ns offset required")
        # The real calibrated artifact is checked by the production source, never rewritten here.
        if artifact.timeshift_ns != b["signed_measured_offset_ns"] or any(str(p) not in pins for p in selected):
            raise ValueError("measured offset/transitive calibration binding differs")
        for key in ("measured_calibration_noise_receipt", "elf_recursive_closure", "python_sdk_runtime_closure"):
            if b.get(key) not in pins:
                raise ValueError("missing external current receipt " + key)
        measured = bound(b["measured_calibration_noise_receipt"])
        if (
            measured.get("schema") != "native-offset-measured-input-v1"
            or measured.get("managed_source_sha256") != args.managed_source_sha256
            or measured.get("offset_ns") != artifact.timeshift_ns
            or not measured.get("raw_input_pins")
            or measured.get("calibration_measured") is not True
            or measured.get("noise_measured") is not True
            or any(pins.get(k) != v for k, v in measured["raw_input_pins"].items())
        ):
            raise ValueError("measured calibration/noise provenance declaration missing")
        for key, schema in (
            ("elf_recursive_closure", "native-offset-current-elf-closure-v1"),
            ("python_sdk_runtime_closure", "native-offset-current-python-sdk-closure-v1"),
        ):
            evidence = bound(b[key])
            if (
                evidence.get("schema") != schema
                or evidence.get("complete") is not True
                or not evidence.get("file_pins")
                or any(pins.get(k) != v for k, v in evidence["file_pins"].items())
                or evidence.get("binary_sha256") != receipt["binary"]["sha256"]
            ):
                raise ValueError("current runtime closure receipt incomplete")
        if require_absent and args.output.exists():
            raise FileExistsError("capture output already exists")
    verify_pins(pins)
    if file_pin(request_path)["sha256"] != sha or file_pin(review_path)["sha256"] != review_sha:
        raise ValueError("request/review changed before command boundary")
    return dict(
        request=request,
        command=command,
        environment=environment,
        request_sha256=sha,
        review_sha256=review_sha,
        stage=stage,
        source=str(ROOT / "tools/benchmark/openvins_online_probe_v2.cpp"),
        qualification=False,
    )


def _query(command, output, label, timeout=10):
    from tools.benchmark.native_query_process import bounded_run

    result = bounded_run(command, cwd=ROOT, env=os.environ.copy(), timeout=timeout)
    Path(output / label).mkdir()
    (output / label / "stdout").write_bytes(result.stdout)
    (output / label / "stderr").write_bytes(result.stderr)
    write(
        output / label / "return.json",
        dict(
            command=command,
            exit=result.returncode,
            output_limit_exceeded=result.output_limit_exceeded,
            collection_errors=result.collection_errors,
        ),
    )
    if result.returncode or result.output_limit_exceeded or result.collection_errors:
        raise RuntimeError("bounded metadata query refused: " + label)
    return result


def collect_resources(output):
    """Only called by future explicit execution; original dual4GiB gate, no polling loop."""
    import psutil

    from tools.benchmark.run_openvins_dataset_consumer import heavy_process

    started = time.monotonic()
    script = """import pathlib,json,os,hashlib
from tools.benchmark.run_openvins_dataset_consumer import heavy_process
m={a:b for a,b in (x.split(':',1) for x in pathlib.Path('/proc/meminfo').read_text().splitlines())}
r=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name) in (os.getpid(),os.getppid()):continue
 try:
  row=dict(pid=int(p.name),name=(p/'comm').read_text().strip(),cmdline=(p/'cmdline').read_bytes().replace(b'\\0',b' ').decode(errors='replace'))
  r.append(dict(pid=row['pid'],name=row['name'],argv_sha256=hashlib.sha256(row['cmdline'].encode()).hexdigest(),blocked=heavy_process(row)))
 except OSError:pass
print(json.dumps(dict(available=int(m['MemAvailable'].split()[0])*1024,processes=r)))"""
    from tools.benchmark.run_openvins_dataset_consumer import linux

    wsl = json.loads(
        _query(
            [
                "wsl",
                "-d",
                "Ubuntu",
                "--",
                "/usr/bin/env",
                "-i",
                "PATH=/usr/bin:/bin",
                "PYTHONPATH=" + linux(ROOT) + "/src:" + linux(ROOT),
                "/usr/bin/python3",
                "-c",
                script,
            ],
            output,
            "wsl",
        ).stdout
    )
    own = {os.getpid(), *(p.pid for p in psutil.Process().parents())}
    windows = [dict(pid=p.pid, **p.info) for p in psutil.process_iter(["name", "cmdline"]) if p.pid not in own]
    docker = _query(["docker", "ps", "--no-trunc", "--format", "{{json .}}"], output, "docker")

    def identity(p):
        cmd = p["cmdline"] if isinstance(p["cmdline"], str) else " ".join(p["cmdline"] or [])
        return dict(pid=p["pid"], name=p["name"], argv_sha256=hashlib.sha256(cmd.encode()).hexdigest())

    if time.monotonic() - started > 30:
        raise TimeoutError("resource observation deadline")
    return dict(
        windows_available=psutil.virtual_memory().available,
        wsl=dict(available=wsl["available"], processes=wsl["processes"]),
        windows_processes=[identity(p) for p in windows],
        docker_exit=0,
        docker_running=docker.stdout.decode(),
        blocked_processes=[identity(p) for p in windows if heavy_process(p)] + [p for p in wsl["processes"] if p["blocked"]],
    )


def execute_once(request, sha, review, review_sha, stage, *, collect=None, verify=None, launch=None, attempt=None):
    real = collect is None and verify is None and launch is None
    if not real and any(x is None for x in (collect, verify, launch)):
        raise ValueError("all inert boundary dependencies must be supplied together")
    if stage not in ("build", "run"):
        raise ValueError("unknown once stage")
    if real and attempt is not None and Path(attempt).resolve() != ATTEMPT.resolve():
        raise ValueError("fixed once attempt path required")
    root = ATTEMPT if real else Path(attempt)
    try:
        guard_attempt(root)
    except ValueError as primary:
        if real:
            try:
                write(ROOT / "native-offset-once-path-refusal.json", dict(error=repr(primary), stage=stage, consumed=False))
            except Exception as secondary:
                primary.add_note("refusal record: " + repr(secondary))
        raise
    root.mkdir(exist_ok=True)
    guard_attempt(root)
    output = root / stage
    output.mkdir(exist_ok=False)
    guard_attempt(output)  # claim before even the first resource observation
    result = dict(consumed=False, stage=stage, qualification=False, error=None)
    try:
        if real:
            from tools.benchmark.native_offset_once_scope import launch_scope, verify_remote

            verify, launch = verify_remote, launch_scope

            def collect():
                directory = output / ("resources-first" if not (output / "firstfacts.json").exists() else "resources-second")
                directory.mkdir()
                return collect_resources(directory)

        from tools.benchmark.run_calibration_capture import admitted

        first = collect()
        write(output / "firstfacts.json", dict(facts=first, admitted=admitted(first)))
        if not admitted(first):
            result["reason"] = "REFUSED_UNCONSUMED first gate"
            return result
        initial = verify(request, sha, review, review_sha, stage)
        write(output / "verified-first.json", initial)
        final = verify(request, sha, review, review_sha, stage)
        write(output / "verified-second.json", final)
        if final != initial:
            raise ValueError("current selection changed before claim")
        second = collect()
        write(output / "secondfacts.json", dict(facts=second, admitted=admitted(second)))
        if not admitted(second):
            result["reason"] = "REFUSED_UNCONSUMED second gate"
            return result
        unit = "fly-offset-" + secrets.token_hex(12) + ".scope"
        write(
            output / "consumed.json",
            dict(
                stage=stage,
                request_sha256=sha,
                review_sha256=review_sha,
                unit=unit,
                state="CONSUMED_DISPATCH_BOUNDARY",
                qualification=False,
            ),
        )
        result["consumed"] = True
        result["launch"] = launch(output, request, sha, review, review_sha, stage, final, unit)
    except Exception as exc:
        result["error"] = repr(exc)
    finally:
        write(output / "completion.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-once", action="store_true", required=True)
    parser.add_argument("--stage", choices=["build", "run"], required=True)
    for name in ("request", "review"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("sha256", "review-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    result = execute_once(args.request, args.sha256, args.review, args.review_sha256, args.stage)
    print(json.dumps(result, indent=2))
    return 0 if result.get("launch", {}).get("exit") == 0 and result["launch"].get("owned_group_released") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
