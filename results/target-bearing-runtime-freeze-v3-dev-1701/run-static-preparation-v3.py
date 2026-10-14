"""Literal admitted once-only static v3 coordinator. Never executes physical capture."""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

import psutil

from tools.benchmark.run_openvins_dataset_consumer import heavy_process, linux, write

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/target-bearing-runtime-freeze-v3-dev-1701"
FOLDER = OUT / "frozen-study-v3"
LIMITS = {"memory.max": "536870912", "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "64"}
CONTROL = None


def source_snapshot():
    paths = [Path(__file__)]
    for scope in ("src/flydrones", "tools/benchmark", "tools/connectome"):
        paths.extend(p for p in (ROOT / scope).rglob("*.py") if "__pycache__" not in p.parts)
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}


def sdk_environment():
    return dict(
        HOME="/home/yuchen7509",
        PATH="/usr/bin:/bin",
        LANG="C.UTF-8",
        PYTHONPATH=linux(ROOT) + "/src:" + linux(ROOT),
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
    )


def remote(*args, timeout=15):
    return subprocess.run(["wsl", "-d", "Ubuntu", "--", *args], capture_output=True, timeout=timeout)


# Primitive identity observation and admission are defined below.


def verify_preidentity(identity):
    if (
        identity["error"] is not None
        or identity["sources"] != source_snapshot()
        or identity["files_before"] != identity["files_after"]
    ):
        raise ValueError("Linux preidentity/source joins differ")
    control = identity["manager_control_environment"]
    if (
        type(identity.get("uid")) is not int
        or identity["uid"] < 0
        or control != dict(PATH="/usr/bin:/bin", LANG="C.UTF-8", XDG_RUNTIME_DIR="/run/user/" + str(identity["uid"]))
    ):
        raise ValueError("own manager environment incomplete")
    global CONTROL
    CONTROL = control


def manager_call(*args):
    if CONTROL is None:
        raise ValueError("own manager control environment unknown")
    return remote("/usr/bin/env", "-i", *[k + "=" + v for k, v in CONTROL.items()], "/usr/bin/systemctl", "--user", *args)


def stop_if_owned(unit, inside):
    observed = manager_call("show", unit, "--property=InvocationID", "--property=ControlGroup")
    actual = dict(line.split("=", 1) for line in observed.stdout.decode().splitlines() if "=" in line)
    expected = dict(line.split("=", 1) for line in inside["systemd_properties"].splitlines() if "=" in line)
    group = inside["cgroup"]
    owned = (
        observed.returncode == 0
        and re.fullmatch(r"fly-calibration-prepare-[0-9a-f]{24}\.scope", unit)
        and group.endswith("/" + unit)
        and expected.get("InvocationID")
        and actual.get("InvocationID") == expected["InvocationID"]
        and actual.get("ControlGroup") == group
    )
    write(
        OUT / "scope-stop-intent.json",
        dict(ownership_confirmed=bool(owned), observed=actual, expected=expected, escaped_closure="unknown"),
    )
    if not owned:
        raise ValueError("scope ownership unknown; unit stop forbidden")
    stopped = manager_call("stop", unit)
    write(
        OUT / "scope-stop-return.json",
        dict(exit=stopped.returncode, stdout_hex=stopped.stdout.hex(), stderr_hex=stopped.stderr.hex()),
    )
    if stopped.returncode:
        raise ValueError("owned unit stop refused")


def observe_release(unit):
    identity = OUT / "sdk-inside-before.json"
    if not identity.exists():
        return dict(owned_group_released=None, scope_identity="unknown; no unit stop")
    inside = json.loads(identity.read_bytes())
    group = inside["cgroup"]
    if not group.startswith("/") or not group.endswith("/" + unit) or ".." in Path(group).parts:
        raise ValueError("owned cgroup path invalid")
    after = manager_call("show", unit, "--property=LoadState", "--property=ActiveState")
    exists = remote("test", "-d", "/sys/fs/cgroup" + group)
    return dict(
        owned_group_released=exists.returncode == 1 and after.returncode == 0 and b"LoadState=not-found" in after.stdout,
        after_exit=after.returncode,
        after_stdout_hex=after.stdout.hex(),
        after_stderr_hex=after.stderr.hex(),
        group_test_exit=exists.returncode,
    )


