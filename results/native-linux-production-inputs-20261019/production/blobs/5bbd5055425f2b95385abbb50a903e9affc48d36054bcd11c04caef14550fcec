"""Own scoped collector invocation; no new simulation, estimator or flight algorithm."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


def write(path, value):
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def manager_environment(runtime_root=Path("/run/user")):
    """Own manager control only; never add session state to collector/SDK env."""
    uid = os.getuid()
    runtime = Path(runtime_root) / str(uid)
    identity = runtime.lstat()
    if not stat.S_ISDIR(identity.st_mode) or identity.st_uid != uid:
        raise ValueError("own user manager runtime directory identity unknown")
    return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": str(runtime)}


def verify_scope(unit, group, limits, properties):
    expected = {"memory.max": str(4 * 1024**3), "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "256"}
    if (
        re.fullmatch(r"fly-calibration-[0-9a-f]{3,24}\.scope", unit) is None
        or not group.endswith("/" + unit)
        or limits != expected
        or properties.get("ControlGroup") != group
        or not properties.get("InvocationID")
    ):
        raise ValueError("own physical scope identity/limits mismatch")


def cleanup_owned(process):
    result = dict(pid=process.pid, before=process.poll(), descendants="unknown")
    try:
        if result["before"] is None:
            process.terminate()
            result["terminate_sent"] = True
        try:
            result["exit"] = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            result["kill_sent"] = True
            result["exit"] = process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.update(error=repr(exc), exit=process.poll())
    return result


def main(argv=None):
    from tools.benchmark.calibration_capture_study import verify_study

    args = sys.argv[1:] if argv is None else argv
    profile = json.loads(Path(args[0]).read_text(encoding="utf8"))
    output = Path(profile["output"])
    lines = [line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::")]
    if len(lines) != 1:
        raise ValueError("own unified physical cgroup unknown")
    group = lines[0]
    root = Path("/sys/fs/cgroup" + group)
    limits = {name: (root / name).read_text().strip() for name in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")}
    props = subprocess.run(
        ["systemctl", "--user", "show", profile["unit"], "--property=InvocationID", "--property=ControlGroup"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        env=manager_environment(),
    )
    properties = dict(line.split("=", 1) for line in props.stdout.splitlines() if "=" in line)
    before = dict(pid=os.getpid(), cgroup=group, limits=limits, systemd_properties=props.stdout, qualification=False)
    write(output / "inside-before.json", before)
    verify_scope(profile["unit"], group, limits, properties)
    checked = verify_study(Path(profile["study"]), profile["study_sha256"])
    write(output / "verified-before.json", checked)
    if checked != profile["verified"]:
        raise ValueError("physical scope selected inputs changed before command")
    command = [
        "/usr/bin/time",
        "-v",
        "-o",
        str(output / "resources.txt"),
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=10s",
        "315s",
        *checked["command"],
    ]
    process = None
    result = dict(exit=None, cgroup=group, selected_inputs_stable=None, qualification=False, error=None)
    primary = None
    try:
        with (output / "collector.stdout").open("xb") as stdout, (output / "collector.stderr").open("xb") as stderr:
            process = subprocess.Popen(command, cwd=checked["cwd"], stdout=stdout, stderr=stderr)
            write(output / "collector-start.json", dict(pid=process.pid, command=command, cgroup=group))
            result["exit"] = process.wait(timeout=330)
        after = verify_study(Path(profile["study"]), profile["study_sha256"], require_absent=False)
        write(output / "verified-after.json", after)
        result["selected_inputs_stable"] = after == checked
    except BaseException as exc:
        primary = exc
        result["error"] = repr(exc)
        raise
    finally:
        if process is not None:
            result["owned_child_cleanup"] = cleanup_owned(process)
            if result["exit"] is None:
                result["exit"] = result["owned_child_cleanup"].get("exit")
        try:
            result.update(
                limits_after={name: (root / name).read_text().strip() for name in limits},
                memory_events=(root / "memory.events").read_text(),
                memory_peak=(root / "memory.peak").read_text() if (root / "memory.peak").exists() else None,
            )
        except Exception as exc:
            result["counter_error"] = repr(exc)
        try:
            write(output / "inside-completion.json", result)
        except Exception:
            if primary is None:
                raise
    return result["exit"] if result["selected_inputs_stable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
