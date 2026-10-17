import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.benchmark.software_process_boundary import install

UNIT = "flydrones-px4-status-build-v1-" + "a" * 24 + ".scope"
CG = "/user.slice/user-1000.slice/user@1000.service/app.slice/" + UNIT
ROOT = "/home/yuchen7509/px4-status-worktrees/firmware-v1"


@pytest.fixture(autouse=True)
def inert_children(monkeypatch):
    install(monkeypatch)


def entry():
    return importlib.import_module("tools.connectome.px4_firmware_scope_entry_v2")


def runner():
    return importlib.import_module("tools.connectome.run_px4_status_firmware_build_v2")


class ReachedExec(BaseException):
    pass


def protocol(monkeypatch):
    module = entry()
    events = []
    files = {
        "/proc/self/cgroup": ("0::" + CG + "\n").encode(),
        "/sys/fs/cgroup" + CG + "/memory.max": b"4294967296\n",
        "/sys/fs/cgroup" + CG + "/memory.swap.max": b"0\n",
        "/sys/fs/cgroup" + CG + "/cpu.max": b"100000 100000\n",
        "/sys/fs/cgroup" + CG + "/pids.max": b"256\n",
        "/sys/fs/cgroup" + CG + "/cgroup.procs": b"73\n74\n",
    }
    fds = {}

    def op(path, flags):
        events.append(("open", path, flags))
        fd = len(fds) + 10
        fds[fd] = [files[path], 0]
        return fd

    def read(fd, n):
        data, at = fds[fd]
        part = data[at : at + n]
        fds[fd][1] += len(part)
        return part

    def execute(path, argv, env):
        events.append(("exec", path, argv, env))
        raise ReachedExec

    fake = SimpleNamespace(
        name="posix",
        environ={},
        O_RDONLY=0,
        O_CLOEXEC=1,
        O_NOFOLLOW=2,
        O_NONBLOCK=4,
        open=op,
        read=read,
        close=lambda fd: events.append(("close", fd)),
        getcwd=lambda: ROOT,
        getuid=lambda: 1000,
        geteuid=lambda: 1000,
        getpid=lambda: 73,
        stat=lambda path: SimpleNamespace(st_uid=1000),
        execve=execute,
    )
    fake_sys = SimpleNamespace(
        platform="linux",
        argv=["entry", "--unit", UNIT],
        modules={},
        flags=SimpleNamespace(isolated=1, no_site=1, dont_write_bytecode=1, optimize=0),
    )
    monkeypatch.setattr(module, "os", fake)
    monkeypatch.setattr(module, "sys", fake_sys)
    return module, fake, fake_sys, files, events


def test_actual_dispatch_command_routes_through_entry_and_declares_zero_swap_tasks():
    module = runner()
    argv = module.build_scope_command()
    assert "--property=MemorySwapMax=0" in argv
    assert "--property=TasksMax=256" in argv
    at = argv.index("/usr/bin/python3")
    assert argv[at:] == ["/usr/bin/python3", "-I", "-S", "-B", module.SCOPE_ENTRY_WSL, "--unit", module.BUILD_SCOPE_UNIT]
    assert "--property=MemoryMax=4G" in argv and "--property=CPUQuota=100%" in argv
    assert "5400s" in argv and argv.index("5400s") < at
    assert "/usr/bin/make" not in argv
    assert module.BUILD_RESULT_PATH == "/home/yuchen7509/px4-status-worktrees/status-build-v1"


def test_valid_actual_scope_protocol_reaches_only_fixed_make_with_clean_environment(monkeypatch):
    module, fake, _, _, events = protocol(monkeypatch)
    fake.environ["LD_PRELOAD"] = "untrusted"
    with pytest.raises(ReachedExec):
        module.enter()
    executed = [e for e in events if e[0] == "exec"]
    assert len(executed) == 1
    _, path, argv, env = executed[0]
    assert path == "/usr/bin/make" and argv == [path, "-j1", "px4_sitl_default"]
    assert env["MAKEFLAGS"] == "-j1" and env["GIT_CONFIG_VALUE_0"] == "never"
    assert "LD_PRELOAD" not in env
    assert sum(e[:2] == ("open", "/proc/self/cgroup") for e in events) == 2