def cleanup_child(process):
    row = dict(pid=process.pid, before=process.poll(), escaped_closure="unknown")
    if row["before"] is None:
        try:
            process.terminate()
            row["terminate_sent"] = True
        except OSError as exc:
            row["terminate_error"] = repr(exc)
    try:
        row["exit"] = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            row["kill_sent"] = True
        except OSError as exc:
            row["kill_error"] = repr(exc)
        try:
            row["exit"] = process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            row["error"] = repr(exc)
    return row


def verify_result():
    path = FOLDER / "study.json"
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    argv = [
        "/usr/bin/env",
        "-i",
        *[k + "=" + v for k, v in sdk_environment().items()],
        "/usr/bin/python3",
        "-m",
        "tools.benchmark.calibration_capture_study",
        "--verify-only",
        "--study",
        linux(path),
        "--sha256",
        sha,
    ]
    result = remote(*argv, timeout=30)
    write(
        OUT / "post-study-verification.json",
        dict(argv=argv, exit=result.returncode, stdout_hex=result.stdout.hex(), stderr_hex=result.stderr.hex(), study_sha256=sha),
    )
    if result.returncode:
        raise ValueError("actual v3 final study refused")
    checked = json.loads(result.stdout)
    from tools.benchmark.calibration_capture_contract import scene_record
    from tools.benchmark.calibration_capture_study import SOURCE

    closure = validate_study_inputs(
        json.loads((OUT / "preidentity.json").read_bytes()),
        json.loads((FOLDER / "runtime-binding-v4.json").read_bytes()),
        scene_record(SOURCE),
        json.loads((FOLDER / "sdk/entry-dependencies/entry-bill.json").read_bytes()),
    )
    write(OUT / "actual-study-prepin-closure.json", closure)
    return checked


def admitted(facts):
    return (
        type(facts.get("windows_available")) is int
        and facts["windows_available"] >= 2**30
        and type(facts.get("wsl", {}).get("available")) is int
        and facts["wsl"]["available"] >= 2**30
        and facts.get("blocked_processes") == []
        and type(facts.get("docker_exit")) is int
        and facts["docker_exit"] == 0
        and type(facts.get("docker_running")) is str
        and not facts["docker_running"].strip()
        and not any(
            p.get("name", "").lower().removesuffix(".exe") in {"microxrceagent", "kalibr", "kalibr_calibrate_imu_camera"}
            for p in facts.get("windows_processes", []) + facts.get("wsl", {}).get("processes", [])
        )
    )


def collect(name):
    first = admission()
    private = OUT / (name + "-private.json")
    write(private, dict(facts=first, static_admitted=admitted(first)))
    public = dict(
        windows_available=first["windows_available"],
        wsl_available=first["wsl"]["available"],
        blocked_process_count=len(first["blocked_processes"]),
        docker_exit=first["docker_exit"],
        docker_running_empty=not first["docker_running"].strip(),
        static_admitted=admitted(first),
        reserve_each_bytes=2**30,
        private_sha256=hashlib.sha256(private.read_bytes()).hexdigest(),
        private_bytes=private.stat().st_size,
    )
    write(OUT / (name + ".json"), public)
    return public["static_admitted"]


