"""Fixed Windows once coordinator; SDK admission is independently primitive."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/target-bearing-runtime-freeze-v4-dev-1701"


def production_boundary():
    if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:
        raise ValueError("pytest production dispatch denied before effects")
    if sys.platform != "win32" or Path.cwd() != ROOT:
        raise ValueError("literal Windows project cwd required")


def admitted(value):
    return (
        type(value) is dict
        and type(value.get("windows_available")) is int
        and value["windows_available"] >= 1073741824
        and type(value.get("wsl_available")) is int
        and value["wsl_available"] >= 1073741824
        and value.get("competitor_count") == 0
        and type(value.get("competitor_count")) is int
        and value.get("docker_exit") == 0
        and value.get("docker_empty") is True
    )


def run_protocol(backend):
    """Actual lifecycle, also exercised with explicit inert I/O protocols."""
    primary = None
    process = None
    state = dict(state="PREPARING", consumed=False, child_exit=None, escaped_closure="UNKNOWN")
    try:
        first = backend.admission(1)
        backend.record("firstfacts", first)
        if not admitted(first):
            state["state"] = "REFUSED_UNCONSUMED"
            return state
        backend.prepare_identity()
        absence = backend.scope_absent()
        backend.record("scope-absence", absence)
        if absence.get("exit") != 0 or absence.get("absent") is not True:
            raise ValueError("nonzero/unknown unit absence is not admission")
        second = backend.admission(2)
        backend.record("secondfacts", second)
        if not admitted(second):
            state["state"] = "REFUSED_UNCONSUMED"
            return state
        backend.claim()
        state["consumed"] = True
        process = backend.start()
        state["state"] = "CHILD_STARTED"
        code = backend.finish(process)
        state["child_exit"] = code
        if code != 0:
            raise ValueError("actual SDK child nonzero")
        backend.postverify()
        state["state"] = "CHILD_ZERO_STATIC_AUDIT_PENDING"
    except BaseException as exc:
        primary = exc
        state["error"] = repr(exc)
        state["state"] = "FAILED"
    finally:
        if process is not None:
            try:
                backend.cleanup(process)
            except BaseException as exc:
                if primary is None:
                    primary = exc
                else:
                    primary.add_note("own Popen cleanup secondary: " + repr(exc))
            try:
                state["release"] = backend.release()
            except BaseException as exc:
                if primary is None:
                    primary = exc
                else:
                    primary.add_note("owned scope release secondary: " + repr(exc))
        if primary is not None:
            state.update(state="FAILED", error=repr(primary))
        try:
            backend.record("completion", state)
        except BaseException as exc:
            if primary is None:
                primary = exc
            else:
                primary.add_note("completion persistence secondary: " + repr(exc))
            state.update(state="FAILED", error=repr(primary))
            try:
                backend.completion_fallback(dict(state, completion_persisted=False, persistence_error=repr(exc)))
            except BaseException as fallback:
                primary.add_note("independent completion fallback unavailable;durability UNKNOWN: " + repr(fallback))
        if primary is not None:
            raise primary
    return state


def native_backend():
    return NativeWindowsBackend()


def execute_once():
    production_boundary()
    # Task4's exact recipe and remaining low-level/control validation are not
    # complete. Source-only partial publication never enables a native attempt.
    raise ValueError("Task4 exact recipe and remaining control/observer audit pending;dispatch unavailable")
    return run_protocol(native_backend())


def native_path(path):
    value = Path(path).absolute().as_posix()
    if len(value) < 3 or value[1:3] != ":/":
        raise ValueError("drive-rooted Windows path required")
    return "/mnt/" + value[0].lower() + value[2:]


class NativeWindowsBackend:
    def __init__(self):
        # This constructor is reached only after the public boundary. A reviewed
        # literal recipe handoff is required; software fixtures never create it.
        import json

        from tools.benchmark.static_v4_identity import decode_primitive

        self.json = json
        self.process = None
        self.pre = None
        self.streams = []
        self.template_path = ROOT / "results/static-v4-executor-production-dev-1701/reviewed-recipe.frame"
        self.template = decode_primitive(self.template_path.read_bytes())
        from tools.benchmark.static_v4_identity import require, sha256

        publication = json.loads((ROOT / "evidence/static-v4-executor-production-publication.json").read_bytes())
        require(
            publication["reviewed_recipe_sha256"] == sha256(self.template_path.read_bytes()),
            "literal published software recipe differs",
        )
        self.source_snapshot = self.sources()
        require(
            self.template["source_root"] == native_path(ROOT) and self.template["source_sha256"] == self.source_snapshot,
            "current full source/recipe differs",
        )
        self.recipe = dict(self.template, nonce=os.urandom(32).hex())
        self.recipe["unit"] = "fly-calibration-prepare-" + self.recipe["nonce"][:24] + ".scope"
        self.unit = self.recipe["unit"]
        self.control = None

    def sources(self):
        import hashlib

        selected = [OUT / "run-static-preparation-v4.py"]
        for part in ("src/flydrones", "tools/benchmark", "tools/connectome"):
            selected.extend(p for p in (ROOT / part).rglob("*.py") if "__pycache__" not in p.parts)
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(selected))}

    def record(self, name, value):
        with (OUT / (name + ".json")).open("x", encoding="utf8") as f:
            self.json.dump(value, f, indent=2)

    def remote(self, args, timeout=15):
        import subprocess

        return subprocess.run(["wsl", "-d", "Ubuntu", "--", *args], cwd=ROOT, capture_output=True, timeout=timeout)

    def admission(self, number):
        import ast
        import hashlib

        import psutil

        from tools.benchmark.run_openvins_dataset_consumer import heavy_process

        code = "import os;v=open('/proc/meminfo').read();a=int(next(x.split()[1] for x in v.splitlines() if x.startswith('MemAvailable:')))*1024;rows=[]\nfor n in os.listdir('/proc'):\n if not n.isdigit():continue\n try:rows.append(dict(pid=int(n),name=open('/proc/'+n+'/comm').read().strip(),cmdline=open('/proc/'+n+'/cmdline','rb').read().replace(b'\\0',b' ').decode(errors='replace')))\n except OSError:pass\nprint(repr(dict(available=a,rows=rows)))"
        row = self.remote(["/usr/bin/python3", "-S", "-c", code], 30)
        if row.returncode:
            raise ValueError("fresh Linux admission snapshot failed")
        linux = ast.literal_eval(row.stdout.decode())
        own = {os.getpid(), *(p.pid for p in psutil.Process().parents())}
        win = [dict(pid=p.pid, **p.info) for p in psutil.process_iter(["name", "cmdline"]) if p.pid not in own]
        blocked = [p for p in win + linux["rows"] if heavy_process(p)]
        docker = self.remote_docker()
        # Full inventories stay private. Public facts contain counters/hash/size.
        private = self.json.dumps(
            dict(windows=win, linux=linux, docker_stdout_hex=docker.stdout.hex()), ensure_ascii=False
        ).encode()
        path = OUT / ("LOCAL_UNPUBLISHED-admission-" + str(number) + ".json")
        with path.open("xb") as f:
            f.write(private)
        return dict(
            windows_available=psutil.virtual_memory().available,
            wsl_available=linux["available"],
            competitor_count=len(blocked),
            docker_exit=docker.returncode,
            docker_empty=not docker.stdout.strip(),
            private_bytes=len(private),
            private_sha256=hashlib.sha256(private).hexdigest(),
        )

    def remote_docker(self):
        import subprocess

        return subprocess.run(["docker", "ps", "--no-trunc", "--format", "{{json .}}"], cwd=ROOT, capture_output=True, timeout=15)

    def prepare_identity(self):
        from tools.benchmark.static_v4_identity import audit_preidentity, decode_primitive, encode_primitive

        with (OUT / "recipe.frame").open("xb") as f:
            f.write(encode_primitive(self.recipe))
        row = self.remote(
            [
                "/usr/bin/timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "30s",
                "/usr/bin/python3",
                "-S",
                native_path(ROOT / "tools/benchmark/static_v4_identity.py"),
                "--observe-fixed-pre",
            ],
            45,
        )
        self.record("preidentity-command", dict(exit=row.returncode, stdout_hex=row.stdout.hex(), stderr_hex=row.stderr.hex()))
        if row.returncode:
            raise ValueError("actual primitive preidentity failed")
        self.pre = decode_primitive((OUT / "preidentity.frame").read_bytes())
        audit_preidentity(self.pre, recipe=self.recipe)
        self.control = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/" + str(self.pre["uid"])}
        if self.sources() != self.source_snapshot:
            raise ValueError("source changed after native preidentity")

    def manager(self, args):
        if self.control is None:
            raise ValueError("own UID manager environment unknown")
        return self.remote(
            ["/usr/bin/env", "-i", *[k + "=" + v for k, v in self.control.items()], "/usr/bin/systemctl", "--user", *args]
        )

    def scope_absent(self):
        r = self.manager(["show", self.unit, "--property=LoadState", "--property=InvocationID", "--property=ControlGroup"])
        text = r.stdout.decode()
        expected = {"LoadState=not-found", "InvocationID=", "ControlGroup="}
        return dict(
            exit=r.returncode,
            absent=r.returncode == 0 and set(text.splitlines()) == expected and not r.stderr,
            stdout_hex=r.stdout.hex(),
            stderr_hex=r.stderr.hex(),
        )

    def claim(self):
        from tools.benchmark.static_v4_identity import encode_primitive, sha256

        if (OUT / "sdk-start.frame").exists() or (OUT / "frozen-study-v4").exists():
            raise FileExistsError("SDK/study already consumed")
        value = dict(
            schema="static-claim-v4",
            nonce=self.recipe["nonce"],
            unit=self.unit,
            recipe_sha256=sha256(encode_primitive(self.recipe)),
            preidentity_sha256=sha256((OUT / "preidentity.frame").read_bytes()),
            source_root=native_path(ROOT),
        )
        with (OUT / "claim.frame").open("xb") as f:
            f.write(encode_primitive(value))

    def start(self):
        import subprocess

        args = [
            "wsl",
            "-d",
            "Ubuntu",
            "--",
            "/usr/bin/env",
            "-i",
            *[k + "=" + v for k, v in self.control.items()],
            "/usr/bin/systemd-run",
            "--user",
            "--scope",
            "--unit=" + self.unit,
            "-p",
            "MemoryMax=536870912",
            "-p",
            "MemorySwapMax=0",
            "-p",
            "CPUQuota=100%",
            "-p",
            "TasksMax=64",
            "-p",
            "RuntimeMaxSec=210s",
            "/usr/bin/env",
            "-i",
            *[k + "=" + v for k, v in self.recipe["sdk_environment"].items()],
            "/usr/bin/timeout",
            "--signal=TERM",
            "--kill-after=10s",
            "180s",
            "/usr/bin/python3",
            "-S",
            native_path(ROOT / "tools/benchmark/static_v4_bootstrap.py"),
            "--admitted-once",
        ]
        self.record("actual-command", dict(argv=args, cwd=str(ROOT), launcher_budget_s=240))
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self.process

    def finish(self, process):
        import threading
        import time

        errors = []

        def drain(pipe, name):
            count = 0
            try:
                with (OUT / name).open("xb") as f:
                    while data := pipe.read(65536):
                        count += len(data)
                        if count > 2 * 1024**2:
                            raise ValueError("launcher hard stream cap")
                        if f.write(data) != len(data):
                            raise OSError("short launcher output write")
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=drain, args=(pipe, name), daemon=True)
            for pipe, name in ((process.stdout, "launcher.stdout"), (process.stderr, "launcher.stderr"))
        ]
        for t in threads:
            t.start()
        start = time.monotonic()
        while process.poll() is None:
            if errors:
                raise errors[0]
            if time.monotonic() - start >= 240:
                raise TimeoutError("240s own launcher deadline")
            time.sleep(0.02)
        code = process.wait(timeout=5)
        for t in threads:
            t.join(timeout=5)
        if errors:
            raise errors[0]
        if any(t.is_alive() for t in threads):
            raise ValueError("launcher pipe reader incomplete")
        from tools.benchmark.static_v4_identity import encode_primitive, sha256

        child = dict(
            schema="static-child-exit-v4", exit=code, waited=True, claim_sha256=sha256((OUT / "claim.frame").read_bytes())
        )
        with (OUT / "child-exit.frame").open("xb") as stream:
            stream.write(encode_primitive(child))
        return code

    def cleanup(self, process):
        from subprocess import TimeoutExpired

        for operation in ("terminate", "kill"):
            if process.poll() is not None:
                break
            try:
                getattr(process, operation)()
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except TimeoutExpired:
                continue
        if process.poll() is None:
            raise ValueError("own Windows Popen wait unavailable;escapedUNKNOWN")

    def release(self):
        # Stop only the currently matching actual Invocation/CG. No guessed PID.
        from tools.benchmark.static_v4_identity import decode_primitive

        path = OUT / "bootstrap-scope-before.frame"
        if not path.is_file():
            return dict(owned_group_released=None, escaped_closure="UNKNOWN")
        old = decode_primitive(path.read_bytes())
        r = self.manager(["show", self.unit, "--property=InvocationID", "--property=ControlGroup", "--property=LoadState"])
        if r.returncode or r.stderr:
            raise ValueError("actual own scope release observation failed")
        props = dict(line.split("=", 1) for line in r.stdout.decode().splitlines())
        if props.get("LoadState") == "not-found":
            return dict(owned_group_released=None, unit_not_found=True, escaped_closure="UNKNOWN")
        if props.get("InvocationID") != old["InvocationID"] or props.get("ControlGroup") != old["ControlGroup"]:
            raise ValueError("fresh Invocation/CG mismatch;unitstop forbidden")
        stopped = self.manager(["stop", self.unit])
        self.record(
            "matching-unit-stop", dict(exit=stopped.returncode, stdout_hex=stopped.stdout.hex(), stderr_hex=stopped.stderr.hex())
        )
        if stopped.returncode:
            raise ValueError("owned matching unit stop failed")
        return dict(owned_group_released=None, matching_stop_exit=0, escaped_closure="UNKNOWN")

    def postverify(self):
        # This literal receiver must implement the complete finished graph/native
        # postidentity transport before any study can be accepted.
        import hashlib

        from tools.benchmark.static_v4_identity import acquire_finished_study

        path = OUT / "frozen-study-v4/study.json"
        return acquire_finished_study(str(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def completion_fallback(self, value):
        # Independent exclusive file, never overwrite the failed canonical record.
        import json

        data = json.dumps(value, ensure_ascii=False).encode("utf8")
        if len(data) > 65536:
            raise ValueError("completion fallback bound")
        with (OUT / "completion-fallback.json").open("xb") as stream:
            if stream.write(data) != len(data):
                raise OSError("short completion fallback")
            stream.flush()
            os.fsync(stream.fileno())