@pytest.mark.parametrize(
    "name,value",
    [
        ("memory.max", b"max\n"),
        ("memory.swap.max", b"1\n"),
        ("cpu.max", b"max 100000\n"),
        ("pids.max", b"max\n"),
        ("cgroup.procs", b"74\n"),
    ],
)
def test_wrong_actual_scope_limit_or_membership_never_executes(monkeypatch, name, value):
    module, _, _, files, events = protocol(monkeypatch)
    files["/sys/fs/cgroup" + CG + "/" + name] = value
    with pytest.raises((ValueError, RuntimeError)):
        module.enter()
    assert not any(e[0] == "exec" for e in events)


@pytest.mark.parametrize("change", ["pytest", "flags", "cwd", "uid", "owner", "unit", "platform"])
def test_invalid_entry_context_rejected_before_exec(monkeypatch, change):
    module, fake, sy, _, events = protocol(monkeypatch)
    if change == "pytest":
        sy.modules["pytest"] = object()
    elif change == "flags":
        sy.flags.isolated = 0
    elif change == "cwd":
        fake.getcwd = lambda: "/tmp"
    elif change == "uid":
        fake.geteuid = lambda: 0
    elif change == "owner":
        fake.stat = lambda path: SimpleNamespace(st_uid=0)
    elif change == "unit":
        sy.argv[-1] = "other.scope"
    elif change == "platform":
        sy.platform = "win32"
    with pytest.raises((ValueError, RuntimeError)):
        module.enter()
    assert not any(e[0] == "exec" for e in events)
    if change in ("pytest", "flags", "unit", "platform"):
        assert not events


@pytest.mark.parametrize("change", ["cgroup", "memory", "pid", "uid", "cwd"])
def test_second_scope_observation_drift_never_executes(monkeypatch, change):
    module, fake, _, files, events = protocol(monkeypatch)
    original = fake.open
    for path, data in list(files.items()):
        if path.startswith("/sys/fs/cgroup"):
            files[path.replace("app.slice", "other.slice")] = data
    reads = 0

    def opening(path, flags):
        nonlocal reads
        if path == "/proc/self/cgroup":
            reads += 1
            if reads == 2:
                if change == "cgroup":
                    files[path] = ("0::" + CG.replace("app.slice", "other.slice") + "\n").encode()
                elif change == "memory":
                    files["/sys/fs/cgroup" + CG + "/memory.max"] = b"max\n"
                elif change == "pid":
                    fake.getpid = lambda: 74
                elif change == "uid":
                    fake.getuid = lambda: 0
                elif change == "cwd":
                    fake.getcwd = lambda: "/tmp"
        return original(path, flags)

    # Change identity between whole snapshots, before the second UID/cwd read.
    old_close = fake.close

    def closing(fd):
        old_close(fd)
        if reads == 1 and sum(e[0] == "close" for e in events) == 6:
            if change == "pid":
                fake.getpid = lambda: 74
            elif change == "uid":
                fake.getuid = lambda: 0
            elif change == "cwd":
                fake.getcwd = lambda: "/tmp"

    fake.open = opening
    fake.close = closing
    with pytest.raises((ValueError, RuntimeError)):
        module.enter()
    assert not any(e[0] == "exec" for e in events)


@pytest.mark.parametrize("failure", ["denied", "oversize", "read", "close"])
def test_virtual_file_failure_closes_and_never_executes(monkeypatch, failure):
    module, fake, _, files, events = protocol(monkeypatch)
    if failure == "denied":
        fake.open = lambda *_: (_ for _ in ()).throw(PermissionError("denied"))
    elif failure == "oversize":
        files["/proc/self/cgroup"] = b"x" * 4097
    elif failure == "read":
        fake.read = lambda *_: (_ for _ in ()).throw(OSError("read failure"))
    elif failure == "close":
        fake.close = lambda *_: (_ for _ in ()).throw(OSError("close failure"))
    with pytest.raises((OSError, ValueError)):
        module.enter()
    assert not any(e[0] == "exec" for e in events)
    if failure in ("oversize", "read"):
        assert any(e[0] == "close" for e in events)