def execute_once():
    if OUT != ROOT / "results/target-bearing-runtime-freeze-v3-dev-1701" or FOLDER != OUT / "frozen-study-v3":
        raise ValueError("literal static v3 path required")
    if FOLDER.exists() or any(
        (OUT / p).exists() for p in ("attempt.json", "first-admission.json", "first-admission-private.json", "completion.json")
    ):
        raise FileExistsError("static v3 already claimed/observed; no replay or gate polling")
    OUT.mkdir(parents=True, exist_ok=True)
    before = source_snapshot()
    write(OUT / "source-before.json", before)
    if not collect("first-admission"):
        return dict(attempt_consumed=False, reason="first resource refusal")
    identity = preidentity()
    verify_preidentity(identity)
    unit = "fly-calibration-prepare-" + secrets.token_hex(12) + ".scope"
    absent = manager_call("show", unit, "--property=LoadState")
    write(
        OUT / "scope-absence.json",
        dict(unit=unit, exit=absent.returncode, stdout_hex=absent.stdout.hex(), stderr_hex=absent.stderr.hex()),
    )
    if b"LoadState=not-found" not in absent.stdout:
        raise ValueError("new unit absence unknown")
    if not collect("second-admission"):
        return dict(attempt_consumed=False, reason="second resource refusal")
    if source_snapshot() != before or FOLDER.exists():
        raise ValueError("source/study changed before claim")
    command = [
        "wsl",
        "-d",
        "Ubuntu",
        "--",
        "/usr/bin/env",
        "-i",
        *[k + "=" + v for k, v in CONTROL.items()],
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--unit=" + unit.removesuffix(".scope"),
        "--property=MemoryMax=536870912",
        "--property=MemorySwapMax=0",
        "--property=CPUQuota=100%",
        "--property=TasksMax=64",
        "--property=RuntimeMaxSec=210",
        "--property=TimeoutStopSec=10s",
        "/usr/bin/env",
        "-i",
        *[k + "=" + v for k, v in sdk_environment().items()],
        "/usr/bin/time",
        "-v",
        "-o",
        linux(OUT / "resources.txt"),
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=10s",
        "180s",
        "/usr/bin/python3",
        "-B",
        "-m",
        "tools.benchmark.prepare_calibration_capture_v3",
        "--prepare-only",
        "--unit",
        unit,
    ]
    start = time.monotonic_ns()
    write(
        OUT / "attempt.json",
        dict(
            unit=unit,
            command=command,
            attempt_consumed=True,
            start_monotonic_ns=start,
            start_utc=datetime.datetime.now(datetime.UTC).isoformat(),
            physical_attempt=False,
        ),
    )
    process = None
    result = dict(
        attempt_consumed=True, exit=None, error=None, owned_group_released=None, escaped_closure="unknown", physical_attempt=False
    )
    try:
        with (OUT / "launcher.stdout").open("xb") as stdout, (OUT / "launcher.stderr").open("xb") as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            write(OUT / "launcher.json", dict(pid=process.pid, command=command))
            result["exit"] = process.wait(timeout=240)
        if result["exit"] == 0:
            result["verified_study"] = verify_result()
    except BaseException as exc:
        result["error"] = repr(exc)
    finally:
        try:
            result.update(observe_release(unit))
            if result["owned_group_released"] is not True and (OUT / "sdk-inside-before.json").exists():
                stop_if_owned(unit, json.loads((OUT / "sdk-inside-before.json").read_bytes()))
                result.update(observe_release(unit))
        except Exception as exc:
            result["scope_cleanup_error"] = repr(exc)
        if process is not None:
            try:
                result["owned_child_cleanup"] = cleanup_child(process)
            except Exception as exc:
                result["child_cleanup_error"] = repr(exc)
        try:
            result["postidentity"] = postidentity()
        except Exception as exc:
            result["postidentity_error"] = repr(exc)
            result["error"] = result["error"] or repr(exc)
        end = time.monotonic_ns()
        result.update(end_monotonic_ns=end, elapsed_ns=end - start, end_utc=datetime.datetime.now(datetime.UTC).isoformat())
        try:
            result["source_after"] = source_snapshot()
            result["source_stable"] = result["source_after"] == before
        except Exception as exc:
            result["source_after_error"] = repr(exc)
        try:
            write(OUT / "completion.json", result)
        except Exception as exc:
            result["completion_writer_error"] = repr(exc)
            result["error"] = result["error"] or repr(exc)
            try:
                write(OUT / "completion-fallback.json", result)
            except Exception as fallback:
                result["fallback_writer_error"] = repr(fallback)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-once", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        result = execute_once()
    except BaseException as exc:
        result = dict(error=repr(exc), attempt_consumed=(OUT / "attempt.json").exists(), physical_attempt=False)
        if not (OUT / "coordinator-failure.json").exists():
            write(OUT / "coordinator-failure.json", result)
    print(json.dumps(result))
    return (
        0
        if result.get("error") is None
        and result.get("exit") == 0
        and result.get("owned_group_released") is True
        and result.get("source_stable") is True
        and result.get("verified_study")
        else 1
    )


execute = execute_once


OBSERVER = ROOT / "tools/benchmark/static_v3_identity.py"
BOOTSTRAP_TOOLS = ["/usr/bin/sha256sum", "/usr/bin/python3", "/usr/bin/env", "/usr/bin/timeout", "/lib64/ld-linux-x86-64.so.2"]
VERSION_TOOLS = [
    "/usr/bin/ldd",
    "/usr/bin/readelf",
    "/usr/bin/python3",
    "/lib64/ld-linux-x86-64.so.2",
    "/usr/bin/systemd-run",
    "/usr/bin/systemctl",
    "/usr/bin/time",
    "/usr/bin/timeout",
    "/usr/bin/env",
    "/usr/bin/dpkg-query",
]


