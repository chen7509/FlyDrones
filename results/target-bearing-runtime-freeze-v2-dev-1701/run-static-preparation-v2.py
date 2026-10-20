"""Literal admitted once-only static v2 coordinator. Never executes physical capture."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from tools.benchmark.run_openvins_dataset_consumer import admission, linux, write

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/target-bearing-runtime-freeze-v2-dev-1701"
FOLDER = OUT / "frozen-study-v2"
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


def preidentity():
    argv = [
        "/usr/bin/env",
        "-i",
        *[k + "=" + v for k, v in sdk_environment().items()],
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=5s",
        "30s",
        "/usr/bin/python3",
        linux(Path(__file__)),
        "--preidentity",
    ]
    start = time.monotonic_ns()
    write(
        OUT / "preidentity-command.json",
        dict(argv=argv, start_monotonic_ns=start, start_utc=datetime.datetime.now(datetime.UTC).isoformat()),
    )
    result = remote(*argv, timeout=45)
    end = time.monotonic_ns()
    write(
        OUT / "preidentity-return.json",
        dict(
            exit=result.returncode,
            stdout_hex=result.stdout.hex(),
            stderr_hex=result.stderr.hex(),
            end_monotonic_ns=end,
            elapsed_ns=end - start,
        ),
    )
    if result.returncode:
        raise ValueError("Linux pre-command identities failed; no static attempt claimed")
    return json.loads((OUT / "preidentity.json").read_bytes())


def linux_preidentity():
    """Trusted file/version metadata only. This is not a renderer/PX4/Agent run."""
    from tools.benchmark.calibration_capture_contract import scene_record
    from tools.benchmark.calibration_capture_scope import manager_environment
    from tools.benchmark.native_entry_dependencies import tool_paths
    from tools.benchmark.prepare_calibration_capture_v2 import CATALOG, SOURCE, V1_FOLDER, reuse_agent_cache

    if sys.platform != "linux" or not json.loads((OUT / "first-admission.json").read_bytes())["static_admitted"]:
        raise ValueError("preidentity requires admitted Linux coordinator context")
    paths = set(tool_paths().values()) | {
        "/usr/bin/python3",
        "/usr/bin/systemd-run",
        "/usr/bin/systemctl",
        "/usr/bin/time",
        "/usr/bin/timeout",
        "/usr/bin/env",
        "/usr/bin/dpkg-query",
        str(ROOT / "results/collada-ordered-candidates-dev-1701/build-v1/resource_resolver"),
    }
    catalog = json.loads(CATALOG.read_bytes())
    for role, members in catalog["inventory"].items():
        if role == "runtime:dependencies" or (
            role.startswith("runtime-root:")
            and not role.startswith("runtime-root:python")
            and role not in {"runtime-root:openvins", "runtime-root:native-reference"}
        ):
            paths.update(members)
    for pattern in ("gz/**/*.so", "sdformat14*.so"):
        paths.update(str(p) for p in Path("/usr/lib/python3/dist-packages").glob(pattern))
    before = []
    record = dict(
        start_monotonic_ns=time.monotonic_ns(),
        start_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        sources=source_snapshot(),
        files_before=before,
        versions=[],
        error=None,
        qualification=False,
    )
    primary = None
    try:
        agent = json.loads((V1_FOLDER / "agent-runtime.json").read_bytes())
        deployment = json.loads((V1_FOLDER / "agent-deployment.json").read_bytes())
        record.update(
            uid=os.getuid(),
            scene=scene_record(SOURCE),
            agent_cache=reuse_agent_cache(agent, deployment),
            manager_control_environment=manager_environment(),
            packages={p: importlib.metadata.version(p) for p in ("numpy", "scipy", "pyulog", "pymavlink", "protobuf")},
            python=sys.version,
        )
        paths.update(str(Path(record["scene"]["path"]) / name) for name in record["scene"]["files"])
        paths.update(row["requested"] for row in record["agent_cache"]["files"])
        paths.update(
            [
                record["agent_cache"]["bundle"]["requested"],
                str(V1_FOLDER / "agent-runtime.json"),
                str(V1_FOLDER / "agent-deployment.json"),
                str(CATALOG),
            ]
        )
        paths.update(
            str(Path(name).resolve())
            for module in tuple(sys.modules.values())
            if (name := getattr(module, "__file__", None)) and Path(name).is_file()
        )
        initial = observe_files(sorted(paths), OUT / "preidentity-files-before.json")
        before = initial["files"]
        record["files_before"] = before
        if initial["error"] is not None or initial.get("journal_error") is not None:
            raise ValueError("partial pre-command file identity: " + repr(initial))
        version_tools = {
            p
            for p in paths
            if p
            in set(tool_paths().values())
            | {
                "/usr/bin/systemd-run",
                "/usr/bin/systemctl",
                "/usr/bin/time",
                "/usr/bin/timeout",
                "/usr/bin/env",
                "/usr/bin/dpkg-query",
            }
        }
        for path in sorted(version_tools):
            row = version_observation(path, OUT / f"preidentity-version-{len(record['versions']) + 1:02d}.json")
            record["versions"].append(row)
            query = row["query"]
            if (
                row.get("error") is not None
                or row.get("postpin_error") is not None
                or row.get("journal_error") is not None
                or query is None
                or type(query["exit"]) is not int
                or row["file_before"] != row["file_after"]
                or query["error"] is not None
                or query["exit"] != 0
                or not query["reader_complete"]
                or query["output_limit_exceeded"]
            ):
                raise ValueError("pre-command tool version/identity refused: " + repr(row))
        final = observe_files(sorted(paths), OUT / "preidentity-files-after.json")
        record["files_after"] = final["files"]
        if final["error"] is not None or final.get("journal_error") is not None:
            raise ValueError("partial post-version file identity: " + repr(final))
        if before != record["files_after"] or record["sources"] != source_snapshot():
            raise ValueError("pre-command input/source changed")
    except BaseException as exc:
        primary = exc
        record["error"] = repr(exc)
        raise
    finally:
        end = time.monotonic_ns()
        record.update(
            end_monotonic_ns=end,
            elapsed_ns=end - record["start_monotonic_ns"],
            end_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        try:
            write(OUT / "preidentity.json", record)
        except Exception as exc:
            if primary is None:
                raise
            primary.add_note("preidentity persistence failure: " + repr(exc))


def observe_files(paths, output, *, pin=None):
    from tools.benchmark.declared_runtime_snapshot import file_record

    pin = pin or file_record
    row = dict(requested=paths, files=[], error=None, failed_path=None, start_monotonic_ns=time.monotonic_ns())
    for path in paths:
        try:
            row["files"].append(pin(path))
        except Exception as exc:
            row.update(error=repr(exc), failed_path=path)
            break
    row["end_monotonic_ns"] = time.monotonic_ns()
    row["elapsed_ns"] = row["end_monotonic_ns"] - row["start_monotonic_ns"]
    try:
        write(output, row)
    except Exception as exc:
        row["journal_error"] = repr(exc)
        try:
            write(output.with_name(output.stem + "-failure.json"), row)
        except Exception as fallback:
            row["fallback_writer_error"] = repr(fallback)
    return row


def version_observation(path, output, *, pin=None, run=None):
    from tools.benchmark.declared_runtime_snapshot import file_record
    from tools.benchmark.native_entry_dependencies import BASE_ENV, _run_tool

    if (pin is None) != (run is None):
        raise ValueError("both fixture dependencies required")
    pin, run = pin or file_record, run or _run_tool
    row = dict(file_before=None, query=None, file_after=None, error=None)
    try:
        row["file_before"] = pin(path)
        row["query"] = run([path, "--version"], dict(BASE_ENV))
        try:
            row["file_after"] = pin(path)
        except Exception as exc:
            row["postpin_error"] = repr(exc)
    except Exception as exc:
        row["error"] = repr(exc)
    try:
        write(output, row)
    except Exception as exc:
        row["journal_error"] = repr(exc)
        try:
            write(output.with_name(output.stem + "-failure.json"), row)
        except Exception as fallback:
            row["fallback_writer_error"] = repr(fallback)
    return row


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
        raise ValueError("actual v2 final study refused")
    return json.loads(result.stdout)


def linux_postidentity():
    original = json.loads((OUT / "preidentity.json").read_bytes())
    observed = observe_files([row["requested"] for row in original["files_before"]], OUT / "postidentity-files.json")
    current = observed["files"]
    result = dict(
        files=current,
        sources=source_snapshot(),
        files_stable=observed["error"] is None and observed.get("journal_error") is None and current == original["files_before"],
        sources_stable=source_snapshot() == original["sources"],
        qualification=False,
    )
    write(OUT / "postidentity.json", result)
    if not result["files_stable"] or not result["sources_stable"]:
        raise ValueError("pre-command Linux file/source identities changed after attempt")


def postidentity():
    argv = [
        "/usr/bin/env",
        "-i",
        *[k + "=" + v for k, v in sdk_environment().items()],
        "/usr/bin/python3",
        linux(Path(__file__)),
        "--postidentity",
    ]
    result = remote(*argv, timeout=30)
    write(
        OUT / "postidentity-return.json",
        dict(argv=argv, exit=result.returncode, stdout_hex=result.stdout.hex(), stderr_hex=result.stderr.hex()),
    )
    if result.returncode:
        raise ValueError("Linux post-command identity refused")
    return json.loads((OUT / "postidentity.json").read_bytes())


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
        blocked_processes=first["blocked_processes"],
        docker_exit=first["docker_exit"],
        docker_running=first["docker_running"],
        static_admitted=admitted(first),
        reserve_each_bytes=2**30,
        private_sha256=hashlib.sha256(private.read_bytes()).hexdigest(),
        private_bytes=private.stat().st_size,
    )
    write(OUT / (name + ".json"), public)
    return public["static_admitted"]


def execute():
    if OUT != ROOT / "results/target-bearing-runtime-freeze-v2-dev-1701" or FOLDER != OUT / "frozen-study-v2":
        raise ValueError("literal static v2 path required")
    if FOLDER.exists() or any(
        (OUT / p).exists() for p in ("attempt.json", "first-admission.json", "first-admission-private.json", "completion.json")
    ):
        raise FileExistsError("static v2 already claimed/observed; no replay or gate polling")
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
        "-m",
        "tools.benchmark.prepare_calibration_capture_v2",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--execute-once", action="store_true")
    action.add_argument("--preidentity", action="store_true")
    action.add_argument("--postidentity", action="store_true")
    args = parser.parse_args()
    if args.preidentity:
        linux_preidentity()
        return 0
    if args.postidentity:
        linux_postidentity()
        return 0
    try:
        result = execute()
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


if __name__ == "__main__":
    raise SystemExit(main())