def test_virtual_read_primary_error_is_not_hidden_by_close_error(monkeypatch):
    module, fake, _, _, _ = protocol(monkeypatch)
    fake.read = lambda *_: (_ for _ in ()).throw(PermissionError("primary read"))
    fake.close = lambda *_: (_ for _ in ()).throw(OSError("secondary close"))
    with pytest.raises(PermissionError, match="primary read"):
        module.enter()


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"0::/wrong\n",
        b"1:cpu:/x\n",
        ("0::" + CG + "\n0::" + CG + "\n").encode(),
        ("0::" + CG.replace("app.slice", "..") + "\n").encode(),
    ],
)
def test_malformed_or_unowned_group_never_executes(monkeypatch, data):
    module, _, _, files, events = protocol(monkeypatch)
    files["/proc/self/cgroup"] = data
    with pytest.raises(ValueError):
        module.enter()
    assert not any(e[0] == "exec" for e in events)


def dispatch_protocol(monkeypatch, tmp_path, *, drift=False):
    module = runner()
    source = Path(module.SCOPE_ENTRY).read_bytes()
    owned = tmp_path / "entry.py"
    owned.write_bytes(source)
    monkeypatch.setattr(module, "SCOPE_ENTRY", owned)
    monkeypatch.setattr(module, "BUILD_EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(module, "LEGACY_BUILD_EVIDENCE_DIR", tmp_path / "legacy-evidence")
    profile = json.loads(module.ROOT.joinpath("configs/px4/estimator-status-firmware-build-profile.json").read_text())
    facts = dict(
        profile,
        source_prepared=True,
        result_path=module.BUILD_RESULT_PATH,
        result_path_exists=False,
        windows_available_bytes=module.MIN_WINDOWS,
        wsl_available_bytes=module.MIN_WSL,
        disk_free_bytes=module.MIN_DISK,
        process_scan_complete=True,
        competitors=[],
        scope_observed_inside=True,
        run_count=0,
        source_observation={"facts": {"owned": "inert software protocol"}},
    )
    absent = dict(load_state="not-found", active_state="inactive", control_group="", invocation_id="")
    active = dict(
        load_state="loaded",
        active_state="active",
        control_group=CG.replace(UNIT, module.BUILD_SCOPE_UNIT),
        invocation_id="b" * 32,
    )
    states = iter([absent, active, absent, absent])
    monkeypatch.setattr(module, "_show_build_unit", lambda **kwargs: next(states))
    calls = []

    def wsl(*args, **kwargs):
        calls.append(args)
        assert args[0] in ("test", "mkdir")
        return SimpleNamespace(returncode=1 if args[0] == "test" else 0)

    monkeypatch.setattr(module, "_wsl", wsl)
    monkeypatch.setattr(
        module,
        "_toolchain_snapshot",
        lambda: dict(files=dict(module.EXPECTED_TOOLCHAIN_FILES), modules=module.EXPECTED_TOOLCHAIN_MODULES),
    )
    monkeypatch.setattr(
        module,
        "_build_tree_snapshot",
        lambda: dict(status=" M src/modules/uxrce_dds_client/dds_topics.yaml\n", build_exists=False, build_symlink=False),
    )
    monkeypatch.setattr(
        module,
        "_read_cgroup",
        lambda group, **kwargs: dict(
            path="/sys/fs/cgroup" + group,
            members=["73"],
            memory_max=module.SCOPE_MEMORY,
            cpu_max=module.SCOPE_CPU,
            swap_max=0,
            tasks_max=256,
        ),
    )

    class Process:
        pid = 73
        returncode = 0

        def __init__(self, command, **kwargs):
            calls.append(("launch", command))
            self.polls = 0
            if drift:
                owned.write_bytes(source + b"# changed during inert launcher\n")

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else 0

    monkeypatch.setattr(module.subprocess, "Popen", Process)
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)
    return module, profile, facts, owned, calls