def host_path(path):
    if path.startswith("/mnt/c/"):
        return Path("C:/" + path[7:])
    if not path.startswith("/") or ".." in path.split("/"):
        raise ValueError("absolute Linux path required")
    return Path("//wsl.localhost/Ubuntu" + path)


def host_pin(path):
    selected = host_path(path)
    before = selected.stat()
    digest = hashlib.sha256()
    with selected.open("rb") as f:
        for chunk in iter(lambda: f.read(128 * 1024), b""):
            digest.update(chunk)
    after = selected.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("host file changed while pinning")
    return dict(path=path, sha256=digest.hexdigest(), bytes=after.st_size)


def verify_bootstrap(records):
    for record in records:
        if host_pin(record["path"]) != record:
            raise ValueError("bootstrap current bytes differ")


def observer_arguments(request, output):
    return ["/usr/bin/python3", "-S", linux(OBSERVER), request, output]


def decode_observer(raw):
    if len(raw) > 16 * 1024**2:
        raise ValueError("primitive journal aggregate cap")
    rows = []
    for line in raw.decode("utf8").splitlines():
        try:
            row = ast.literal_eval(line)
        except (ValueError, SyntaxError) as exc:
            raise ValueError("malformed primitive row") from exc
        if type(row) is not dict:
            raise ValueError("primitive row must be dict")
        rows.append(row)
    return rows


def admission():
    # Readonly resource observer has the same audited primitive imports; no JSON on Linux.
    code = """import os,sys
mem={k:v for k,v in (line.split(':',1) for line in open('/proc/meminfo').read().splitlines())}
rows=[]
for n in os.listdir('/proc'):
 if not n.isdigit() or int(n) in (os.getpid(),os.getppid()):continue
 try:rows.append(dict(pid=int(n),name=open('/proc/'+n+'/comm').read().strip(),cmdline=open('/proc/'+n+'/cmdline','rb').read().replace(bytes([0]),b' ').decode(errors='replace')))
 except OSError:pass
print(repr(dict(available=int(mem['MemAvailable'].split()[0])*1024,processes=rows)))
"""
    startup_pins = [host_pin(p) for p in ["/usr/bin/python3", "/lib64/ld-linux-x86-64.so.2"]]
    verify_bootstrap(startup_pins)
    observed = remote("/usr/bin/python3", "-S", "-c", code, timeout=30)
    verify_bootstrap(startup_pins)
    if observed.returncode:
        raise ValueError("primitive admission observer refused")
    data = ast.literal_eval(observed.stdout.decode("utf8"))
    own = {os.getpid(), *(x.pid for x in psutil.Process().parents())}
    windows = [dict(pid=x.pid, **x.info) for x in psutil.process_iter(["name", "cmdline"]) if x.pid not in own]
    blocked = [x for x in data["processes"] + windows if heavy_process(x)]
    docker = subprocess.run(["docker", "ps", "--no-trunc", "--format", "{{json .}}"], capture_output=True, timeout=30)

    def identity(x):
        command = x["cmdline"] if isinstance(x["cmdline"], str) else " ".join(x["cmdline"] or [])
        return dict(pid=x["pid"], name=x["name"], argv_sha256=hashlib.sha256(command.encode()).hexdigest())

    return dict(
        windows_available=psutil.virtual_memory().available,
        wsl=dict(available=data["available"], processes=[identity(x) for x in data["processes"]]),
        windows_processes=[identity(x) for x in windows],
        blocked_processes=[identity(x) for x in blocked],
        docker_exit=docker.returncode,
        docker_running=docker.stdout.decode(),
        admission_bootstrap=startup_pins,
        wsl_stderr_hex=observed.stderr.hex(),
    )


