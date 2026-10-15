"""Standalone primitive identity framing; native observation has an explicit gate."""

import sys

if "time" not in sys.builtin_module_names:
    raise RuntimeError("builtin time required")
import os
import time

CAP = 2 * 1024**2
FRAME_CAP = 16 * 1024**2


def encode_primitive(value):
    def part(v, depth):
        if depth > 32:
            raise ValueError("primitive depth bound")
        if v is None:
            return b"n"
        if type(v) is bool:
            return b"t" if v else b"f"
        if type(v) is int:
            return b"i" + str(v).encode("ascii") + b";"
        if type(v) in (bytes, str):
            data = v.encode("utf8") if type(v) is str else v
            return (b"s" if type(v) is str else b"x") + str(len(data)).encode("ascii") + b":" + data
        if type(v) is list:
            return b"l" + str(len(v)).encode("ascii") + b":" + b"".join(part(x, depth + 1) for x in v)
        if type(v) is dict and all(type(k) is str for k in v):
            return (
                b"d"
                + str(len(v)).encode("ascii")
                + b":"
                + b"".join(part(k, depth + 1) + part(v[k], depth + 1) for k in sorted(v))
            )
        raise ValueError("unsupported primitive type")

    result = b"V4F1" + part(value, 0)
    if len(result) > FRAME_CAP:
        raise ValueError("primitive frame bound")
    return result


def decode_primitive(data):
    if type(data) is not bytes or not data.startswith(b"V4F1") or len(data) > FRAME_CAP:
        raise ValueError("primitive frame required")
    at = 4
    events = 0

    def number(delimiter, signed=False):
        nonlocal at
        end = data.find(delimiter, at)
        if end < 0 or end - at > 20:
            raise ValueError("bounded primitive integer required")
        token = data[at:end]
        at = end + 1
        try:
            value = int(token)
        except ValueError:
            raise ValueError("primitive integer invalid") from None
        if str(value).encode("ascii") != token or not signed and value < 0:
            raise ValueError("canonical integer required")
        return value

    def item(depth):
        nonlocal at, events
        events += 1
        if at >= len(data) or depth > 32 or events > 262144:
            raise ValueError("primitive partial/depth/event bound")
        tag = data[at : at + 1]
        at += 1
        if tag == b"n":
            return None
        if tag in (b"t", b"f"):
            return tag == b"t"
        if tag == b"i":
            return number(b";", True)
        if tag in (b"s", b"x"):
            size = number(b":")
            if at + size > len(data):
                raise ValueError("partial primitive bytes")
            result = data[at : at + size]
            at += size
            try:
                return result.decode("utf8") if tag == b"s" else result
            except UnicodeError:
                raise ValueError("primitive UTF8 invalid") from None
        if tag in (b"l", b"d"):
            size = number(b":")
            if size > 65536:
                raise ValueError("primitive container bound")
            if tag == b"l":
                return [item(depth + 1) for _ in range(size)]
            result = {}
            previous = None
            for _ in range(size):
                key = item(depth + 1)
                if type(key) is not str or previous is not None and key <= previous:
                    raise ValueError("primitive duplicate/order/key")
                previous = key
                result[key] = item(depth + 1)
            return result
        raise ValueError("primitive tag invalid")

    result = item(0)
    if at != len(data):
        raise ValueError("primitive trailing bytes")
    return result


