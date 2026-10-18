"""Production scope entry and launcher for the fixed v2 once coordinator; no import-time dispatch."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from tools.benchmark.calibration_capture_scope import cleanup_owned, manager_environment
from tools.benchmark.native_offset_build_receipt import produce, read_json, write
from tools.benchmark.native_offset_once import ROOT, verify_request
from tools.benchmark.run_openvins_dataset_consumer import linux


def wsl(*argv, check=True, timeout=10):
    # Fixed control queries remain on the original bounded 10-second control boundary.
    from tools.benchmark.native_query_process import bounded_run

    result = bounded_run(["wsl", "-d", "Ubuntu", "--", *argv], cwd=ROOT, env=os.environ.copy(), timeout=min(timeout, 10))
    if result.output_limit_exceeded or result.collection_errors or (check and result.returncode):
        raise RuntimeError("WSL control query refused")
    return result


class DeadlineControl:
    def __init__(self, deadline):
        self.deadline = deadline

    def __call__(self, *argv, **kwargs):
        # Helper owns up to 2s wait + two 2s reader joins; retain 10s for launcher cleanup.
        remaining = self.deadline - time.monotonic() - 6 - 10
        if remaining <= 0:
            raise TimeoutError("outer control budget exhausted; residual unknown")
        kwargs["timeout"] = min(10, remaining)
        result = wsl(*argv, **kwargs)
        if time.monotonic() >= self.deadline - 10:
            raise TimeoutError("outer control cleanup reserve exhausted")
        return result


def finish_launcher(output, process, deadline):
    row = dict(pid=process.pid, exit_code=None, scope_release="unknown")
    try:
        if process.poll() is None:
            process.terminate()
        remaining = min(5, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("owned launcher cleanup deadline")
        try:
            row["exit_code"] = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
            remaining = min(5, deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError("owned launcher kill/wait deadline") from None
            row["exit_code"] = process.wait(timeout=remaining)
    except (OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
        row["cleanup_error"] = repr(exc)
    write(output / "owned-launcher-timeout-cleanup.json", row)
    return row


def require_consumed_claim(profile):
    from tools.benchmark.native_offset_once import ATTEMPT, guard_attempt
    from tools.benchmark.run_calibration_capture import admitted

    stage = profile.get("stage")
    output = Path(profile.get("output", ""))
    if stage not in ("build", "run") or output != ATTEMPT / stage:
        raise ValueError("fixed consumed scope claim required before Linux observation")
    guard_attempt(output)
    if (output / "completion.json").exists() or (output / "launcher-completion.json").exists():
        raise ValueError("terminal consumed scope claim cannot be reopened")
    try:
        claim = read_json(output / "consumed.json")
        for key in ("unit", "stage"):
            if claim.get(key) != profile.get(key):
                raise ValueError("scope claim identity differs")
        if (
            claim.get("state") != "CONSUMED_DISPATCH_BOUNDARY"
            or claim.get("request_sha256") != profile.get("sha256")
            or claim.get("review_sha256") != profile.get("review_sha256")
        ):
            raise ValueError("scope claim binding differs")
        for name in ("firstfacts.json", "secondfacts.json"):
            record = read_json(output / name)
            if record.get("admitted") is not True or not admitted(record.get("facts", {})):
                raise ValueError("scope claim resources not admitted")
        for name in ("verified-first.json", "verified-second.json"):
            if read_json(output / name) != profile.get("verified"):
                raise ValueError("scope claim selected inputs differ")
    except (OSError, KeyError) as exc:
        raise ValueError("missing consumed scope claim") from exc
    write(
        output / "inside-entry.json",
        dict(
            unit=profile["unit"],
            request_sha256=profile["sha256"],
            review_sha256=profile["review_sha256"],
            stage=stage,
            pid=os.getpid(),
        ),
    )


def verify_scope(unit, group, limits, properties, stage):
    memory, tasks = (1024**3, "64") if stage == "build" else (4 * 1024**3, "256")
    if (
        stage not in ("build", "run")
        or re.fullmatch(r"fly-offset-[0-9a-f]{24}\.scope", unit) is None
        or not group.endswith("/" + unit)
        or properties.get("ControlGroup") != group
        or not properties.get("InvocationID")
        or limits != {"memory.max": str(memory), "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": tasks}
    ):
        raise ValueError("owned once scope identity/limits mismatch")


def run_inside(profile):
    require_consumed_claim(profile)
    import resource

    output = Path(profile["output"])
    stage = profile["stage"]
    started = time.monotonic()
    budget = 300 if stage == "build" else 315
    deadline = started + budget
    rows = [line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::")]
    if len(rows) != 1:
        raise ValueError("unified owned cgroup unknown")
    group = rows[0]
    root = Path("/sys/fs/cgroup" + group)
    limits = {name: (root / name).read_text().strip() for name in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")}
    props = subprocess.run(
        ["systemctl", "--user", "show", profile["unit"], "--property=InvocationID", "--property=ControlGroup"],
        env=manager_environment(),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    properties = dict(line.split("=", 1) for line in props.stdout.splitlines() if "=" in line)
    write(
        output / "inside-before.json",
        dict(pid=os.getpid(), cgroup=group, limits=limits, systemd_properties=props.stdout, qualification=False),
    )
    verify_scope(profile["unit"], group, limits, properties, stage)
    checked = verify_request(profile["request"], profile["sha256"], profile["review"], profile["review_sha256"], stage)
    if checked != profile["verified"]:
        raise ValueError("selected inputs changed at scoped entry")
    request = checked["request"]
    request = dict(request, source=checked["source"])
    build = Path(request["bindings"]["exclusive_build_dir"])
    if stage == "build":
        build.mkdir(exist_ok=False)
    commands = checked["command"] if stage == "build" else [checked["command"]]
    steps = []
    primary = None
    result = dict(exit=None, qualification=False, descendants="unknown", errors=[])
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    try:
        for index, command in enumerate(commands):
            if time.monotonic() >= deadline:
                raise TimeoutError("whole stage deadline before command")
            boundary = verify_request(
                profile["request"], profile["sha256"], profile["review"], profile["review_sha256"], stage, require_absent=False
            )
            if boundary != checked:
                raise ValueError("selected request/review changed at final command boundary")
            name = ("configure", "build")[index] if stage == "build" else "capture"
            remaining = deadline - time.monotonic()
            actual = [
                "/usr/bin/time",
                "-v",
                "-o",
                str(output / (name + ".resources")),
                "/usr/bin/timeout",
                "--signal=TERM",
                "--kill-after=10s",
                str(max(0.001, remaining)) + "s",
                *command,
            ]
            row = dict(name=name, command=command, actual_command=actual, exit=None, cleanup=None, error=None)
            steps.append(row)
            process = None
            try:
                with (output / (name + ".stdout")).open("xb") as stdout, (output / (name + ".stderr")).open("xb") as stderr:
                    process = subprocess.Popen(
                        actual, cwd=ROOT, env=checked["environment"], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr
                    )
                    write(output / (name + ".start.json"), dict(pid=process.pid, command=actual, cgroup=group))
                    row["exit"] = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except BaseException as exc:
                row["error"] = repr(exc)
                raise
            finally:
                if process is not None:
                    row["cleanup"] = cleanup_owned(process)
                write(output / (name + ".return.json"), row)
            if row["exit"] != 0 or row["cleanup"].get("exit") != 0:
                raise RuntimeError(name + " failed; attempt remains consumed")
        verify_request(
            profile["request"], profile["sha256"], profile["review"], profile["review_sha256"], stage, require_absent=False
        )
        result["exit"] = 0
    except BaseException as exc:
        primary = exc
        result["errors"].append(repr(exc))
    finally:
        try:
            result["limits_after"] = {name: (root / name).read_text().strip() for name in limits}
            result["memory_events"] = (root / "memory.events").read_text()
            result["memory_peak"] = (root / "memory.peak").read_text()
            if result["limits_after"] != limits:
                raise ValueError("scope limits changed")
            counters = dict(line.split() for line in result["memory_events"].splitlines())
            if any(int(counters.get(k, "0")) for k in ("oom", "oom_kill", "oom_group_kill")):
                raise ValueError("scope OOM events")
            if time.monotonic() > deadline:
                raise TimeoutError("terminal work exhausted original stage budget")
        except BaseException as exc:
            result["errors"].append(repr(exc))
            result["exit"] = 2
        if stage == "build":
            try:
                receipt = produce(request, build, steps, stage_errors=result["errors"], deadline=deadline)
                if not receipt["complete"]:
                    raise ValueError("build receipt incomplete; run gate remains closed")
                if time.monotonic() > deadline:
                    raise TimeoutError("build receipt exceeded shared stage deadline")
            except BaseException as exc:
                result["errors"].append(repr(exc))
                result["exit"] = 2
        if result["errors"]:
            result["exit"] = 2
        result["elapsed_s"] = time.monotonic() - started
        write(output / "inside-completion.json", result)
    if primary is not None and not isinstance(primary, Exception):
        raise primary
    return result["exit"]


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "--verify":
        parser = argparse.ArgumentParser()
        parser.add_argument("--verify", required=True)
        for name in ("sha256", "review", "review-sha256", "stage"):
            parser.add_argument("--" + name, required=True)
        selected = parser.parse_args(args)
        print(
            json.dumps(verify_request(selected.verify, selected.sha256, selected.review, selected.review_sha256, selected.stage))
        )
        return 0
    if len(args) != 1:
        raise ValueError("one owned profile required")
    return run_inside(read_json(args[0]))


def stop_scope(output, unit, inside, *, query=None):
    query = query or wsl
    observed = query("systemctl", "--user", "show", unit, "--property=InvocationID", "--property=ControlGroup", check=False)
    actual = dict(line.split("=", 1) for line in observed.stdout.decode().splitlines() if "=" in line)
    expected = dict(line.split("=", 1) for line in inside["systemd_properties"].splitlines() if "=" in line)
    owned = (
        observed.returncode == 0
        and expected.get("InvocationID")
        and actual.get("InvocationID") == expected["InvocationID"]
        and actual.get("ControlGroup") == inside["cgroup"]
        and inside["cgroup"].endswith("/" + unit)
    )
    write(output / "scope-stop-intent.json", dict(ownership_confirmed=bool(owned), properties=actual, residual="unknown"))
    if not owned:
        raise RuntimeError("unknown scope identity; no unit stop")
    stopped = query("systemctl", "--user", "stop", unit, check=False)
    write(
        output / "scope-stop-return.json",
        dict(exit=stopped.returncode, stdout_hex=stopped.stdout.hex(), stderr_hex=stopped.stderr.hex()),
    )
    if stopped.returncode:
        raise RuntimeError("scope stop failed; residual unknown")


def verify_remote(request, sha, review, review_sha, stage):
    command = [
        "wsl",
        "-d",
        "Ubuntu",
        "--",
        "/usr/bin/env",
        "-i",
        "HOME=/home/yuchen7509",
        "PATH=/usr/bin:/bin",
        "PYTHONPATH=" + linux(ROOT) + "/src:" + linux(ROOT),
        "/usr/bin/python3",
        "-m",
        "tools.benchmark.native_offset_once_scope",
        "--verify",
        linux(request),
        "--sha256",
        sha,
        "--review",
        linux(review),
        "--review-sha256",
        review_sha,
        "--stage",
        stage,
    ]
    # Metadata request output is capped by the selected bounded helper, never a target invocation.
    from tools.benchmark.native_query_process import bounded_run

    result = bounded_run(command, cwd=ROOT, env=os.environ.copy(), timeout=10)
    if result.returncode or result.output_limit_exceeded or result.collection_errors:
        raise RuntimeError("current Linux verification refused: " + result.stderr.hex())
    return json.loads(result.stdout)


def launch_scope(output, study, sha, review, review_sha, stage, verified, unit):
    started = time.monotonic()
    outer = 330 if stage == "build" else 360
    deadline = started + outer
    control = DeadlineControl(deadline)
    before = control(
        "systemctl", "--user", "show", unit, "--property=LoadState", "--property=ActiveState", check=False, timeout=10
    )
    write(
        output / "scope-before.json", dict(exit=before.returncode, stdout_hex=before.stdout.hex(), stderr_hex=before.stderr.hex())
    )
    if b"LoadState=not-found" not in before.stdout:
        raise RuntimeError("new scope absent state unknown")
    profile = dict(
        unit=unit,
        output=linux(output),
        request=linux(study),
        sha256=sha,
        review=linux(review),
        review_sha256=review_sha,
        stage=stage,
        verified=verified,
    )
    write(output / "scope.json", profile)
    command = [
        "wsl",
        "-d",
        "Ubuntu",
        "--",
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--unit=" + unit.removesuffix(".scope"),
        "--property=MemoryMax=" + str(1024**3 if stage == "build" else 4 * 1024**3),
        "--property=MemorySwapMax=0",
        "--property=CPUQuota=100%",
        "--property=TasksMax=" + ("64" if stage == "build" else "256"),
        "--property=RuntimeMaxSec=" + ("315" if stage == "build" else "330"),
        "--property=TimeoutStopSec=10s",
        "/usr/bin/env",
        "-i",
        "HOME=/home/yuchen7509",
        "PATH=/usr/bin:/bin",
        "PYTHONPATH=" + linux(ROOT) + "/src:" + linux(ROOT),
        "/usr/bin/python3",
        "-m",
        "tools.benchmark.native_offset_once_scope",
        linux(output / "scope.json"),
    ]
    process = None
    stop_attempted = False
    result = dict(exit=None, owned_group_released=None, escaped_closure="unknown", error=None)

    def stop_if_identified():
        nonlocal stop_attempted
        stop_attempted = True
        identity = output / "inside-before.json"
        if identity.exists():
            stop_scope(output, unit, read_json(identity), query=control)
        else:
            write(output / "scope-ownership-unknown.json", dict(unit=unit, residual="unknown; no unit stop"))

    def observe_release():
        after = control(
            "systemctl", "--user", "show", unit, "--property=LoadState", "--property=ActiveState", check=False, timeout=10
        )
        released = None
        identity = output / "inside-before.json"
        if identity.exists():
            inside = read_json(identity)
            group = inside["cgroup"]
            if group.endswith("/" + unit):
                exists = control("test", "-d", "/sys/fs/cgroup" + group, check=False, timeout=10)
                released = exists.returncode == 1 and b"LoadState=not-found" in after.stdout
        result.update(
            owned_group_released=released,
            after_exit=after.returncode,
            after_stdout_hex=after.stdout.hex(),
            after_stderr_hex=after.stderr.hex(),
        )

    primary = None
    try:
        with (output / "launcher.stdout").open("xb") as stdout, (output / "launcher.stderr").open("xb") as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            write(output / "launcher.json", dict(pid=process.pid, command=command, unit=unit))
            try:
                # Reserve the original final 30 seconds for control/owned cleanup.
                result["exit"] = process.wait(
                    timeout=max(0.001, (300 if stage == "build" else 330) - (time.monotonic() - started))
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError("physical launcher timeout; retained ownership/cleanup evidence") from None
        observe_release()
        if result["owned_group_released"] is not True:
            stop_if_identified()
            observe_release()
    except BaseException as exc:
        primary = exc
        result["error"] = repr(exc)
        raise
    finally:
        if process is not None:
            if primary is not None and not stop_attempted:
                try:
                    stop_if_identified()
                except Exception as exc:
                    result["scope_cleanup_error"] = repr(exc)
            try:
                cleanup = finish_launcher(output, process, deadline)
                if cleanup.get("cleanup_error") or cleanup.get("exit_code") is None:
                    result["launcher_cleanup_error"] = cleanup
            except Exception as exc:
                result["launcher_cleanup_error"] = repr(exc)
            if primary is not None:
                try:
                    observe_release()
                except Exception as exc:
                    result["release_observation_error"] = repr(exc)
        try:
            if result.get("launcher_cleanup_error") or result.get("scope_cleanup_error"):
                result["exit"] = 2
                result["owned_group_released"] = None
            result["elapsed_s"] = time.monotonic() - started
            result["outer_budget_s"] = outer
            if result["elapsed_s"] > outer:
                result["error"] = "outer budget exhausted; cleanup/release not qualified"
                result["owned_group_released"] = None
                result["exit"] = 2
            write(output / "launcher-completion.json", result)
        except Exception:
            if primary is None:
                raise
    return result


if __name__ == "__main__":
    raise SystemExit(main())