def identity_request():
    from tools.benchmark.agent_capture_runtime import AGENT_SHA256, BUNDLE_SHA256, LIBRARY_SHA256
    from tools.benchmark.calibration_capture_contract import scene_record
    from tools.benchmark.calibration_capture_study import SOURCE
    from tools.benchmark.prepare_calibration_capture import CATALOG

    scene = scene_record(SOURCE)
    folder = ROOT / "results/target-bearing-runtime-freeze-dev-1701/frozen-study-v1"
    config = json.loads((folder / "agent-runtime.json").read_bytes())
    deployment = json.loads((folder / "agent-deployment.json").read_bytes())
    if config["port"] != 18888:
        raise ValueError("Agent port changed")
    expected = {"bin/MicroXRCEAgent": AGENT_SHA256, **{"lib/" + k: v for k, v in LIBRARY_SHA256.items()}}
    members = {r["member"]: r["deployed"] for r in deployment["members"]}
    if set(members) != set(expected) or len(members) != len(deployment["members"]):
        raise ValueError("Agent exact cache members differ")
    if {p.name for p in host_path(config["lib_dir"]).iterdir()} != set(LIBRARY_SHA256):
        raise ValueError("Agent extra/missing library")
    checks = []
    for name, h in expected.items():
        path = config["binary"] if name == "bin/MicroXRCEAgent" else config["lib_dir"] + "/" + name[4:]
        row = host_pin(path)
        if row["sha256"] != h or row["sha256"] != members[name]["sha256"]:
            raise ValueError("Agent pinned bytes differ")
        checks.append(row)
    bundle = host_pin(config["bundle"])
    if bundle["sha256"] != BUNDLE_SHA256 or bundle["sha256"] != deployment["bundle"]["sha256"]:
        raise ValueError("Agent bundle changed")
    checks.append(bundle)
    catalog = json.loads(CATALOG.read_bytes())
    paths = set(VERSION_TOOLS) | {linux(OBSERVER), "/usr/bin/sha256sum"}
    paths.update(linux(ROOT / p) for p in source_snapshot())
    paths.update(linux(Path(scene["path"]) / n) for n in scene["files"])
    paths.update(x["path"] for x in checks)
    paths.update([linux(folder / "agent-runtime.json"), linux(folder / "agent-deployment.json"), linux(CATALOG)])
    for role, values in catalog["inventory"].items():
        if (
            role == "runtime:dependencies"
            or role.startswith("graph:")
            or (
                role.startswith("runtime-root:")
                and not role.startswith("runtime-root:python")
                and role not in {"runtime-root:openvins", "runtime-root:native-reference"}
            )
        ):
            paths.update(values)
    paths.update(["/etc/python3.12/sitecustomize.py", linux(ROOT / "tools/benchmark/native/local_candidates.hh")])
    roots = ["/usr/lib/python3.12", "/etc/python3.12", "/usr/share/doc"]
    roots += [linux(ROOT / p) for p in ["src/flydrones", "tools/benchmark", "tools/connectome"]]
    packages = {}
    for base in ["/usr/lib/python3/dist-packages", "/home/yuchen7509/.local/lib/python3.12/site-packages"]:
        if not host_path(base).is_dir():
            continue
        for entry in host_path(base).iterdir():
            name = entry.name
            if entry.is_file() and (name.endswith(".pth") or name in {"sitecustomize.py", "usercustomize.py"}):
                paths.add(base + "/" + name)
            if name == "__pycache__" and entry.is_dir():
                roots.append(base + "/" + name)
            if name in {"gz", "sdformat14", "numpy", "numpy.libs", "scipy", "scipy.libs", "pymavlink", "pyulog", "google"}:
                if entry.is_dir():
                    roots.append(base + "/" + name)
            if name.startswith(("sdformat14", "gz_")) and entry.is_file() and (name.endswith(".py") or ".so" in name):
                paths.add(base + "/" + name)
            if name.endswith((".dist-info", ".egg-info")) and name.lower().startswith(
                ("numpy-", "scipy-", "pyulog-", "pymavlink-", "protobuf-")
            ):
                roots.append(base + "/" + name)
                meta = entry / "METADATA"
                if not meta.exists():
                    meta = entry / "PKG-INFO"
                text = meta.read_text(encoding="utf8")
                package = next(x[6:] for x in text.splitlines() if x.startswith("Name: "))
                version = next(x[9:] for x in text.splitlines() if x.startswith("Version: "))
                if package in packages:
                    raise ValueError("ambiguous installed package metadata")
                packages[package] = version
    if set(packages) != {"numpy", "scipy", "pyulog", "pymavlink", "protobuf"}:
        raise ValueError("required current package metadata missing")
    for relative in [
        "build/px4_sitl_default/rootfs/gz_env.sh",
        "build/px4_sitl_default/etc/init.d-posix/rcS",
        "src/modules/simulation/gz_bridge/server.config",
        "Tools/simulation/gz/models/x500/model.sdf",
        "Tools/simulation/gz/models/x500_base/model.sdf",
        "LICENSE",
    ]:
        paths.add("/home/yuchen7509/PX4-Autopilot/" + relative)
    paths.add(linux(ROOT / "results/agent-capture-contract-dev-1701/agent-runtime.json"))
    bootstrap = [host_pin(x) for x in [*BOOTSTRAP_TOOLS, linux(OBSERVER)]]
    # Existing static scene and immutable deployment were checked against their hard pins above.
    return dict(
        schema="static-v3-preidentity-request-v1",
        sources=source_snapshot(),
        paths=sorted(paths),
        roots=roots,
        versions=VERSION_TOOLS,
        bootstrap=bootstrap,
        scene=scene,
        agent_files=checks,
        packages=packages,
    )