def sha256(data):
    """SHA256 using integers only; bootstrap imports no crypto extension."""
    constants = (
        0x428A2F98,
        0x71374491,
        0xB5C0FBCF,
        0xE9B5DBA5,
        0x3956C25B,
        0x59F111F1,
        0x923F82A4,
        0xAB1C5ED5,
        0xD807AA98,
        0x12835B01,
        0x243185BE,
        0x550C7DC3,
        0x72BE5D74,
        0x80DEB1FE,
        0x9BDC06A7,
        0xC19BF174,
        0xE49B69C1,
        0xEFBE4786,
        0x0FC19DC6,
        0x240CA1CC,
        0x2DE92C6F,
        0x4A7484AA,
        0x5CB0A9DC,
        0x76F988DA,
        0x983E5152,
        0xA831C66D,
        0xB00327C8,
        0xBF597FC7,
        0xC6E00BF3,
        0xD5A79147,
        0x06CA6351,
        0x14292967,
        0x27B70A85,
        0x2E1B2138,
        0x4D2C6DFC,
        0x53380D13,
        0x650A7354,
        0x766A0ABB,
        0x81C2C92E,
        0x92722C85,
        0xA2BFE8A1,
        0xA81A664B,
        0xC24B8B70,
        0xC76C51A3,
        0xD192E819,
        0xD6990624,
        0xF40E3585,
        0x106AA070,
        0x19A4C116,
        0x1E376C08,
        0x2748774C,
        0x34B0BCB5,
        0x391C0CB3,
        0x4ED8AA4A,
        0x5B9CCA4F,
        0x682E6FF3,
        0x748F82EE,
        0x78A5636F,
        0x84C87814,
        0x8CC70208,
        0x90BEFFFA,
        0xA4506CEB,
        0xBEF9A3F7,
        0xC67178F2,
    )
    state = [0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19]
    padded = data + b"\x80" + b"\0" * ((55 - len(data)) % 64) + (len(data) * 8).to_bytes(8, "big")

    def rotate(v, n):
        return ((v >> n) | (v << (32 - n))) & 0xFFFFFFFF

    for offset in range(0, len(padded), 64):
        w = [int.from_bytes(padded[offset + i : offset + i + 4], "big") for i in range(0, 64, 4)]
        for i in range(16, 64):
            a, b = w[i - 15], w[i - 2]
            w.append(
                (w[i - 16] + (rotate(a, 7) ^ rotate(a, 18) ^ (a >> 3)) + w[i - 7] + (rotate(b, 17) ^ rotate(b, 19) ^ (b >> 10)))
                & 0xFFFFFFFF
            )
        a, b, c, d, e, f, g, h = state
        for k, v in zip(constants, w):
            t = (h + (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)) + ((e & f) ^ ((~e) & g)) + k + v) & 0xFFFFFFFF
            u = ((rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) & 0xFFFFFFFF
            a, b, c, d, e, f, g, h = (t + u) & 0xFFFFFFFF, a, b, c, (d + t) & 0xFFFFFFFF, e, f, g
        state = [(x + y) & 0xFFFFFFFF for x, y in zip(state, (a, b, c, d, e, f, g, h))]
    return "".join(f"{v:08x}" for v in state)


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def require(value, message):
    if not value:
        raise ValueError(message)


def strict_path(path):
    require(
        type(path) is str
        and path.startswith("/")
        and not path.startswith("//")
        and 1 <= len(path.encode("utf8")) <= 4095
        and ".." not in path.split("/")
        and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in path),
        "strict absolute declared path required",
    )
    return path


