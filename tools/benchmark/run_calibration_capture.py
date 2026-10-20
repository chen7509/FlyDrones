"""Single admitted raw physical study. Preparation/fixture records grant no flight authority."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
from pathlib import Path

from tools.benchmark.run_openvins_dataset_consumer import ROOT, admission, finish_owned_launcher, linux, write

ATTEMPT = ROOT / "results/target-bearing-physical-capture-dev-1701"
QUALIFICATION = {
    k: False for k in ("source", "clock", "measured_calibration", "accuracy", "teacher", "fusion", "training", "flight")
}
RESERVE = 4 * 1024**3


def admitted(facts):
    return (
        type(facts.get("windows_available")) is int
        and facts["windows_available"] >= RESERVE
        and type(facts.get("wsl", {}).get("available")) is int
        and facts["wsl"]["available"] >= RESERVE
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


def wsl(*argv, check=True, timeout=30):
    result = subprocess.run(["wsl", "-d", "Ubuntu", "--", *argv], capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"WSL refused: {argv!r}, code={result.returncode}, stderr={result.stderr.hex()}")
    return result


def verify_remote(study, sha):
    command = [
        "/usr/bin/env",
        "-i",
        "HOME=/home/yuchen7509",
        "PATH=/usr/bin:/bin",
        "PYTHONPATH=" + linux(ROOT) + "/src:" + linux(ROOT),
        "/usr/bin/python3",
        "-m",
        "tools.benchmark.calibration_capture_study",
        "--verify-only",
        "--study",
        linux(study),
        "--sha256",
        sha,
    ]
    return json.loads(wsl(*command).stdout)


def stop_scope(output, unit, inside):
    observed = wsl(
        "systemctl", "--user", "show", unit, "--property=InvocationID", "--property=ControlGroup", check=False, timeout=10
    )
    actual = dict(x.split("=", 1) for x in observed.stdout.decode().splitlines() if "=" in x)
    expected = dict(x.split("=", 1) for x in inside["systemd_properties"].splitlines() if "=" in x)
    owned = (
        observed.returncode == 0
        and expected.get("InvocationID")
        and actual.get("InvocationID") == expected["InvocationID"]
        and actual.get("ControlGroup") == inside["cgroup"]
        and inside["cgroup"].endswith("/" + unit)
    )
    write(output / "scope-stop-intent.json", dict(ownership_confirmed=bool(owned), properties=actual, residual="unknown"))
    if not owned:
        raise RuntimeError("scope ownership unknown; no unit stop")
    stopped = wsl("systemctl", "--user", "stop", unit, check=False, timeout=10)
    write(
        output / "scope-stop-return.json",
        dict(exit=stopped.returncode, stdout_hex=stopped.stdout.hex(), stderr_hex=stopped.stderr.hex()),
    )
    if stopped.returncode:
        raise RuntimeError("owned scope stop refused; residual unknown")


def launch_scope(output, study, sha, verified, unit):
    before = wsl("systemctl", "--user", "show", unit, "--property=LoadState", "--property=ActiveState", check=False, timeout=10)
    write(
        output / "scope-before.json", dict(exit=before.returncode, stdout_hex=before.stdout.hex(), stderr_hex=before.stderr.hex())
    )
    if b"LoadState=not-found" not in before.stdout:
        raise RuntimeError("new scope absent state unknown")
    profile = dict(unit=unit, output=linux(output), study=linux(study), study_sha256=sha, verified=verified)
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
        "--property=MemoryMax=" + str(RESERVE),
        "--property=MemorySwapMax=0",
        "--property=CPUQuota=100%",
        "--property=TasksMax=256",
        "--property=RuntimeMaxSec=330",
        "--property=TimeoutStopSec=10s",
        "/usr/bin/env",
        "-i",
        "HOME=/home/yuchen7509",
        "PATH=/usr/bin:/bin",
        "PYTHONPATH=" + linux(ROOT) + "/src:" + linux(ROOT),
        "/usr/bin/python3",
        "-m",
        "tools.benchmark.calibration_capture_scope",
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
            stop_scope(output, unit, json.loads(identity.read_text(encoding="utf8")))
        else:
            write(output / "scope-ownership-unknown.json", dict(unit=unit, residual="unknown; no unit stop"))

    def observe_release():
        after = wsl(
            "systemctl", "--user", "show", unit, "--property=LoadState", "--property=ActiveState", check=False, timeout=10
        )
        released = None
        identity = output / "inside-before.json"
        if identity.exists():
            inside = json.loads(identity.read_text(encoding="utf8"))
            group = inside["cgroup"]
            if group.endswith("/" + unit):
                exists = wsl("test", "-d", "/sys/fs/cgroup" + group, check=False, timeout=10)
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
                result["exit"] = process.wait(timeout=360)
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
                finish_owned_launcher(output, process)
            except Exception as exc:
                result["launcher_cleanup_error"] = repr(exc)
            if primary is not None:
                try:
                    observe_release()
                except Exception as exc:
                    result["release_observation_error"] = repr(exc)
        try:
            write(output / "launcher-completion.json", result)
        except Exception:
            if primary is None:
                raise
    return result


def execute_once(study, sha, record, output=ATTEMPT, *, collect=None, verify=None, launch=None):
    real = collect is None and verify is None and launch is None
    if not real and any(x is None for x in (collect, verify, launch)):
        raise ValueError("fixture dependencies must be supplied together")
    output, record, study = Path(output), Path(record), Path(study)
    if real and output.resolve() != ATTEMPT.resolve():
        raise ValueError("physical attempt path is fixed; no alternate replay directory")
    if output.exists():
        raise FileExistsError("raw physical attempt already claimed")
    collect, verify, launch = collect or admission, verify or verify_remote, launch or launch_scope
    first = collect()
    write(record, dict(first=first, reserve_bytes=RESERVE, admitted=admitted(first), qualification=QUALIFICATION))
    result = dict(attempt_claimed=False, qualification=QUALIFICATION)
    if not admitted(first):
        return dict(result, reason="first resources refused")
    try:
        initial = verify(study, sha)
        write(record.with_name(record.name + ".verification-first.json"), initial)
        final = verify(study, sha)
        write(record.with_name(record.name + ".verification-second.json"), final)
        if final != initial:
            return dict(result, reason="selected inputs changed before claim")
        second = collect()
        write(
            record.with_name(record.name + ".second.json"), dict(facts=second, reserve_bytes=RESERVE, admitted=admitted(second))
        )
        if not admitted(second):
            return dict(result, reason="second resources refused")
    except Exception as exc:
        write(record.with_name(record.name + ".verification-error.json"), dict(error=repr(exc), attempt_claimed=False))
        return dict(result, error=repr(exc))
    unit = "fly-calibration-" + secrets.token_hex(12) + ".scope"
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "attempt.json",
        dict(
            study=str(study.resolve()),
            study_sha256=sha,
            unit=unit,
            verified=final,
            attempt_claimed=True,
            qualification=QUALIFICATION,
        ),
    )
    try:
        result = dict(result, attempt_claimed=True, launch=launch(output, study, sha, final, unit))
    except Exception as exc:
        result = dict(result, attempt_claimed=True, error=repr(exc))
    write(output / "completion.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-once", required=True, action="store_true")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--admission-record", type=Path, required=True)
    args = parser.parse_args(argv)
    result = execute_once(args.study, args.sha256, args.admission_record)
    print(json.dumps(result, indent=2))
    return 0 if result.get("launch", {}).get("exit") == 0 and result["launch"].get("owned_group_released") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