def validate_identity_rows(rows, request):
    kinds = [r.get("kind") for r in rows]
    if kinds.count("begin") != 1 or kinds.count("terminal") != 1 or kinds[-1] != "terminal":
        raise ValueError("one complete primitive sequence required")
    if any(k not in {"bootstrap", "begin", "file", "version", "terminal", "hash-query"} for k in kinds):
        raise ValueError("unknown primitive row")
    begin = rows[kinds.index("begin")]
    terminal = rows[-1]
    if begin.get("imported_extensions") != [] or terminal.get("imported_extensions") != [] or terminal.get("error") is not None:
        raise ValueError("primitive import policy/terminal refused")
    start, end, elapsed = (begin["start_monotonic_ns"], terminal["end_monotonic_ns"], terminal["elapsed_ns"])
    if any(type(x) is not int or x < 0 for x in [start, end, elapsed]) or end - start != elapsed or end < start:
        raise ValueError("primitive local clock facts differ")
    requested = begin["requested"]
    if (
        not requested
        or len(set(requested)) != len(requested)
        or requested != sorted(requested)
        or len(requested) > 8192
        or not set(request["paths"]).issubset(requested)
    ):
        raise ValueError("primitive exact request membership differs")
    before = {r["file"]["requested"]: r["file"] for r in rows if r.get("kind") == "file" and r["phase"] == "before"}
    if set(before) != set(requested):
        raise ValueError("primitive input pin coverage differs")
    boots = [r["file"] for r in rows if r.get("kind") == "bootstrap"]
    if [r["requested"] for r in boots] != [r["path"] for r in request["bootstrap"]]:
        raise ValueError("primitive bootstrap membership differs")
    for row, expected in zip(boots, request["bootstrap"]):
        if row["sha256"] != expected["sha256"] or row["bytes"] != expected["bytes"] or row != before.get(row["requested"]):
            raise ValueError("primitive bootstrap identity differs")
    versions = [r for r in rows if r.get("kind") == "version"]
    if [r["file"] for r in versions] != request["versions"]:
        raise ValueError("primitive version membership differs")
    for row in [r for r in rows if r.get("kind") in {"version", "hash-query"}]:
        q = row["query"]
        expected_argv = [row["file"], "--version"] if row["kind"] == "version" else None
        if expected_argv is not None:
            if q["argv"] != expected_argv or not (q["stdout_hex"] or q["stderr_hex"]):
                raise ValueError("primitive exact version argv/output differs")
            if row["file_before"] != before.get(row["file"]) or row["file_after"] != row["file_before"]:
                raise ValueError("version tool per-call identity differs")
        elif len(q["argv"]) != 3 or q["argv"][:2] != ["/usr/bin/sha256sum", "--"] or q["argv"][2] not in requested:
            raise ValueError("primitive hash argv differs")
        if q["environment"] != dict(PATH="/usr/bin:/bin", LANG="C.UTF-8") or type(q["pid"]) is not int or q["pid"] <= 0:
            raise ValueError("primitive tool process/environment differs")
        if (
            q["exit"] != 0
            or type(q["exit"]) is not int
            or q["error"] is not None
            or q["reader_complete"] is not True
            or q["cleanup"].get("waited") is not True
        ):
            raise ValueError("primitive tool query refused")
        if q["end_monotonic_ns"] - q["start_monotonic_ns"] != q["elapsed_ns"] or q["elapsed_ns"] < 0:
            raise ValueError("primitive tool clock differs")
        if len(bytes.fromhex(q["stdout_hex"])) > 2 * 1024**2 or len(bytes.fromhex(q["stderr_hex"])) > 2 * 1024**2:
            raise ValueError("primitive tool stream cap exceeded")
    used_hashes = set()

    def link_hash(index, file):
        if index < 0 or rows[index].get("kind") != "hash-query" or index in used_hashes:
            raise ValueError("missing/duplicate raw hash query")
        q = rows[index]["query"]
        data = bytes.fromhex(q["stdout_hex"])
        if (
            q["argv"] != ["/usr/bin/sha256sum", "--", file["requested"]]
            or data != (file["sha256"] + "  " + file["requested"] + "\n").encode()
        ):
            raise ValueError("raw hash query/file join differs")
        used_hashes.add(index)

    for i, row in enumerate(rows):
        if row["kind"] in {"bootstrap", "file"}:
            link_hash(i - 1, row["file"])
        if row["kind"] == "version":
            link_hash(i - 2, row["file_before"])
            link_hash(i - 1, row["file_after"])
            a, b = rows[i - 2]["query"], rows[i - 1]["query"]
            v = row["query"]
            if a["end_monotonic_ns"] > v["start_monotonic_ns"] or v["end_monotonic_ns"] > b["start_monotonic_ns"]:
                raise ValueError("version per-call raw hash ordering differs")
    if used_hashes != {i for i, r in enumerate(rows) if r["kind"] == "hash-query"}:
        raise ValueError("extra unbound raw hash query")
    return begin