@pytest.mark.parametrize("drift", [False, True])
def test_actual_dispatch_persists_entry_pin_and_detects_postlaunch_drift(monkeypatch, tmp_path, drift):
    module, profile, facts, _, calls = dispatch_protocol(monkeypatch, tmp_path, drift=drift)
    result = module._dispatch_approved(profile, facts, facts)
    assert result["build_dispatched"] is True  # launcher only, in this test inert
    assert result["entry_unchanged"] is (not drift)
    assert result["owned_scope_released"] is True
    assert any(call[0] == "launch" for call in calls)
    saved = json.loads((module.BUILD_EVIDENCE_DIR / "dispatch-result.json").read_text())
    assert saved == result
    assert any("entry_post_unknown_or_changed" in e for e in result["errors"]) is drift
    assert (
        json.loads((module.BUILD_EVIDENCE_DIR / "preflight.json").read_text())["entry_before"]["sha256"]
        == module.SCOPE_ENTRY_SHA256
    )


def test_changed_entry_bytes_refuse_before_any_scope_query_or_output(monkeypatch, tmp_path):
    module, profile, facts, owned, calls = dispatch_protocol(monkeypatch, tmp_path)
    owned.write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        module._dispatch_approved(profile, facts, facts)
    assert calls == [] and not module.BUILD_EVIDENCE_DIR.exists()


def test_runner_main_rejects_pytest_before_profile_or_query(monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "_pin_entry", lambda: pytest.fail("pin IO before context rejection"))
    with pytest.raises(RuntimeError, match="under pytest"):
        module.main(["--execute-once", "--profile", "absent"])


@pytest.mark.parametrize("swap,tasks", [("0", "256"), ("1", "256"), ("0", "max")])
def test_actual_external_scope_reader_also_requires_swap_and_task_limits(monkeypatch, swap, tasks):
    module = runner()
    group = CG.replace(UNIT, module.BUILD_SCOPE_UNIT)
    values = {
        "cgroup.procs": "73\n",
        "memory.max": "4294967296",
        "cpu.max": "100000 100000",
        "memory.peak": "1024",
        "memory.swap.max": swap,
        "pids.max": tasks,
    }
    monkeypatch.setattr(module, "_wsl", lambda command, path, **kwargs: SimpleNamespace(stdout=values[path.rsplit("/", 1)[1]]))
    if swap == "0" and tasks == "256":
        actual = module._read_cgroup(group)
        assert actual["swap_max"] == 0 and actual["tasks_max"] == 256
    else:
        with pytest.raises(ValueError):
            module._read_cgroup(group)


@pytest.mark.parametrize("swap,tasks", [("0", "256"), ("1", "256"), ("0", "max")])
def test_scope_admission_probe_requires_new_limits_without_running_it(monkeypatch, swap, tasks):
    module = runner()
    calls = []

    def observed(*args):
        calls.append(args)
        return SimpleNamespace(
            stdout=json.dumps(
                dict(group="/user.slice/run-inert.scope", memory="4294967296", cpu="100000 100000", swap=swap, tasks=tasks)
            )
        )

    monkeypatch.setattr(module, "_wsl", observed)
    verified, memory, cpu = module._scope_facts()
    assert verified is (swap == "0" and tasks == "256")
    assert memory == 4294967296 and cpu == "100000 100000"
    assert "MemorySwapMax=0" in calls[0] and "TasksMax=256" in calls[0]


def test_cold_primitive_definition_imports_only_os_sys_and_does_no_io(monkeypatch):
    module, fake, sy, _, events = protocol(monkeypatch)
    code = Path(module.__file__).read_text()
    imported = []

    def importing(name, *args):
        imported.append(name)
        return {"os": fake, "sys": sy}[name]

    builtins = dict(vars(__import__("builtins")), __import__=importing)
    exec(compile(code, "owned-primitive-source", "exec"), {"__builtins__": builtins, "__name__": "inert_import"})
    assert imported == ["os", "sys"] and events == []
    sy.modules["pytest"] = object()
    with pytest.raises(RuntimeError, match="under pytest"):
        exec(compile(code, "owned-primitive-source", "exec"), {"__builtins__": builtins, "__name__": "__main__"})
    assert events == []


