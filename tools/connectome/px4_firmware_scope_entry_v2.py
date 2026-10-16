"""Primitive pre-make checks; no project imports, admission or binary authority."""

import os
import sys

ROOT = "/home/yuchen7509/px4-status-worktrees/firmware-v1"
UNIT_PREFIX = "flydrones-px4-status-build-v1-"


def _read_virtual(path, cap):
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        data = b""
        while True:
            part = os.read(descriptor, min(4096, cap + 1 - len(data)))
            if not part:
                break
            data += part
            if len(data) > cap:
                raise ValueError("scope virtual file exceeds bound")
    except BaseException as primary:
        try:
            os.close(descriptor)
        except BaseException as secondary:
            primary.add_note("scope descriptor close also failed: " + repr(secondary))
        raise
    else:
        os.close(descriptor)
        return data


def _snapshot(unit):
    uid, effective, pid = os.getuid(), os.geteuid(), os.getpid()
    if uid <= 0 or uid != effective or pid <= 0:
        raise ValueError("scope UID/PID invalid")
    if os.getcwd() != ROOT or os.stat(ROOT).st_uid != uid:
        raise ValueError("scope source directory identity invalid")
    data = _read_virtual("/proc/self/cgroup", 4096)
    if not data.startswith(b"0::/") or not data.endswith(b"\n") or data.count(b"\n") != 1:
        raise ValueError("unified cgroup record invalid")
    group = data[3:-1].decode("ascii")
    if (
        not group.startswith(f"/user.slice/user-{uid}.slice/user@{uid}.service/")
        or not group.endswith("/" + unit)
        or any(part in ("", ".", "..") for part in group.split("/")[1:])
        or any(ord(c) < 33 or ord(c) > 126 or c == "\\" for c in group)
    ):
        raise ValueError("current cgroup is not the literal owned scope")
    base = "/sys/fs/cgroup" + group
    for name, expected in (
        ("memory.max", b"4294967296\n"),
        ("memory.swap.max", b"0\n"),
        ("cpu.max", b"100000 100000\n"),
        ("pids.max", b"256\n"),
    ):
        if _read_virtual(base + "/" + name, 128) != expected:
            raise ValueError("actual scope limit mismatch: " + name)
    members = _read_virtual(base + "/cgroup.procs", 65536).splitlines()
    if (
        not members
        or any(not item.isdigit() or item.startswith(b"0") for item in members)
        or str(pid).encode("ascii") not in members
    ):
        raise ValueError("own PID missing or malformed scope membership")
    # Other transient members may exit between reads; only this process is bound.
    return uid, effective, pid, group


def enter():
    """Validate actual current scope twice, then replace only with fixed make."""
    if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError("compiler entry forbidden under pytest")
    if sys.platform != "linux" or os.name != "posix":
        raise RuntimeError("compiler entry requires Linux")
    if sys.flags.isolated != 1 or sys.flags.no_site != 1 or sys.flags.dont_write_bytecode != 1 or sys.flags.optimize != 0:
        raise RuntimeError("compiler entry interpreter flags invalid")
    if len(sys.argv) != 3 or sys.argv[1] != "--unit":
        raise ValueError("compiler entry arguments invalid")
    unit = sys.argv[2]
    nonce = unit[len(UNIT_PREFIX) : -6]
    if (
        not unit.startswith(UNIT_PREFIX)
        or not unit.endswith(".scope")
        or len(nonce) != 24
        or any(c not in "0123456789abcdef" for c in nonce)
    ):
        raise ValueError("compiler entry nonce unit invalid")
    environment = {
        "HOME": "/home/yuchen7509",
        "USER": "yuchen7509",
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "protocol.allow",
        "GIT_CONFIG_VALUE_0": "never",
        "GIT_TERMINAL_PROMPT": "0",
        "CCACHE_DISABLE": "1",
        "MAKEFLAGS": "-j1",
    }
    before = _snapshot(unit)
    if _snapshot(unit) != before:
        raise ValueError("compiler scope identity changed before exec")
    os.execve("/usr/bin/make", ["/usr/bin/make", "-j1", "px4_sitl_default"], environment)


if __name__ == "__main__":
    enter()