def validate_study_inputs(identity, binding, scene, bill=None):
    approved = {r["requested"]: r for r in identity["files_before"]}
    copied = {
        linux(FOLDER / "capture-input-v1" / name): (linux(Path(scene["path"]) / name), row["sha256"])
        for name, row in scene["files"].items()
    }
    produced = {
        linux(FOLDER / name)
        for name in [
            "wire-config.json",
            "agent-runtime.json",
            "agent-cache-reuse.json",
            "sdk/python-context.json",
            "sdk/entry-dependencies/entry-bill.json",
        ]
    }
    if bill is not None:
        produced.update(
            linux(FOLDER / "sdk/entry-dependencies" / f"query-{n:04d}.json") for n in range(1, len(bill["queries"]) + 1)
        )
    joins = []
    for row in binding["baseline"]["files"]:
        path = row["requested"]
        if path in approved:
            original = approved[path]
            if any(row.get(k) != original.get(k) for k in ["resolved", "sha256", "bytes", "identity", "path_identity"]):
                raise ValueError("actual study prepin identity changed")
            joins.append(dict(path=path, kind="preapproved"))
        elif path in copied:
            source, h = copied[path]
            if approved.get(source, {}).get("sha256") != h or row["sha256"] != h:
                raise ValueError("copied scene lacks source prepin")
            joins.append(dict(path=path, kind="exact_scene_copy", source=source))
        elif path in produced and path.startswith(linux(FOLDER) + "/"):
            joins.append(dict(path=path, kind="declared_producer_output"))
        else:
            raise ValueError("actual study file absent from approved prepin: " + path)
    return dict(static_preapproved_input_join=True, files=joins, source_qualified=False)


def decode_prefix(raw):
    rows = []
    error = None
    for line in raw.decode("utf8", errors="replace").splitlines():
        try:
            row = ast.literal_eval(line)
            if type(row) is not dict:
                raise ValueError("primitive row is not dict")
            rows.append(row)
        except (SyntaxError, ValueError) as exc:
            error = repr(exc)
            break
    return dict(rows=rows, parse_error=error)