def test_prior_v1_evidence_consumption_refuses_new_dispatch_before_queries(monkeypatch, tmp_path):
    module, profile, facts, _, calls = dispatch_protocol(monkeypatch, tmp_path)
    legacy = tmp_path / "original-v1-evidence"
    legacy.mkdir()
    monkeypatch.setattr(module, "LEGACY_BUILD_EVIDENCE_DIR", legacy, raising=False)
    with pytest.raises(FileExistsError):
        module._dispatch_approved(profile, facts, facts)
    assert calls == [] and not module.BUILD_EVIDENCE_DIR.exists()


def test_prior_v1_evidence_consumption_refuses_before_admission_collector(monkeypatch, tmp_path):
    module, profile, _, _, _ = dispatch_protocol(monkeypatch, tmp_path)
    legacy = tmp_path / "original-v1-evidence"
    legacy.mkdir()
    monkeypatch.setattr(module, "LEGACY_BUILD_EVIDENCE_DIR", legacy, raising=False)
    with pytest.raises(FileExistsError):
        module.execute_once(profile, collect=lambda *_: pytest.fail("collector called after consumption"))


def test_launcher_fallback_read_is_bounded_before_allocation(monkeypatch, tmp_path):
    module = runner()
    path = tmp_path / "stderr.bin"
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    actual_open = Path.open
    sizes = []

    class Reader:
        def __enter__(self):
            self.file = actual_open(path, "rb")
            return self

        def __exit__(self, *args):
            self.file.close()

        def read(self, size=-1):
            sizes.append(size)
            return self.file.read(size)

    monkeypatch.setattr(Path, "open", lambda self, *a, **kw: Reader() if self == path else actual_open(self, *a, **kw))
    assert module._recorded_launcher_invocation_id(path) is None
    assert sizes and all(0 <= size <= 1024 * 1024 + 1 for size in sizes)


def test_active_monitor_passes_one_deadline_to_each_observation(monkeypatch, tmp_path):
    module, profile, facts, _, _ = dispatch_protocol(monkeypatch, tmp_path)
    old_show, old_read = module._show_build_unit, module._read_cgroup
    shows, reads = [], []

    def show(**kwargs):
        shows.append(kwargs.get("deadline"))
        return old_show()

    def read(group, **kwargs):
        reads.append(kwargs.get("deadline"))
        return old_read(group)

    monkeypatch.setattr(module, "_show_build_unit", show)
    monkeypatch.setattr(module, "_read_cgroup", read)
    result = module._dispatch_approved(profile, facts, facts)
    assert result["build_exit_code"] == 0
    assert isinstance(shows[1], float) and reads == [shows[1]]


@pytest.mark.parametrize("remaining", [2.5, 0.0, -1.0])
def test_monitor_subprocess_uses_remaining_budget_or_refuses(monkeypatch, remaining):
    module = runner()
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 10.0))
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    if remaining > 0:
        module._wsl("inert-command", deadline=10.0 + remaining)
        assert calls[0]["timeout"] == remaining
    else:
        with pytest.raises(module.subprocess.TimeoutExpired):
            module._wsl("inert-command", deadline=10.0 + remaining)
        assert calls == []


def test_active_monitor_sleep_is_capped_by_remaining_budget(monkeypatch, tmp_path):
    module, profile, facts, _, _ = dispatch_protocol(monkeypatch, tmp_path)
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
    original = module._read_cgroup

    def read(group, **kwargs):
        now[0] = 5399.75
        return original(group)

    monkeypatch.setattr(module, "_read_cgroup", read)
    module._dispatch_approved(profile, facts, facts)
    assert sleeps == [0.25]


def test_dangling_legacy_evidence_entry_also_refuses_before_queries(monkeypatch, tmp_path):
    module, profile, facts, _, calls = dispatch_protocol(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "LEGACY_BUILD_EVIDENCE_DIR", SimpleNamespace(exists=lambda: False, is_symlink=lambda: True))
    with pytest.raises(FileExistsError):
        module._dispatch_approved(profile, facts, facts)
    assert calls == [] and not module.BUILD_EVIDENCE_DIR.exists()
