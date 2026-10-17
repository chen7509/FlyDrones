"""Fixed Windows once coordinator; SDK admission is independently primitive."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/target-bearing-runtime-freeze-v4-dev-1701"


def bounded_windows_command(argv, *, cwd, timeout, popen=None, clock=None):
    """Owned raw pipes; partial bytes, deadline and bounded own wait retained."""
    import datetime
    import subprocess
    import threading
    import time

    if popen is None:
        production_boundary()
        popen = subprocess.Popen
    clock = time if clock is None else clock
    start = clock.monotonic()
    started_utc = datetime.datetime.now(datetime.UTC).isoformat()
    process, code, primary = None, None, None
    buffers, errors, threads, done = [bytearray(), bytearray()], [], [], [False, False]
    waited = False
    notes = []

    def drain(pipe, number):
        try:
            while data := pipe.read(65536):
                room = 2 * 1024**2 - len(buffers[number])
                buffers[number].extend(data[:room])
                if len(data) > room:
                    raise ValueError("metadata hard stream cap")
            done[number] = True
        except BaseException as exc:
            errors.append(exc)

    try:
        process = popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        for number, pipe in enumerate((process.stdout, process.stderr)):
            thread = threading.Thread(target=drain, args=(pipe, number), daemon=True)
            threads.append(thread)
            thread.start()
        while process.poll() is None:
            if errors:
                raise errors[0]
            if clock.monotonic() - start >= timeout:
                raise TimeoutError("metadata owned deadline exceeded")
            clock.sleep(0.01)
        code = process.wait(timeout=5)
        waited = True
        for thread in threads:
            thread.join(timeout=max(0, min(5, timeout - (clock.monotonic() - start))))
        if errors:
            raise errors[0]
        if any(thread.is_alive() for thread in threads):
            raise ValueError("metadata reader incomplete")
    except BaseException as exc:
        primary = exc
    finally:
        if process is not None and not waited:
            for operation in ("terminate", "kill"):
                try:
                    if process.poll() is None:
                        getattr(process, operation)()
                    code = process.wait(timeout=5)
                    waited = True
                    break
                except subprocess.TimeoutExpired:
                    continue
                except BaseException as exc:
                    notes.append(repr(exc))
            if not waited:
                notes.append("owned metadata wait unavailable;escapedUNKNOWN")
        if process is not None:
            for pipe in (process.stdout, process.stderr):
                try:
                    pipe.close()
                except BaseException as exc:
                    notes.append(repr(exc))
        for thread in threads:
            thread.join(timeout=0)
        if any(thread.is_alive() for thread in threads):
            notes.append("owned metadata reader unavailable;escapedUNKNOWN")
        if primary is None and notes:
            primary = ValueError(notes[0])
    return dict(
        argv=list(argv),
        cwd=str(cwd),
        started_utc=started_utc,
        ended_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        elapsed_s=clock.monotonic() - start,
        deadline_s=timeout,
        stdout_hex=bytes(buffers[0]).hex(),
        stderr_hex=bytes(buffers[1]).hex(),
        exit=code,
        error=repr(primary) if primary else None,
        reader_complete=all(done),
        cleanup=dict(waited=waited, notes=notes, escaped_closure="UNKNOWN"),
    )


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
            state["state"] = (
                "REFUSED_CONSUMED_PREIDENTITY" if getattr(backend, "consumed", False) is True else "REFUSED_UNCONSUMED"
            )
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
        state["consumed"] = state["consumed"] or getattr(backend, "consumed", False) is True
        if process is None:
            try:
                process = getattr(backend, "process", None)
            except BaseException as exc:
                if primary is None:
                    primary = exc
                else:
                    primary.add_note("owned handle retrieval secondary: " + repr(exc))
        if process is not None:
            try:
                state["own_cleanup"] = backend.cleanup(process)
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
    load_windows_software_release()
    return run_protocol(native_backend())


def load_windows_software_release():
    import hashlib
    import zipfile

    from tools.benchmark.static_v4_identity import audit_software_release, decode_primitive

    try:
        raw = (ROOT / "evidence/static-v4-executor-completion-release.frame").read_bytes()
        payload = (ROOT / "results/static-v4-executor-completion-dev-1701/reviewed-recipe.frame").read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("Task4 exact recipe/full software review and seal pending;native dispatch unavailable") from exc
    if len(raw) > 16 * 1024**2 or len(payload) > 16 * 1024**2:
        raise ValueError("bounded software handoff required")
    release = decode_primitive(raw)
    request = audit_software_release(release, payload)
    if request["source_root"] != native_path(ROOT) or request["source_sha256"] != NativeWindowsBackend.sources(None):
        raise ValueError("released full source/root differs from current source")
    for relative, expected in (
        (release["archive"], release["archive_sha256"]),
        ("results/static-v4-executor-completion-dev-1701/independent-review.md", release["review_sha256"]),
        ("results/static-v4-executor-completion-dev-1701/executor-fix-pass.md", release["fixpass_sha256"]),
    ):
        digest = hashlib.sha256()
        with (ROOT / relative).open("rb") as stream:
            while data := stream.read(65536):
                digest.update(data)
        if digest.hexdigest() != expected:
            raise ValueError("literal reviewed software artifact changed")
    with zipfile.ZipFile(ROOT / release["archive"]) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("duplicate software archive members")
        member = "results/static-v4-executor-completion-dev-1701/reviewed-recipe.frame"
        if archive.getinfo(member).file_size > 16 * 1024**2 or archive.read(member) != payload:
            raise ValueError("archived exact recipe bytes differ")
        for name in ("independent-review.md", "executor-fix-pass.md"):
            member = "results/static-v4-executor-completion-dev-1701/" + name
            if archive.getinfo(member).file_size > 16 * 1024**2 or archive.read(member) != (ROOT / member).read_bytes():
                raise ValueError("archived review/fix bytes differ")
    return release, request


def native_path(path):
    value = Path(path).absolute().as_posix()
    if len(value) < 3 or value[1:3] != ":/":
        raise ValueError("drive-rooted Windows path required")
    return "/mnt/" + value[0].lower() + value[2:]


class NativeWindowsBackend:
    def __init__(self):
        production_boundary()
        load_windows_software_release()
        # This constructor is reached only after the public boundary. A reviewed
        # literal recipe handoff is required; software fixtures never create it.
        import json

        from tools.benchmark.static_v4_identity import decode_primitive

        self.json = json
        self.process = None
        self.pre = None
        self.streams = []
        self.remote_counter = 0
        self.consumed = False
        self.template_path = ROOT / "results/static-v4-executor-completion-dev-1701/reviewed-recipe.frame"
        self.template = decode_primitive(self.template_path.read_bytes())
        from tools.benchmark.static_v4_identity import require, sha256

        publication = json.loads((ROOT / "evidence/static-v4-executor-completion-publication.json").read_bytes())
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
        if sorted(p.name for p in OUT.iterdir()) != ["run-static-preparation-v4.py"]:
            raise FileExistsError("fixed v4 parent is not source-only;no retry")

    def sources(self):
        import hashlib

        selected = [OUT / "run-static-preparation-v4.py"]
        for part in ("src/flydrones", "tools/benchmark", "tools/connectome"):
            selected.extend(p for p in (ROOT / part).rglob("*.py") if "__pycache__" not in p.parts)
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(selected))}

    def record(self, name, value):
        production_boundary()
        with (OUT / (name + ".json")).open("x", encoding="utf8") as f:
            self.json.dump(value, f, indent=2)

    def remote(self, args, timeout=15, *, private=False):
        production_boundary()
        return self.recorded_command(["wsl", "-d", "Ubuntu", "--", *args], timeout, private=private)

    def recorded_command(self, argv, timeout, *, private=False):
        import subprocess

        row = bounded_windows_command(argv, cwd=ROOT, timeout=timeout)
        self.remote_counter += 1
        name = ("LOCAL_UNPUBLISHED-" if private else "") + "metadata-" + str(self.remote_counter).zfill(3)
        primary = ValueError("owned metadata command failed: " + str(row["error"])) if row["error"] else None
        try:
            self.record(name, row)
        except BaseException as exc:
            if primary is None:
                primary = ValueError("metadata command nonzero: " + str(row["exit"])) if row.get("exit") not in (0, None) else exc
                if primary is not exc:
                    primary.add_note("metadata persistence secondary: " + repr(exc))
            else:
                primary.add_note("metadata persistence secondary: " + repr(exc))
            try:
                import json

                data = json.dumps(row, ensure_ascii=False).encode("utf8")
                if len(data) > 16 * 1024**2:
                    raise ValueError("metadata independent fallback bound")
                fallback = (
                    ("LOCAL_UNPUBLISHED-" if private else "") + "metadata-fallback-" + str(self.remote_counter).zfill(3) + ".json"
                )
                with (OUT / fallback).open("xb") as stream:
                    if stream.write(data) != len(data):
                        raise OSError("short metadata fallback")
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException as fallback:
                primary.add_note("metadata fallback unavailable;durability UNKNOWN: " + repr(fallback))
        if primary is not None:
            raise primary
        return subprocess.CompletedProcess(argv, row["exit"], bytes.fromhex(row["stdout_hex"]), bytes.fromhex(row["stderr_hex"]))

    def admission(self, number):
        import ast
        import datetime
        import hashlib
        import time

        import psutil

        from tools.benchmark.run_openvins_dataset_consumer import heavy_process

        code = "import os,sys\nif 'time' not in sys.builtin_module_names:raise SystemExit('builtin time required')\nimport time\ns=time.monotonic_ns();v=open('/proc/meminfo').read();a=int(next(x.split()[1] for x in v.splitlines() if x.startswith('MemAvailable:')))*1024;m=time.monotonic_ns();u=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());rows=[]\nfor n in os.listdir('/proc'):\n if not n.isdigit():continue\n try:rows.append(dict(pid=int(n),name=open('/proc/'+n+'/comm').read().strip(),cmdline=open('/proc/'+n+'/cmdline','rb').read().replace(b'\\0',b' ').decode(errors='replace')))\n except OSError:pass\nprint(repr(dict(available=a,rows=rows,started_monotonic_ns=s,memory_monotonic_ns=m,ended_monotonic_ns=time.monotonic_ns(),utc=u)))"
        row = self.remote(
            ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "LANG=C.UTF-8", "/usr/bin/python3", "-S", "-c", code], 30, private=True
        )
        if row.returncode:
            raise ValueError("fresh Linux admission snapshot failed")
        linux = ast.literal_eval(row.stdout.decode())
        if not all(type(linux[k]) is int for k in ("started_monotonic_ns", "memory_monotonic_ns", "ended_monotonic_ns")) or not (
            linux["started_monotonic_ns"] <= linux["memory_monotonic_ns"] <= linux["ended_monotonic_ns"]
        ):
            raise ValueError("fresh Linux admission clock invalid")
        memory_start = time.monotonic_ns()
        available = psutil.virtual_memory().available
        memory_end = time.monotonic_ns()
        memory = dict(
            available=available, start=memory_start, end=memory_end, utc=datetime.datetime.now(datetime.UTC).isoformat()
        )
        own = {os.getpid(), *(p.pid for p in psutil.Process().parents())}
        win = [dict(pid=p.pid, **p.info) for p in psutil.process_iter(["name", "cmdline"]) if p.pid not in own]
        blocked = [p for p in win + linux["rows"] if heavy_process(p)]
        docker = self.remote_docker()
        # Full inventories stay private. Public facts contain counters/hash/size.
        private = self.json.dumps(
            dict(
                windows=win,
                windows_memory=memory,
                linux=linux,
                docker_stdout_hex=docker.stdout.hex(),
                docker_stderr_hex=docker.stderr.hex(),
            ),
            ensure_ascii=False,
        ).encode()
        path = OUT / ("LOCAL_UNPUBLISHED-admission-" + str(number) + ".json")
        with path.open("xb") as f:
            f.write(private)
        return dict(
            windows_available=available,
            wsl_available=linux["available"],
            competitor_count=len(blocked),
            docker_exit=docker.returncode,
            docker_empty=not docker.stdout.strip() and not docker.stderr.strip(),
            windows_clock={k: memory[k] for k in ("start", "end", "utc")},
            linux_clock={k: linux[k] for k in ("started_monotonic_ns", "memory_monotonic_ns", "ended_monotonic_ns", "utc")},
            private_bytes=len(private),
            private_sha256=hashlib.sha256(private).hexdigest(),
        )

    def remote_docker(self):
        production_boundary()
        return self.recorded_command(["docker", "ps", "--no-trunc", "--format", "{{json .}}"], 15, private=True)

    def prepare_identity(self):
        production_boundary()
        from tools.benchmark.static_v4_identity import audit_preidentity, decode_primitive, encode_primitive

        with (OUT / "preidentity-attempt.frame").open("xb") as stream:
            self.consumed = True
            stream.write(
                encode_primitive(
                    dict(
                        schema="static-preidentity-attempt-v4",
                        nonce=self.recipe["nonce"],
                        unit=self.unit,
                        source_root=native_path(ROOT),
                    )
                )
            )
        with (OUT / "recipe-request.frame").open("xb") as f:
            f.write(encode_primitive(self.recipe))
        row = self.remote(
            [
                "/usr/bin/env",
                "-i",
                "PATH=/usr/bin:/bin",
                "LANG=C.UTF-8",
                "/usr/bin/timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "30s",
                "/usr/bin/python3",
                "-S",
                "-B",
                native_path(ROOT / "tools/benchmark/static_v4_identity.py"),
                "--observe-fixed-pre",
            ],
            45,
        )
        self.record("preidentity-command", dict(exit=row.returncode, stdout_hex=row.stdout.hex(), stderr_hex=row.stderr.hex()))
        if row.returncode:
            raise ValueError("actual primitive preidentity failed")
        self.recipe = decode_primitive((OUT / "recipe.frame").read_bytes())
        from tools.benchmark.static_v4_identity import audit_materialized_recipe

        audit_materialized_recipe(dict(self.template, nonce=self.recipe["nonce"], unit=self.unit), self.recipe)
        self.pre = decode_primitive((OUT / "preidentity.frame").read_bytes())
        audit_preidentity(self.pre, recipe=self.recipe)
        from tools.benchmark.static_v4_identity import audit_identity_journal, sha256

        def read_native(ref):
            prefix = native_path(OUT) + "/"
            if not ref.startswith(prefix) or ".." in ref.split("/"):
                raise ValueError("identity journal outside literal transport")
            return (OUT / ref[len(prefix) :]).read_bytes()

        audit_identity_journal(self.pre, recipe=self.recipe, reader=read_native)
        receipt = encode_primitive(
            dict(
                schema="static-preidentity-exit-v4",
                exit=0,
                preidentity_sha256=sha256((OUT / "preidentity.frame").read_bytes()),
                recipe_sha256=sha256((OUT / "recipe.frame").read_bytes()),
            )
        )
        with (OUT / "preidentity-exit.frame").open("xb") as stream:
            if stream.write(receipt) != len(receipt):
                raise OSError("short preidentity exit receipt")
            stream.flush()
            os.fsync(stream.fileno())
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
        production_boundary()
        from tools.benchmark.static_v4_identity import encode_primitive, sha256

        if self.sources() != self.source_snapshot:
            raise ValueError("full source changed before exclusive claim")
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
        production_boundary()
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
            "/usr/bin/time",
            "-v",
            "-o",
            native_path(OUT / "resources.txt"),
            "/usr/bin/timeout",
            "--signal=TERM",
            "--kill-after=10s",
            "180s",
            "/usr/bin/python3",
            "-S",
            "-B",
            native_path(ROOT / "tools/benchmark/static_v4_bootstrap.py"),
            "--admitted-once",
        ]
        self.record("actual-command", dict(argv=args, cwd=str(ROOT), launcher_budget_s=240))
        self.process = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        return self.process

    def finish(self, process):
        production_boundary()
        import threading
        import time

        if process is not self.process:
            raise ValueError("owned launcher handle differs")
        errors = []
        self.reader_errors = errors

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
        self.streams = threads
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

        if process is not getattr(self, "process", None):
            raise ValueError("cleanup only the retained owned Popen")
        waited = False
        code = None
        primary = None
        try:
            for operation in ("terminate", "kill"):
                if process.poll() is not None:
                    if not waited:
                        code = process.wait(timeout=5)
                        waited = True
                    break
                try:
                    getattr(process, operation)()
                except OSError:
                    pass
                try:
                    code = process.wait(timeout=5)
                    waited = True
                except TimeoutExpired:
                    continue
            if process.poll() is None:
                primary = ValueError("own Windows Popen wait unavailable;escapedUNKNOWN")
        except BaseException as exc:
            primary = exc
        for pipe in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
            if pipe is not None:
                try:
                    pipe.close()
                except BaseException as exc:
                    if primary is None:
                        primary = exc
                    else:
                        primary.add_note("own raw pipe close secondary: " + repr(exc))
        for thread in getattr(self, "streams", []):
            thread.join(timeout=0)
        complete = not any(thread.is_alive() for thread in getattr(self, "streams", []))
        if not complete:
            if primary is None:
                primary = ValueError("owned pipe reader unavailable;escapedUNKNOWN")
            else:
                primary.add_note("owned pipe reader unavailable;escapedUNKNOWN")
        if primary is not None:
            raise primary
        return dict(
            waited=waited,
            exit=code,
            reader_complete=complete,
            reader_errors=[repr(e) for e in getattr(self, "reader_errors", [])],
            escaped_closure="UNKNOWN",
        )

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
        props = {}
        for line in r.stdout.decode().splitlines():
            key, value = line.split("=", 1)
            if key in props:
                raise ValueError("duplicate current scope property;unitstop forbidden")
            props[key] = value
        if set(props) != {"LoadState", "InvocationID", "ControlGroup"}:
            raise ValueError("exact current scope properties required;unitstop forbidden")
        from tools.benchmark.static_v4_identity import strict_path

        strict_path(old["ControlGroup"])
        if not old["ControlGroup"].endswith("/" + self.unit):
            raise ValueError("retained own scope name differs;unitstop forbidden")

        def gone():
            probe = self.remote(
                [
                    "/usr/bin/env",
                    "-i",
                    *[k + "=" + v for k, v in self.control.items()],
                    "/usr/bin/python3",
                    "-S",
                    "-c",
                    "import os,sys;print(repr(os.path.exists(sys.argv[1])))",
                    "/sys/fs/cgroup" + old["ControlGroup"],
                ]
            )
            if probe.returncode != 0 or probe.stderr or probe.stdout != b"False\n":
                raise ValueError("owned cgroup release unconfirmed;escapedUNKNOWN")
            return dict(owned_group_released=True, unit_not_found=True, escaped_closure="UNKNOWN")

        if props.get("LoadState") == "not-found":
            if props["InvocationID"] or props["ControlGroup"]:
                raise ValueError("contradictory absent unit properties;release unconfirmed")
            return gone()
        if props.get("InvocationID") != old["InvocationID"] or props.get("ControlGroup") != old["ControlGroup"]:
            raise ValueError("fresh Invocation/CG mismatch;unitstop forbidden")
        stopped = self.manager(["stop", self.unit])
        self.record(
            "matching-unit-stop", dict(exit=stopped.returncode, stdout_hex=stopped.stdout.hex(), stderr_hex=stopped.stderr.hex())
        )
        if stopped.returncode:
            raise ValueError("owned matching unit stop failed")
        after = self.manager(["show", self.unit, "--property=LoadState", "--property=InvocationID", "--property=ControlGroup"])
        if (
            after.returncode != 0
            or after.stderr
            or set(after.stdout.decode().splitlines()) != {"LoadState=not-found", "InvocationID=", "ControlGroup="}
        ):
            raise ValueError("owned unit release unconfirmed;escapedUNKNOWN")
        return dict(gone(), matching_stop_exit=0)

    def postverify(self):
        production_boundary()
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