def identity_run(label, request):
    request_path = OUT / (label + "-request.txt")
    body = "".join("P\t" + p.encode().hex() + "\n" for p in request["paths"])
    body += "".join("D\t" + p.encode().hex() + "\n" for p in request["roots"])
    body += "".join("V\t" + p.encode().hex() + "\n" for p in request["versions"])
    body += "".join("B\t" + r["path"].encode().hex() + "\t" + r["sha256"] + "\n" for r in request["bootstrap"])
    with request_path.open("x", encoding="utf8", newline="\n") as f:
        f.write(body)
    output = OUT / (label + "-primitive.txt")
    argv = [
        "/usr/bin/env",
        "-i",
        "PATH=/usr/bin:/bin",
        "LANG=C.UTF-8",
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=5s",
        "30s",
        *observer_arguments(linux(request_path), linux(output)),
    ]
    start = time.monotonic_ns()
    primary = None
    result = None
    raw = b""
    write(
        OUT / (label + "-command.json"),
        dict(
            argv=argv,
            start_monotonic_ns=start,
            start_utc=datetime.datetime.now(datetime.UTC).isoformat(),
            bootstrap=request["bootstrap"],
            observer_source_sha256=hashlib.sha256(OBSERVER.read_bytes()).hexdigest(),
        ),
    )
    try:
        verify_bootstrap(request["bootstrap"])
        result = remote(*argv, timeout=45)
        if output.exists():
            raw = output.read_bytes()
        rows = decode_observer(raw)
        write(OUT / (label + "-decoded.json"), rows)
        if result.returncode or not rows or rows[-1].get("kind") != "terminal" or rows[-1].get("error") is not None:
            raise ValueError("primitive identity incomplete/refused")
        verify_bootstrap(request["bootstrap"])
        begin = validate_identity_rows(rows, request)
        before = [r["file"] for r in rows if r.get("kind") == "file" and r["phase"] == "before"]
        after = [r["file"] for r in rows if r.get("kind") == "file" and r["phase"] == "after"]
        if before != after or len(before) != len(begin["requested"]) or [r["requested"] for r in before] != begin["requested"]:
            raise ValueError("identity exact input prepost differs")
        record = dict(
            error=None,
            sources=source_snapshot(),
            files_before=before,
            files_after=after,
            uid=begin["uid"],
            manager_control_environment=begin["manager_control_environment"],
            versions=[r for r in rows if r.get("kind") == "version"],
            observer_terminal=rows[-1],
            request=request,
            qualification=False,
        )
        if record["sources"] != request["sources"]:
            raise ValueError("current source changed during preidentity")
        write(OUT / (label + ".json"), record)
        return record
    except BaseException as exc:
        primary = exc
        raise
    finally:
        recovery_error = None
        try:
            if output.exists():
                with output.open("rb") as stream:
                    raw = stream.read(16 * 1024**2 + 1)
                if len(raw) > 16 * 1024**2:
                    raise ValueError("primitive journal cap exceeded")
            if primary is not None:
                write(OUT / (label + "-decoded-prefix.json"), decode_prefix(raw))
        except Exception as exc:
            recovery_error = repr(exc)
            if primary is not None:
                primary.add_note("primitive partial recovery: " + repr(exc))
        ended = time.monotonic_ns()
        row = dict(
            recovery_error=recovery_error,
            exit=result.returncode if result is not None else None,
            stdout_hex=result.stdout.hex() if result is not None else (getattr(primary, "output", None) or b"").hex(),
            stderr_hex=result.stderr.hex() if result is not None else (getattr(primary, "stderr", None) or b"").hex(),
            error=repr(primary) if primary else None,
            raw_bytes=len(raw),
            end_monotonic_ns=ended,
            elapsed_ns=ended - start,
            end_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        try:
            write(OUT / (label + "-return.json"), row)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("identity return writer: " + repr(exc))


def build_request_bounded():
    output = OUT / "identity-request.json"
    code = "import importlib.util,sys; s=importlib.util.spec_from_file_location('fixed_static_v3_request',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.write(m.OUT/'identity-request.json',m.identity_request())"
    argv = [sys.executable, "-c", code, str(Path(__file__).resolve())]
    process = None
    primary = None
    row = dict(argv=argv, error=None, exit=None)
    write(
        OUT / "request-builder-command.json",
        dict(
            argv=argv,
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            start_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        ),
    )
    start = time.monotonic_ns()
    try:
        with (OUT / "request-builder.stdout").open("xb") as stdout, (OUT / "request-builder.stderr").open("xb") as stderr:
            process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
            row["pid"] = process.pid
            row["exit"] = process.wait(timeout=15)
        if row["exit"] != 0:
            raise ValueError("host request builder refused")
        return json.loads(output.read_bytes())
    except BaseException as exc:
        primary = exc
        row["error"] = repr(exc)
        raise
    finally:
        if process is not None:
            row["cleanup"] = cleanup_child(process)
        end = time.monotonic_ns()
        row.update(start_monotonic_ns=start, end_monotonic_ns=end, elapsed_ns=end - start)
        try:
            write(OUT / "request-builder-return.json", row)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("host request terminal writer: " + repr(exc))


def preidentity():
    request = build_request_bounded()
    return identity_run("preidentity", request)


def postidentity():
    original = json.loads((OUT / "preidentity.json").read_bytes())
    observed = identity_run("postidentity", original["request"])
    if observed["files_before"] != original["files_before"] or observed["sources"] != original["sources"]:
        raise ValueError("postidentity changed")
    return observed


if __name__ == "__main__":
    raise SystemExit(main())
