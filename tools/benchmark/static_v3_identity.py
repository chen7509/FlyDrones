"""Primitive Linux file/tool observer; no project, JSON or extension imports."""

import sys

if "time" not in sys.builtin_module_names:
    raise RuntimeError("builtin time required before import")

import os  # noqa: E402 - builtin policy gate precedes imports
import time  # noqa: E402 - builtin policy gate precedes imports

CAP = 2 * 1024**2
JOURNAL_CAP = 16 * 1024**2


def imported_extensions():
    return [
        name
        for name, module in tuple(sys.modules.items())
        if type(getattr(getattr(module, "__spec__", None), "loader", None)).__name__ == "ExtensionFileLoader"
    ]


def query(argv, env):
    start = time.monotonic_ns()
    pipes = [os.pipe(), os.pipe()]
    pid = os.fork()
    if pid == 0:
        try:
            for number, pair in zip((1, 2), pipes):
                os.dup2(pair[1], number)
            for pair in pipes:
                for fd in pair:
                    os.close(fd)
            os.execve(argv[0], argv, env)
        finally:
            os._exit(127)
    for pair in pipes:
        os.close(pair[1])
        os.set_blocking(pair[0], False)
    data = [bytearray(), bytearray()]
    open_pipes = {0, 1}
    row = dict(
        argv=argv,
        environment=env,
        pid=pid,
        start_monotonic_ns=start,
        exit=None,
        error=None,
        stdout_hex="",
        stderr_hex="",
        cleanup={},
        reader_complete=False,
    )
    status = None
    try:
        while status is None or open_pipes:
            for i in tuple(open_pipes):
                try:
                    chunk = os.read(pipes[i][0], 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    open_pipes.remove(i)
                else:
                    room = CAP - len(data[i])
                    data[i].extend(chunk[:room])
                    if len(chunk) > room:
                        raise ValueError("primitive tool stream cap")
            if status is None:
                found, code = os.waitpid(pid, os.WNOHANG)
                if found:
                    status = code
            if time.monotonic_ns() - start >= 10_000_000_000:
                raise TimeoutError("primitive tool deadline")
            os.sched_yield()
        row["reader_complete"] = True
    except BaseException as exc:
        row["error"] = repr(exc)
    finally:
        if status is None:
            for signal, seconds in ((15, 5), (9, 5)):
                try:
                    os.kill(pid, signal)
                    row["cleanup"][str(signal)] = "sent to own child"
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    found, code = os.waitpid(pid, os.WNOHANG)
                    if found:
                        status = code
                        break
                    os.sched_yield()
                if status is not None:
                    break
        for pair in pipes:
            os.close(pair[0])
        row.update(
            exit=os.waitstatus_to_exitcode(status) if status is not None else None,
            stdout_hex=bytes(data[0]).hex(),
            stderr_hex=bytes(data[1]).hex(),
            end_monotonic_ns=time.monotonic_ns(),
        )
        row["elapsed_ns"] = row["end_monotonic_ns"] - start
        row["cleanup"].update(waited=status is not None, escaped_closure="unknown")
    return row


def observe(request, output):
    started = time.monotonic_ns()
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    written = 0

    def emit(row):
        nonlocal written
        payload = (repr(row) + "\n").encode()
        if written + len(payload) > JOURNAL_CAP:
            raise ValueError("primitive journal cap")
        while payload:
            count = os.write(descriptor, payload)
            if count <= 0:
                raise OSError("primitive journal short write")
            written += count
            payload = payload[count:]

    def safe(path):
        if not path.startswith("/") or ".." in path.split("/") or "\n" in path or "\x00" in path:
            raise ValueError("absolute declared primitive path required")
        return path

    def identity(path):
        def fields(value):
            return dict(
                device=value.st_dev,
                inode=value.st_ino,
                mode=value.st_mode,
                size=value.st_size,
                mtime_ns=value.st_mtime_ns,
                ctime_ns=value.st_ctime_ns,
            )

        before = os.stat(path)
        raw = query(["/usr/bin/sha256sum", "--", path], dict(PATH="/usr/bin:/bin", LANG="C.UTF-8"))
        emit(dict(kind="hash-query", query=raw))
        data = bytes.fromhex(raw["stdout_hex"])
        if raw["exit"] != 0 or raw["error"] or raw["stderr_hex"] or not raw["reader_complete"]:
            raise ValueError("primitive hash query refused")
        digest = data[:64].decode("ascii")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) or data[64:] != b"  " + path.encode() + b"\n":
            raise ValueError("primitive hash output differs")
        after = os.stat(path)
        if fields(before) != fields(after):
            raise ValueError("primitive file changed while hashing")
        return dict(
            requested=path,
            resolved=os.path.realpath(path),
            identity=fields(after),
            path_identity=fields(os.lstat(path)),
            bytes=after.st_size,
            sha256=digest,
        )

    error = None
    try:
        if sys.platform != "linux" or not sys.flags.no_site or "time" not in sys.builtin_module_names or imported_extensions():
            raise ValueError("primitive observer startup/import policy refused")
        rows = open(request, encoding="utf8").read().splitlines()
        paths, roots, versions, bootstrap = [], [], [], {}
        for line in rows:
            parts = line.split("\t")
            if len(parts) not in (2, 3):
                raise ValueError("primitive request syntax")
            kind, path = parts[0], safe(bytes.fromhex(parts[1]).decode())
            if kind == "P":
                paths.append(path)
            elif kind == "D":
                roots.append(path)
            elif kind == "V":
                versions.append(path)
            elif kind == "B" and len(parts) == 3:
                bootstrap[path] = parts[2]
            else:
                raise ValueError("primitive request kind")
        for path, expected in bootstrap.items():
            row = identity(path)
            emit(dict(kind="bootstrap", file=row))
            if row["sha256"] != expected:
                raise ValueError("bootstrap host/Linux bytes differ")
        for root in roots:
            if not os.path.isdir(root):
                raise ValueError("required installed tree missing: " + root)

            def fail_walk(exc):
                raise exc

            for folder, _, names in os.walk(root, onerror=fail_walk):
                for name in names:
                    if (
                        name.endswith((".py", ".pyc", ".pth"))
                        or ".so" in name
                        or name in ("copyright", "METADATA", "LICENSE", "COPYING")
                    ):
                        paths.append(safe(os.path.join(folder, name)))
        paths = sorted(set(paths) | set(bootstrap))
        if not paths or len(paths) > 8192:
            raise ValueError("bounded primitive input membership required")
        uid = os.getuid()
        manager = "/run/user/" + str(uid)
        state = os.lstat(manager)
        if state.st_uid != uid or state.st_mode & 0o170000 != 0o040000:
            raise ValueError("own manager directory refused")
        emit(
            dict(
                kind="begin",
                requested=paths,
                uid=uid,
                python=sys.version,
                builtin_modules=list(sys.builtin_module_names),
                imported_extensions=imported_extensions(),
                start_monotonic_ns=started,
                manager_control_environment=dict(PATH="/usr/bin:/bin", LANG="C.UTF-8", XDG_RUNTIME_DIR=manager),
            )
        )
        for phase in ("before", "after"):
            for path in paths:
                emit(dict(kind="file", phase=phase, file=identity(path)))
            if phase == "before":
                for path in versions:
                    file_before = identity(path)
                    raw = query([path, "--version"], dict(PATH="/usr/bin:/bin", LANG="C.UTF-8"))
                    file_after = identity(path)
                    emit(dict(kind="version", file=path, query=raw, file_before=file_before, file_after=file_after))
                    if file_before != file_after:
                        raise ValueError("version tool per-call identity changed")
                    if (
                        raw["exit"] != 0
                        or raw["error"]
                        or not raw["reader_complete"]
                        or not (raw["stdout_hex"] or raw["stderr_hex"])
                    ):
                        raise ValueError("primitive version refused")
        if imported_extensions():
            raise ValueError("primitive observer imported extension")
    except BaseException as exc:
        error = repr(exc)
        raise
    finally:
        try:
            ended = time.monotonic_ns()
            emit(
                dict(
                    kind="terminal",
                    error=error,
                    start_monotonic_ns=started,
                    end_monotonic_ns=ended,
                    elapsed_ns=ended - started,
                    imported_extensions=imported_extensions(),
                    runtime_import_verified=False,
                    qualification=False,
                )
            )
        finally:
            os.close(descriptor)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("fixed coordinator request/output arguments required")
    observe(sys.argv[1], sys.argv[2])