def audit_preidentity(value, *, recipe, phase="pre", now=None):
    require(
        type(value) is dict
        and set(value)
        == {
            "schema",
            "phase",
            "nonce",
            "recipe_sha256",
            "source_root",
            "source_sha256",
            "files_before",
            "files_after",
            "versions",
            "error",
            "started_monotonic_ns",
            "ended_monotonic_ns",
            "uid",
        },
        "exact identity schema required",
    )
    require(
        value["schema"] == "static-identity-v4" and value["phase"] == phase and value["error"] is None,
        "complete successful identity required",
    )
    require(
        value["nonce"] == recipe["nonce"]
        and value["recipe_sha256"] == sha256(encode_primitive(recipe))
        and value["source_root"] == recipe["source_root"]
        and value["source_sha256"] == recipe["source_sha256"],
        "identity source/recipe joins differ",
    )
    start, end = value["started_monotonic_ns"], value["ended_monotonic_ns"]
    require(type(start) is int and type(end) is int and 0 <= start <= end, "identity monotonic interval invalid")
    if now is not None:
        require(type(now) is int and 0 <= now - end <= 60_000_000_000, "identity stale or future")
    require(value["files_before"] == value["files_after"], "global file pre/post differs")
    files = value["files_before"]
    known = {r["requested"]: r for r in files}
    require(len(known) == len(files) and set(known) == set(recipe["files"]), "exact identity member set differs")
    for path, row in known.items():
        strict_path(path)
        require(
            set(row) == {"requested", "resolved", "links", "identity", "path_identity", "bytes", "sha256"},
            "full native pin required",
        )
        require(
            type(row["bytes"]) is int
            and row["bytes"] >= 0
            and row["identity"] == row["path_identity"]
            and row["identity"]["size"] == row["bytes"]
            and row["identity"]["mode"] & 0o170000 == 0o100000,
            "native descriptor pin differs",
        )
    for name, expected in recipe["source_sha256"].items():
        require(known[recipe["source_root"] + "/" + name]["sha256"] == expected, "current source SHA differs")
    require(len(value["versions"]) == len(recipe["versions"]), "version query membership differs")
    for q, expected in zip(value["versions"], recipe["versions"]):
        require(
            q["argv"] == expected
            and q["environment"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
            and q["exit"] == 0
            and q["error"] is None
            and q["reader_complete"] is True
            and q["cleanup"]["waited"] is True
            and bytes.fromhex(q["stdout_hex"]).strip()
            and not bytes.fromhex(q["stderr_hex"]),
            "version query incomplete/different",
        )
    return value


def validate_sdk_ticket(ticket, *, actual_scope, recipe, preidentity, claim, marker, now):
    require(
        type(ticket) is dict
        and set(ticket)
        == {
            "schema",
            "nonce",
            "unit",
            "InvocationID",
            "ControlGroup",
            "claim_sha256",
            "recipe_sha256",
            "preidentity_sha256",
            "sdk_start_sha256",
        },
        "exact untrusted ticket reference required",
    )
    audit_preidentity(preidentity, recipe=recipe, now=now)
    require(
        type(marker) is dict
        and set(marker)
        == {"schema", "pid", "uid", "nonce", "InvocationID", "ControlGroup", "claim_sha256", "started_monotonic_ns"},
        "original SDK-start marker required",
    )
    require(
        set(claim) == {"schema", "nonce", "unit", "recipe_sha256", "preidentity_sha256", "source_root"}
        and claim["schema"] == "static-claim-v4"
        and claim["source_root"] == recipe["source_root"],
        "literal claim differs",
    )
    require(
        ticket["schema"] == "static-sdk-ticket-reference-v4" and marker["schema"] == "static-sdk-start-v4",
        "SDK reference schema differs",
    )
    for key in ("nonce", "claim_sha256", "recipe_sha256", "preidentity_sha256", "sdk_start_sha256"):
        require(
            type(ticket[key]) is str and len(ticket[key]) == 64 and all(c in "0123456789abcdef" for c in ticket[key]),
            "SDK reference digest invalid",
        )
    require(
        ticket["nonce"] == claim["nonce"] == recipe["nonce"] == marker["nonce"]
        and ticket["unit"] == claim["unit"] == recipe["unit"] == actual_scope["unit"],
        "SDK nonce/unit differs",
    )
    require(
        ticket["claim_sha256"] == marker["claim_sha256"] == sha256(encode_primitive(claim))
        and ticket["recipe_sha256"] == claim["recipe_sha256"] == sha256(encode_primitive(recipe))
        and ticket["preidentity_sha256"] == claim["preidentity_sha256"] == sha256(encode_primitive(preidentity))
        and ticket["sdk_start_sha256"] == sha256(encode_primitive(marker)),
        "actual receipt bytes/digests differ",
    )
    require(
        actual_scope["uid"] == preidentity["uid"] == marker["uid"]
        and actual_scope["pid"] == marker["pid"]
        and type(marker["pid"]) is int
        and marker["pid"] > 0,
        "current own UID/SDK PID differs",
    )
    require(
        ticket["InvocationID"] == actual_scope["InvocationID"] == marker["InvocationID"]
        and ticket["ControlGroup"] == actual_scope["ControlGroup"] == marker["ControlGroup"]
        and actual_scope["ControlGroup"].endswith("/" + ticket["unit"])
        and actual_scope["limits"] == recipe["static_limits"],
        "current own invocation/group/limits differ",
    )
    return dict(schema="revalidated-static-sdk-context-v4", sdk_pid=marker["pid"], ticket=ticket)


def retain_observation(body, emit):
    primary = None
    result = None
    try:
        result = body(emit)
    except BaseException as exc:
        primary = exc
    try:
        emit(dict(terminal=True, error=repr(primary) if primary else None))
    except BaseException as exc:
        if primary is None:
            primary = exc
        else:
            primary.add_note("final writer secondary: " + repr(exc))
    if primary is not None:
        raise primary
    return result


def query(argv, environment, *, api=None, clock=None):
    """Owned fork/exec, bounded streams and own-child wait; never unit control."""
    api = os if api is None else api
    clock = time if clock is None else clock
    start = clock.monotonic_ns()
    pipes = []
    pid = None
    status = None
    primary = None
    notes = []
    data = [bytearray(), bytearray()]
    active = set()
    owned_fds = set()
    row = dict(
        argv=list(argv),
        environment=dict(environment),
        started_utc=utc(),
        started_monotonic_ns=start,
        stdout_hex="",
        stderr_hex="",
        exit=None,
        error=None,
        reader_complete=False,
        cleanup=dict(waited=False, escaped_closure="UNKNOWN"),
    )
    try:
        for _ in range(2):
            pair = api.pipe()
            pipes.append(pair)
            owned_fds.update(pair)
        pid = api.fork()
        row["pid"] = pid
        if pid == 0:
            try:
                for number, pair in zip((1, 2), pipes):
                    api.dup2(pair[1], number)
                for pair in pipes:
                    for fd in pair:
                        api.close(fd)
                api.execve(argv[0], argv, environment)
            finally:
                api._exit(127)
        for i, pair in enumerate(pipes):
            api.close(pair[1])
            owned_fds.remove(pair[1])
            api.set_blocking(pair[0], False)
            active.add(i)
        while active or status is None:
            for i in tuple(active):
                try:
                    block = api.read(pipes[i][0], 65536)
                except BlockingIOError:
                    continue
                if not block:
                    active.remove(i)
                else:
                    room = CAP - len(data[i])
                    data[i].extend(block[:room])
                    if len(block) > room:
                        raise ValueError("hard primitive stream bound")
            if status is None:
                observed, code = api.waitpid(pid, api.WNOHANG)
                if observed:
                    status = code
            if clock.monotonic_ns() - start > 10_000_000_000:
                raise TimeoutError("primitive query10s exceeded")
            api.sched_yield()
        row["reader_complete"] = True
    except BaseException as exc:
        primary = exc
    finally:
        if pid and status is None:
            for signal in (15, 9):
                try:
                    api.kill(pid, signal)
                except ProcessLookupError:
                    pass
                except BaseException as exc:
                    notes.append(repr(exc))
                deadline = clock.monotonic_ns() + 5_000_000_000
                while clock.monotonic_ns() < deadline:
                    try:
                        observed, code = api.waitpid(pid, api.WNOHANG)
                        if observed:
                            status = code
                            break
                    except BaseException as exc:
                        notes.append(repr(exc))
                        break
                    api.sched_yield()
                if status is not None:
                    break
        for fd in sorted(owned_fds):
            try:
                api.close(fd)
            except BaseException as exc:
                notes.append(repr(exc))
        if primary is None and notes:
            primary = RuntimeError("own query cleanup incomplete: " + notes[0])
        row.update(
            error=repr(primary) if primary else None,
            stdout_hex=bytes(data[0]).hex(),
            stderr_hex=bytes(data[1]).hex(),
            ended_utc=utc(),
            ended_monotonic_ns=clock.monotonic_ns(),
        )
        row["elapsed_ns"] = row["ended_monotonic_ns"] - start
        row["exit"] = api.waitstatus_to_exitcode(status) if status is not None else None
        row["cleanup"].update(waited=status is not None, notes=notes)
    return row


def identity(info):
    return dict(
        device=info.st_dev,
        inode=info.st_ino,
        mode=info.st_mode,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def walk(path):
    strict_path(path)
    pending = path.split("/")[1:]
    parts = []
    links = []
    events = 0
    while pending:
        item = pending.pop(0)
        events += 1
        require(events <= 4096, "path component bound")
        if item in ("", "."):
            require(os.stat("/" + "/".join(parts)).st_mode & 0o170000 == 0o040000, "path directory required")
            continue
        if item == "..":
            require(os.stat("/" + "/".join(parts)).st_mode & 0o170000 == 0o040000, "parent directory required")
            if parts:
                parts.pop()
            continue
        selected = "/" + "/".join(parts + [item])
        before = os.lstat(selected)
        if before.st_mode & 0o170000 == 0o120000:
            require(len(links) < 40, "symlink bound")
            target = os.readlink(selected)
            require(type(target) is str and 0 < len(target.encode()) <= 4095, "link target invalid")
            require(identity(before) == identity(os.lstat(selected)) and os.readlink(selected) == target, "link changed")
            links.append(dict(path=selected, target=target, identity=identity(before)))
            if target.startswith("/"):
                parts = []
            pending = target.split("/") + pending
        else:
            if pending:
                require(before.st_mode & 0o170000 == 0o040000, "component not directory")
            parts.append(item)
    return "/" + "/".join(parts), links


def file_pin(path, *, hash_tool="/usr/bin/sha256sum", emit=None):
    """Current original-path readonly owned descriptor; bounded hash-tool output."""
    resolved, links = walk(path)
    fd = None
    primary = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
        before = identity(os.fstat(fd))
        require(before["mode"] & 0o170000 == 0o100000, "regular descriptor required")
        require(before == identity(os.stat(resolved)), "canonical descriptor mismatch")
        reference = "/proc/" + str(os.getpid()) + "/fd/" + str(fd)
        row = query([hash_tool, "--", reference], {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        row["input_requested"] = path
        row["input_identity_before"] = before
        row["input_identity_after"] = identity(os.fstat(fd))
        if emit is not None:
            emit(dict(kind="file-hash-query", query=row))
        require(
            row["exit"] == 0
            and row["error"] is None
            and row["reader_complete"]
            and row["cleanup"]["waited"]
            and not bytes.fromhex(row["stderr_hex"]),
            "owned descriptor hash query failed",
        )
        output = bytes.fromhex(row["stdout_hex"])
        expected = b"  " + reference.encode() + b"\n"
        require(len(output) == 64 + len(expected) and output[64:] == expected, "hash output token differs")
        digest = output[:64].decode("ascii")
        require(all(c in "0123456789abcdef" for c in digest), "SHA token invalid")
        require(
            before == row["input_identity_after"] == identity(os.stat(resolved)) and (resolved, links) == walk(path),
            "descriptor/path/link mutation",
        )
        return dict(
            requested=path,
            resolved=resolved,
            links=links,
            identity=before,
            path_identity=dict(before),
            bytes=before["size"],
            sha256=digest,
        )
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except BaseException as exc:
                if primary is None:
                    raise
                primary.add_note("owned descriptor close secondary: " + repr(exc))


def read_virtual_bytes(path, limit=65536):
    """Bounded live proc/cgroup fact; st_size is not virtual payload length."""
    require(
        path == "/proc/self/cgroup"
        or (
            path.startswith("/sys/fs/cgroup/")
            and path.rsplit("/", 1)[-1] in ("memory.max", "memory.swap.max", "cpu.max", "pids.max")
        ),
        "unsupported virtual scope fact",
    )
    strict_path(path)
    require(0 < limit <= 65536, "virtual fact bound")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    primary = None
    try:
        before = identity(os.fstat(fd))
        require(before["mode"] & 0o170000 == 0o100000, "regular virtual scope fact required")
        data = bytearray()
        while block := os.read(fd, min(65536, limit + 1 - len(data))):
            data.extend(block)
            require(len(data) <= limit, "virtual fact stream bound")
        after = identity(os.fstat(fd))
        require(all(before[k] == after[k] for k in ("device", "inode", "mode")), "virtual descriptor changed")
        require(bool(data), "empty virtual fact")
        return bytes(data)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            os.close(fd)
        except BaseException as exc:
            if primary is None:
                raise
            primary.add_note("virtual fact close secondary: " + repr(exc))


def read_bytes(path, limit=FRAME_CAP):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    primary = None
    try:
        before = identity(os.fstat(fd))
        require(before["mode"] & 0o170000 == 0o100000 and before["size"] <= limit, "bounded regular receipt required")
        data = bytearray()
        while block := os.read(fd, min(65536, limit + 1 - len(data))):
            data.extend(block)
            require(len(data) <= limit, "receipt stream bound")
        require(before == identity(os.fstat(fd)) and len(data) == before["size"], "receipt changed")
        return bytes(data)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            os.close(fd)
        except BaseException as exc:
            if primary is None:
                raise
            primary.add_note("receipt close secondary: " + repr(exc))


def write_exclusive(path, value):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600)
    primary = None
    try:
        data = encode_primitive(value)
        while data:
            count = os.write(fd, data)
            require(count > 0, "short primitive write")
            data = data[count:]
        os.fsync(fd)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            os.close(fd)
        except BaseException as exc:
            if primary is None:
                raise
            primary.add_note("receipt writer close secondary: " + repr(exc))


def source_root():
    return __file__.replace("\\", "/").rsplit("/", 3)[0]


def fixed_paths():
    root = source_root()
    parent = root + "/results/target-bearing-runtime-freeze-v4-dev-1701"
    return dict(
        root=root,
        parent=parent,
        recipe=parent + "/recipe.frame",
        pre=parent + "/preidentity.frame",
        claim=parent + "/claim.frame",
        marker=parent + "/sdk-start.frame",
        post=parent + "/postidentity.frame",
    )


def observer_boundary():
    require(
        sys.platform == "linux" and "PYTEST_CURRENT_TEST" not in os.environ and "pytest" not in sys.modules,
        "production primitive observer context denied",
    )
    require(os.getcwd() == source_root(), "literal native cwd required")
    raise ValueError("Task4 exact recipe and remaining observer/control audit pending;native observation unavailable")


def observe(request, output):
    observer_boundary()
    fixed = fixed_paths()
    require(request == fixed["recipe"] and output in (fixed["pre"], fixed["post"]), "literal observer recipe/output required")
    recipe = decode_primitive(read_bytes(request))
    phase = "pre" if output == fixed["pre"] else "post"
    if phase == "post":
        post_request = decode_primitive(read_bytes(fixed["parent"] + "/post-request.frame"))
        require(post_request["initial_recipe_sha256"] == sha256(encode_primitive(recipe)), "postrequest initial recipe differs")
        revised = post_request["recipe"]
        require(
            {k: v for k, v in revised.items() if k != "files"} == {k: v for k, v in recipe.items() if k != "files"},
            "postrecipe changed original context",
        )
        recipe = revised
    events = []
    started = time.monotonic_ns()
    written = 0

    def emit(row):
        nonlocal written
        written += len(encode_primitive(row))
        require(written <= FRAME_CAP, "observer journal aggregate bound")
        events.append(row)
        write_exclusive(output + ".event-" + str(len(events)).zfill(5), row)

    def body(writer):
        require(recipe["source_root"] == source_root() and os.getcwd() == source_root(), "actual native recipe cwd differs")
        # Bootstrap the hash tool without importing hashlib or a native accelerator.
        tool = read_bytes("/usr/bin/sha256sum", 2 * 1024**2)
        tool_sha = sha256(tool)
        tool_stat = identity(os.stat("/usr/bin/sha256sum"))
        writer(dict(kind="hash-tool-bootstrap", path="/usr/bin/sha256sum", sha256=tool_sha, identity=tool_stat))
        before = [file_pin(path, emit=writer) for path in recipe["files"]]
        versions = []
        for argv in recipe["versions"]:
            q = query(argv, {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
            versions.append(q)
            writer(dict(kind="version-query", query=q))
        after = [file_pin(path, emit=writer) for path in recipe["files"]]
        require(
            tool_stat == identity(os.stat("/usr/bin/sha256sum"))
            and tool_sha == sha256(read_bytes("/usr/bin/sha256sum", 2 * 1024**2)),
            "hash tool bootstrap changed",
        )
        value = dict(
            schema="static-identity-v4",
            phase=phase,
            nonce=recipe["nonce"],
            recipe_sha256=sha256(encode_primitive(recipe)),
            source_root=source_root(),
            source_sha256={
                name: next(r["sha256"] for r in after if r["requested"] == source_root() + "/" + name)
                for name in recipe["source_sha256"]
            },
            files_before=before,
            files_after=after,
            versions=versions,
            error=None,
            started_monotonic_ns=started,
            ended_monotonic_ns=time.monotonic_ns(),
            uid=os.getuid(),
        )
        audit_preidentity(value, recipe=recipe, phase=phase)
        write_exclusive(output, value)
        return value

    return retain_observation(body, emit)


def decode_identity(data):
    value = decode_primitive(data)
    require(type(value) is dict and value.get("schema") == "static-identity-v4", "actual identity frame required")
    return value


def audit_finished_native_receipts(recipe, pre, post, claim, child):
    audit_preidentity(pre, recipe=recipe)
    require(
        type(child) is dict
        and set(child) == {"schema", "exit", "waited", "claim_sha256"}
        and child["schema"] == "static-child-exit-v4"
        and type(child["exit"]) is int
        and child["exit"] == 0
        and child["waited"] is True,
        "actual owned child zero/wait required",
    )
    require(
        child["claim_sha256"] == sha256(encode_primitive(claim))
        and claim["preidentity_sha256"] == sha256(encode_primitive(pre))
        and claim["recipe_sha256"] == sha256(encode_primitive(recipe)),
        "child/claim/preidentity bytes differ",
    )
    revised = dict(recipe, files=[r["requested"] for r in post["files_before"]])
    require(post["uid"] == pre["uid"], "post observer ownUID differs")
    audit_preidentity(post, recipe=revised, phase="post")
    before = {r["requested"]: r for r in pre["files_before"]}
    after = {r["requested"]: r for r in post["files_before"]}
    require(set(before) <= set(after), "post omitted original native input")
    for path, value in before.items():
        require(after[path] == value, "native original bytes/identity changed across SDK")
    generated = recipe["source_root"] + "/results/target-bearing-runtime-freeze-v4-dev-1701/frozen-study-v4/"
    for path, value in after.items():
        strict_path(path)
        if path in before:
            continue
        # Newly copied/generated SDK metadata may appear only in its literal
        # study. An unseen outside library is never promoted to a prepin.
        if not path.startswith(generated):
            require(
                any(all(value[k] == old[k] for k in ("resolved", "identity", "bytes", "sha256")) for old in before.values()),
                "new outside native input lacks original prepin",
            )
    return dict(files=list(after.values()), source_root=recipe["source_root"])


def acquire_finished_receipts(backend):
    request = backend.request()
    backend.acquire(request)
    return backend.validate(request)


def validate_retained_finished_receipts(backend):
    request = backend.request()
    return backend.validate(request)


def acquire_finished_study(path, sha, *, require_absent=True):
    return acquire_finished_receipts(NativeFinishedReceiver(path, sha, require_absent))


def revalidate_finished_study(path, sha, *, require_absent=True):
    """Repeatable read-only validation; never rerun a retained observation."""
    return validate_retained_finished_receipts(NativeFinishedReceiver(path, sha, require_absent))


class NativeFinishedReceiver:
    def __init__(self, path, sha, require_absent):
        self.path, self.sha, self.require_absent = path, sha, require_absent

    def request(self):
        path, sha, require_absent = self.path, self.sha, self.require_absent
        from tools.benchmark.static_v4_executor import OUT, ROOT, native_path, production_boundary

        production_boundary()
        import hashlib
        import json
        from pathlib import Path

        def payload(p, limit=FRAME_CAP):
            with Path(p).open("rb") as stream:
                data = stream.read(limit + 1)
            require(len(data) <= limit, "finished metadata byte bound")
            return data

        def digest(b):
            return hashlib.sha256(b).hexdigest()

        require(Path(path).absolute() == OUT / "frozen-study-v4/study.json", "literal finished study required")
        require(
            not require_absent or not (ROOT / "results/target-bearing-physical-capture-dev-1701").exists(),
            "physical fixed attempt already exists",
        )
        recipe = decode_primitive(payload(OUT / "recipe.frame"))
        pre = decode_identity(payload(OUT / "preidentity.frame"))
        claim = decode_primitive(payload(OUT / "claim.frame"))
        child = decode_primitive(payload(OUT / "child-exit.frame"))
        require(recipe["source_root"] == native_path(ROOT), "native source root differs from literal host project")
        study_bytes = payload(path)
        require(digest(study_bytes) == sha, "actual finished study bytes differ")
        folder = OUT / "frozen-study-v4"
        index_bytes = payload(folder / "finished-artifact-index.json")
        index = json.loads(index_bytes)
        binding = json.loads(payload(folder / "runtime-binding-v4.json"))
        preparation = json.loads(payload(folder / "preparation.json"))
        bill = json.loads(payload(folder / "sdk/entry-dependencies/entry-bill.json"))
        members = [r["source"] for r in index["files"]] + binding["baseline"]["files"] + preparation["pre"]["files"]
        selected = (
            {r["requested"] for r in pre["files_before"]}
            | {r["requested"] for r in members}
            | {r["requested"] for r in bill["files"]}
        )
        selected.update(
            {
                native_path(folder / "study.json"),
                native_path(folder / "finished-artifact-index.json"),
                native_path(folder / "sdk-complete.json"),
            }
        )
        require(len(selected) <= 8192, "finished native pin membership bound")
        revised = dict(recipe, files=sorted(selected))
        request = dict(
            schema="static-post-request-v4",
            recipe=revised,
            initial_recipe_sha256=digest(encode_primitive(recipe)),
            study_sha256=sha,
            index_sha256=digest(index_bytes),
        )
        self.context = (OUT, ROOT, native_path, json, payload, digest, recipe, pre, claim, child, revised, selected, index_bytes)
        return request

    def acquire(self, request):
        OUT, ROOT, native_path, json, payload, digest, recipe, pre, claim, child, revised, selected, index_bytes = self.context
        with (OUT / "post-request.frame").open("xb") as stream:
            stream.write(encode_primitive(request))
        import subprocess

        result = subprocess.run(
            [
                "wsl",
                "-d",
                "Ubuntu",
                "--",
                "/usr/bin/timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "30s",
                "/usr/bin/python3",
                "-S",
                native_path(ROOT / "tools/benchmark/static_v4_identity.py"),
                "--observe-fixed-post",
            ],
            cwd=ROOT,
            capture_output=True,
            timeout=45,
        )
        with (OUT / "postidentity-command.json").open("x", encoding="utf8") as stream:
            json.dump(dict(exit=result.returncode, stdout_hex=result.stdout.hex(), stderr_hex=result.stderr.hex()), stream)
        require(result.returncode == 0, "actual primitive postidentity failed")

    def validate(self, request):
        OUT, ROOT, native_path, json, payload, digest, recipe, pre, claim, child, revised, selected, index_bytes = self.context
        sha = self.sha
        retained = decode_primitive(payload(OUT / "post-request.frame"))
        require(retained == request, "retained postrequest changed")
        command = json.loads(payload(OUT / "postidentity-command.json"))
        require(
            type(command) is dict
            and set(command) == {"exit", "stdout_hex", "stderr_hex"}
            and type(command["exit"]) is int
            and command["exit"] == 0
            and command["stderr_hex"] == "",
            "retained postidentity command failed",
        )
        require(
            type(command["stdout_hex"]) is str and len(bytes.fromhex(command["stdout_hex"])) <= CAP,
            "retained postidentity output bound",
        )
        post = decode_identity(payload(OUT / "postidentity.frame"))
        require(
            post["recipe_sha256"] == digest(encode_primitive(revised))
            and {r["requested"] for r in post["files_before"]} == selected,
            "exact postrequest membership differs",
        )
        validated = audit_finished_native_receipts(recipe, pre, post, claim, child)
        # Full current host source bytes must still match independently sampled
        # native pre/post pins. No Windows hash replaces those Linux observations.
        from tools.benchmark.static_v4_executor import NativeWindowsBackend

        require(NativeWindowsBackend.sources(None) == recipe["source_sha256"], "current source changed after native receipts")
        return dict(
            schema="validated-static-prepost-receipts-v4",
            files=validated["files"],
            source_root=recipe["source_root"],
            study_sha256=sha,
            index_sha256=digest(index_bytes),
            sdk_exit=child["exit"],
        )


def actual_scope(recipe):
    require(os.getuid() >= 0, "actual ownUID required")
    unit = recipe["unit"]
    require(unit == "fly-calibration-prepare-" + recipe["nonce"][:24] + ".scope", "nonce-bound unit required")
    group = read_virtual_bytes("/proc/self/cgroup", 65536).decode().strip().splitlines()
    require(len(group) == 1 and group[0].startswith("0::"), "unified own cgroup required")
    cg = group[0][3:]
    require(cg.endswith("/" + unit) and ".." not in cg.split("/"), "own exact unit cgroup required")
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/" + str(os.getuid())}
    row = query(["/usr/bin/systemctl", "--user", "show", unit, "--property=InvocationID", "--property=ControlGroup"], env)
    require(
        row["exit"] == 0
        and row["error"] is None
        and row["cleanup"]["waited"]
        and row["reader_complete"]
        and not bytes.fromhex(row["stderr_hex"]),
        "current user-manager scope query failed",
    )
    props = {}
    for line in bytes.fromhex(row["stdout_hex"]).decode().splitlines():
        key, value = line.split("=", 1)
        require(key not in props, "duplicate scope property")
        props[key] = value
    require(
        set(props) == {"InvocationID", "ControlGroup"}
        and props["ControlGroup"] == cg
        and len(props["InvocationID"]) == 32
        and all(c in "0123456789abcdef" for c in props["InvocationID"]),
        "actual current scope properties differ",
    )
    limits = {
        key: read_virtual_bytes("/sys/fs/cgroup" + cg + "/" + key, 4096).decode().strip() for key in recipe["static_limits"]
    }
    return dict(
        uid=os.getuid(), pid=os.getpid(), unit=unit, InvocationID=props["InvocationID"], ControlGroup=cg, limits=limits, query=row
    )


def production_recipe(recipe):
    root = source_root()
    required = {
        "schema",
        "source_root",
        "nonce",
        "unit",
        "source_sha256",
        "files",
        "versions",
        "sdk_environment",
        "static_limits",
    }
    require(
        set(recipe) == required
        and recipe["schema"] == "static-recipe-v4"
        and recipe["source_root"] == root
        and os.getcwd() == root,
        "literal complete production recipe required",
    )
    require(
        type(recipe["nonce"]) is str and len(recipe["nonce"]) == 64 and all(c in "0123456789abcdef" for c in recipe["nonce"]),
        "recipe nonce invalid",
    )
    require(
        recipe["static_limits"]
        == {"memory.max": "536870912", "memory.swap.max": "0", "cpu.max": "100000 100000", "pids.max": "64"},
        "static limits changed",
    )
    expected_env = {
        "HOME": "/home/yuchen7509",
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONPATH": root + "/src:" + root,
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
    }
    require(recipe["sdk_environment"] == expected_env, "SDK invocation environment differs")
    actual = []
    for part in ("src/flydrones", "tools/benchmark", "tools/connectome"):
        for directory, dirs, files in os.walk(root + "/" + part):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            actual.extend((directory + "/" + f)[len(root) + 1 :] for f in files if f.endswith(".py"))
    actual.append("results/target-bearing-runtime-freeze-v4-dev-1701/run-static-preparation-v4.py")
    require(set(recipe["source_sha256"]) == set(actual), "full current source membership differs")
    require(
        len(recipe["files"]) == len(set(recipe["files"])) and len(recipe["files"]) <= 8192,
        "complete bounded input membership required",
    )
    required_paths = {root + "/" + name for name in actual} | {
        "/usr/bin/sha256sum",
        "/usr/bin/python3",
        "/usr/bin/ldd",
        "/usr/bin/readelf",
        "/lib64/ld-linux-x86-64.so.2",
    }
    require(required_paths <= set(recipe["files"]), "required native/code inputs absent")
    require(
        recipe["versions"] and all(type(a) is list and a and a[0] in recipe["files"] for a in recipe["versions"]),
        "pinned native version argv required",
    )
    return recipe


def current_receipts():
    observer_boundary()
    fixed = fixed_paths()
    recipe = production_recipe(decode_primitive(read_bytes(fixed["recipe"])))
    pre = decode_primitive(read_bytes(fixed["pre"]))
    claim = decode_primitive(read_bytes(fixed["claim"]))
    scope = actual_scope(recipe)
    return fixed, recipe, pre, claim, scope


def revalidate_sdk_reference(ticket):
    fixed, recipe, pre, claim, scope = current_receipts()
    marker = decode_primitive(read_bytes(fixed["marker"]))
    now = time.monotonic_ns()
    require(
        type(marker.get("started_monotonic_ns")) is int and 0 <= now - marker["started_monotonic_ns"] <= 180_000_000_000,
        "SDK start age invalid",
    )
    result = validate_sdk_ticket(
        ticket, actual_scope=scope, recipe=recipe, preidentity=pre, claim=claim, marker=marker, now=marker["started_monotonic_ns"]
    )
    # Full fresh Linux byte evidence at each preparation/publication boundary.
    current = [file_pin(path) for path in recipe["files"]]
    require(current == pre["files_before"], "current input/source/tool bytes differ from native preidentity")
    return result


def enter_sdk():
    fixed, recipe, pre, claim, scope = current_receipts()
    audit_preidentity(pre, recipe=recipe, now=time.monotonic_ns())
    require([file_pin(path) for path in recipe["files"]] == pre["files_before"], "SDK preimport current pin differs")
    require(scope["limits"] == recipe["static_limits"], "actual scope limits differ before SDK")
    # Current scope observations are facts, not coordinator guesses.
    write_exclusive(fixed["parent"] + "/bootstrap-scope-before.frame", scope)
    marker = dict(
        schema="static-sdk-start-v4",
        pid=os.getpid(),
        uid=os.getuid(),
        nonce=recipe["nonce"],
        InvocationID=scope["InvocationID"],
        ControlGroup=scope["ControlGroup"],
        claim_sha256=sha256(encode_primitive(claim)),
        started_monotonic_ns=time.monotonic_ns(),
    )
    write_exclusive(fixed["marker"], marker)
    ticket = dict(
        schema="static-sdk-ticket-reference-v4",
        nonce=recipe["nonce"],
        unit=recipe["unit"],
        InvocationID=scope["InvocationID"],
        ControlGroup=scope["ControlGroup"],
        claim_sha256=marker["claim_sha256"],
        recipe_sha256=sha256(encode_primitive(recipe)),
        preidentity_sha256=sha256(encode_primitive(pre)),
        sdk_start_sha256=sha256(encode_primitive(marker)),
    )
    revalidate_sdk_reference(ticket)
    # No project import above this point. Install this actual standalone module
    # under the literal API name expected by inert prepare/study entry modules.
    sys.modules["tools.benchmark.static_v4_bootstrap"] = sys.modules[__name__]
    sys.path[:0] = [fixed["root"] + "/src", fixed["root"]]
    from tools.benchmark.prepare_calibration_capture_v4 import prepare_v4

    return prepare_v4(ticket)


if __name__ == "__main__":
    if (
        sys.argv[1:] != ["--admitted-once"]
        or sys.platform != "linux"
        or "pytest" in sys.modules
        or "PYTEST_CURRENT_TEST" in os.environ
    ):
        raise SystemExit("standalone bootstrap denied before receipt IO")
    enter_sdk()
