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
        and set(value) - {"journal"}
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
            and q.get("command_started") is True
            and q.get("tool_before") == known[expected[0]] == q.get("tool_after")
            and bytes.fromhex(q["stdout_hex"]).strip()
            and not bytes.fromhex(q["stderr_hex"]),
            "version query incomplete/different",
        )
    return value


def validate_sdk_claim(claim, *, actual_scope, recipe, preidentity, now):
    """Semantic claim check before marker writes; current_receipts supplies facts."""
    audit_preidentity(preidentity, recipe=recipe, now=now)
    require(
        type(claim) is dict and set(claim) == {"schema", "nonce", "unit", "recipe_sha256", "preidentity_sha256", "source_root"},
        "exact literal claim required",
    )
    require(
        claim["schema"] == "static-claim-v4"
        and claim["source_root"] == recipe["source_root"]
        and claim["nonce"] == recipe["nonce"]
        and claim["unit"] == recipe["unit"] == actual_scope["unit"],
        "claim nonce/unit/root differs",
    )
    require(
        claim["recipe_sha256"] == sha256(encode_primitive(recipe))
        and claim["preidentity_sha256"] == sha256(encode_primitive(preidentity)),
        "claim original bytes differ",
    )
    require(
        type(actual_scope["uid"]) is int
        and actual_scope["uid"] == preidentity["uid"]
        and type(actual_scope["pid"]) is int
        and actual_scope["pid"] > 0,
        "claim current own PID/UID differs",
    )
    invocation = actual_scope["InvocationID"]
    require(
        type(invocation) is str and len(invocation) == 32 and all(c in "0123456789abcdef" for c in invocation),
        "claim actual Invocation invalid",
    )
    strict_path(actual_scope["ControlGroup"])
    require(
        actual_scope["ControlGroup"].endswith("/" + recipe["unit"]) and actual_scope["limits"] == recipe["static_limits"],
        "claim current group/limits differ",
    )
    return claim


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
    validate_sdk_claim(claim, actual_scope=actual_scope, recipe=recipe, preidentity=preidentity, now=now)
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


def retain_observation(body, emit, *, fallback=None):
    primary = None
    result = None
    try:
        result = body(emit)
    except BaseException as exc:
        primary = exc
    terminal_persisted = False
    try:
        emit(dict(terminal=True, error=repr(primary) if primary else None))
        terminal_persisted = True
    except BaseException as exc:
        if primary is None:
            primary = exc
        else:
            primary.add_note("final writer secondary: " + repr(exc))
    if primary is not None:
        if fallback is not None:
            try:
                record = dict(
                    schema="static-observer-failure-v4",
                    primary_error=repr(primary),
                    canonical_terminal_persisted=terminal_persisted,
                    notes=list(getattr(primary, "__notes__", [])),
                )
                require(len(encode_primitive(record)) <= 65536, "independent observer fallback bound")
                fallback(record)
            except BaseException as exc:
                primary.add_note("independent observer fallback failed;durability UNKNOWN: " + repr(exc))
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
        cwd=api.getcwd() if hasattr(api, "getcwd") else None,
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


_HASH_ROOT = None


def with_hash_root(body, emit):
    """One pure-byte bootstrap, held owned descriptor, fresh helper byte hashes."""
    global _HASH_ROOT
    require(_HASH_ROOT is None, "nested bootstrap hash context refused")
    pin = tool_witness("/usr/bin/sha256sum")
    fd = os.open(pin["requested"], os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    primary, result = None, None
    try:
        require(identity(os.fstat(fd)) == pin["identity"], "bootstrap descriptor changed")
        reference = "/proc/" + str(os.getpid()) + "/fd/" + str(fd)
        emit(
            dict(
                kind="hash-tool-bootstrap",
                path=pin["requested"],
                sha256=pin["sha256"],
                identity=pin["identity"],
                reference=reference,
            )
        )
        _HASH_ROOT = dict(pin=pin, fd=fd, reference=reference, emit=emit)
        result = body(emit)
    except BaseException as exc:
        primary = exc
    finally:
        _HASH_ROOT = None
        try:
            require(
                identity(os.fstat(fd)) == pin["identity"] and tool_witness(pin["requested"]) == pin,
                "bootstrap final bytes changed",
            )
            emit(dict(kind="hash-tool-final", file=pin))
        except BaseException as exc:
            if primary is None:
                primary = exc
            else:
                primary.add_note("bootstrap final secondary: " + repr(exc))
        try:
            os.close(fd)
        except BaseException as exc:
            if primary is None:
                primary = exc
            else:
                primary.add_note("bootstrap descriptor close secondary: " + repr(exc))
    if primary is not None:
        raise primary
    return result


def tool_witness(path):
    """No-import tool byte witness on the original owned descriptor."""
    resolved, links = walk(path)
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    primary = None
    try:
        before = identity(os.fstat(fd))
        require(before["mode"] & 0o170000 == 0o100000 and 0 <= before["size"] < 2**63, "regular tool required")
        require(before == identity(os.stat(resolved)), "tool canonical descriptor differs")
        root = _HASH_ROOT
        if root is None:
            require(before["size"] <= CAP, "bounded primitive bootstrap tool required")
            data = bytearray()
            while block := os.read(fd, 65536):
                data.extend(block)
                require(len(data) <= CAP, "tool byte bound")
            require(len(data) == before["size"], "tool short byte read")
            digest = sha256(bytes(data))
        else:
            require(
                identity(os.fstat(root["fd"])) == root["pin"]["identity"] == identity(os.stat(root["pin"]["resolved"])),
                "held bootstrap identity changed",
            )
            reference = "/proc/" + str(os.getpid()) + "/fd/" + str(fd)
            q = query([root["reference"], "--", reference], {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
            q["root_before"] = root["pin"]
            q["input_identity_before"] = before
            error = None
            if (
                q["exit"] != 0
                or q["error"] is not None
                or not q["reader_complete"]
                or not q["cleanup"]["waited"]
                or q["stderr_hex"]
            ):
                error = ValueError("bootstrap helper query failed: " + str(q["error"]))
            for field, descriptor in (("root_identity_after", root["fd"]), ("input_identity_after", fd)):
                q[field] = None
                try:
                    q[field] = identity(os.fstat(descriptor))
                except BaseException as exc:
                    if error is None:
                        error = exc
                    else:
                        error.add_note("tool post observation secondary: " + repr(exc))
            output = bytes.fromhex(q["stdout_hex"])
            suffix = b"  " + reference.encode() + b"\n"
            try:
                require(
                    q["exit"] == 0
                    and q["error"] is None
                    and q["reader_complete"]
                    and q["cleanup"]["waited"]
                    and not bytes.fromhex(q["stderr_hex"]),
                    "bootstrap helper query failed: " + str(q["error"]),
                )
                require(len(output) == 64 + len(suffix) and output[64:] == suffix, "tool hash output differs")
                digest = output[:64].decode("ascii")
                require(all(c in "0123456789abcdef" for c in digest), "tool hash token malformed")
            except BaseException as exc:
                if error is None:
                    error = exc
                else:
                    error.add_note("tool output validation secondary: " + repr(exc))
            try:
                root["emit"](
                    dict(
                        kind="tool-byte-query",
                        file=dict(
                            requested=path,
                            resolved=resolved,
                            links=links,
                            identity=before,
                            path_identity=dict(before),
                            bytes=before["size"],
                            sha256=digest if error is None else None,
                        ),
                        query=q,
                        error=repr(error) if error else None,
                    )
                )
            except BaseException as exc:
                if error is None:
                    error = exc
                else:
                    error.add_note("tool prefix writer secondary: " + repr(exc))
            if error is not None:
                raise error
            require(q["root_identity_after"] == root["pin"]["identity"], "bootstrap helper mutation")
        require(
            before == identity(os.fstat(fd)) == identity(os.stat(resolved)) and (resolved, links) == walk(path),
            "tool byte/path mutation",
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
        try:
            os.close(fd)
        except BaseException as exc:
            if primary is None:
                raise
            primary.add_note("tool descriptor close secondary: " + repr(exc))


def checked_query(argv, environment):
    before = None
    row = dict(
        argv=list(argv),
        environment=dict(environment),
        exit=None,
        error=None,
        stdout_hex="",
        stderr_hex="",
        command_started=False,
        reader_complete=False,
        cleanup=dict(waited=False, escaped_closure="UNKNOWN"),
    )
    try:
        before = tool_witness(argv[0])
        row = dict(query(argv, environment), command_started=True)
    except BaseException as exc:
        row["error"] = repr(exc)
    row["tool_before"] = before
    row["tool_after"] = None
    row["observer_notes"] = []
    try:
        row["tool_after"] = tool_witness(argv[0])
        require(before is not None and before == row["tool_after"], "query tool changed")
    except BaseException as exc:
        if row["error"] is None:
            row["error"] = repr(exc)
        else:
            row["observer_notes"].append(repr(exc))
    return row


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
        row = checked_query([hash_tool, "--", reference], {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        row["input_requested"] = path
        row["observer_pid"] = os.getpid()
        row["input_identity_before"] = before
        if (
            row["exit"] != 0
            or row["error"] is not None
            or not row["reader_complete"]
            or not row["cleanup"]["waited"]
            or row["stderr_hex"]
        ):
            primary = ValueError("owned descriptor hash query failed: " + str(row["error"]))
        row["input_identity_after"] = None
        try:
            row["input_identity_after"] = identity(os.fstat(fd))
        except BaseException as exc:
            if primary is None:
                primary = exc
            else:
                primary.add_note("post-input observation secondary: " + repr(exc))
        try:
            if emit is not None:
                emit(dict(kind="file-hash-query", query=row))
        except BaseException as exc:
            if primary is None:
                primary = exc
            else:
                primary.add_note("hash query writer secondary: " + repr(exc))
        if primary is not None:
            raise primary
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
        request=parent + "/recipe-request.frame",
        pre=parent + "/preidentity.frame",
        claim=parent + "/claim.frame",
        marker=parent + "/sdk-start.frame",
        post=parent + "/postidentity.frame",
    )


def audit_software_release(release, template_bytes):
    required = {
        "schema",
        "request_sha256",
        "source_sha256",
        "archive",
        "archive_sha256",
        "review_sha256",
        "fixpass_sha256",
        "Task4_software_complete",
        "native_dispatch_ready",
    }
    require(
        type(release) is dict and set(release) == required and release["schema"] == "static-v4-reviewed-software-release-v1",
        "exact reviewed software handoff required",
    )
    request = decode_primitive(template_bytes)
    require(
        release["Task4_software_complete"] is True
        and release["native_dispatch_ready"] is False
        and release["request_sha256"] == sha256(template_bytes)
        and release["source_sha256"] == request["source_sha256"]
        and release["archive"] == "evidence/static-v4-executor-completion-dev-1701.zip",
        "software release/source/recipe differs;not native admission",
    )
    for name in ("request_sha256", "archive_sha256", "review_sha256", "fixpass_sha256"):
        require(
            type(release[name]) is str and len(release[name]) == 64 and all(c in "0123456789abcdef" for c in release[name]),
            "software handoff digest invalid",
        )
    return request


def primitive_software_release():
    root = source_root()
    try:
        raw = read_bytes(root + "/evidence/static-v4-executor-completion-release.frame")
        template = read_bytes(root + "/results/static-v4-executor-completion-dev-1701/reviewed-recipe.frame")
    except FileNotFoundError as exc:
        raise ValueError("Task4 exact recipe/full software review and seal pending;native dispatch unavailable") from exc
    release = decode_primitive(raw)
    request = audit_software_release(release, template)
    require(request["source_root"] == root, "literal released native source root differs")
    return release, request


def observer_boundary():
    require(
        sys.platform == "linux" and "PYTEST_CURRENT_TEST" not in os.environ and "pytest" not in sys.modules,
        "production primitive observer context denied",
    )
    require(os.getcwd() == source_root(), "literal native cwd required")
    primitive_software_release()


def collect_project_bytecode(root):
    rows = []

    def fail(exc):
        raise exc

    for part in ("src/flydrones", "tools/benchmark", "tools/connectome"):
        for folder, _, files in os.walk(root + "/" + part, onerror=fail, followlinks=False):
            for name in files:
                if name.endswith(".pyc"):
                    rows.append(strict_path(folder + "/" + name))
                require(len(rows) <= 8192, "project bytecode membership bound")
    return sorted(set(rows))


def collect_python_runtime(request):
    """Enumerate existing importable external bytes without importing them."""
    project = request["source_root"]
    paths = sorted(
        set(
            request["metadata_protocol"]["roots"]
            + [p for p in sys.path if p and p.startswith("/") and not (p == project or p.startswith(project + "/"))]
        )
    )
    roots = []
    for path in sorted(paths, key=lambda p: (len(p), p)):
        strict_path(path)
        if not any(path.startswith(root + "/") for root in roots if os.path.isdir(root)):
            roots.append(path)
    files, trees, states = [], [], {}

    def fail(exc):
        raise exc

    for root in roots:
        directory = os.path.isdir(root)
        regular = os.path.isfile(root)
        states[root] = "directory" if directory else "file" if regular else "absent"
        if not directory:
            if regular:
                require(root.endswith(".zip"), "unrecognized Python search file")
                files.append(root)
            continue
        for folder, dirs, names in os.walk(root, onerror=fail, followlinks=False):
            dirs.sort()
            names.sort()
            require(len(dirs) + len(names) <= 4096 and len(trees) < 8192, "Python runtime namespace bound")
            for sub in dirs:
                require(os.lstat(folder + "/" + sub).st_mode & 0o170000 == 0o040000, "Python runtime directory link unsupported")
            metadata = any(part.endswith((".dist-info", ".egg-info")) for part in folder.split("/"))
            selected = [
                name
                for name in names
                if metadata
                or name.endswith((".py", ".pyc", ".pth", ".zip"))
                or ".so" in name
                or name.startswith(("LICENSE", "COPYING", "NOTICE"))
            ]
            values = [strict_path(folder + "/" + name) for name in selected]
            files.extend(values)
            require(len(files) <= 8192, "complete Python runtime file bound")
            trees.append(dict(directory=folder, directories=list(dirs), files=values))
    return dict(roots=sorted(roots), states=states, directories=trees, files=sorted(set(files)))


def collect_startup_search(request):
    project = request["source_root"]
    paths = sorted(
        set(
            request["metadata_protocol"]["roots"] + [p for p in sys.path if p and p.startswith("/")] + [project, project + "/src"]
        )
    )
    files = []
    for directory in paths:
        strict_path(directory)
        if os.path.isdir(directory):
            for name in ("sitecustomize.py", "usercustomize.py"):
                selected = directory.rstrip("/") + "/" + name
                if os.path.isfile(selected):
                    files.append(strict_path(selected))
        elif os.path.isfile(directory) and directory.endswith(".zip"):
            files.append(directory)
    return dict(paths=paths, files=sorted(set(files)))


def collect_installed_metadata(request, emit):
    """Fresh bounded installed metadata. No JSON/site/importlib/target import."""
    protocol = request["metadata_protocol"]
    expected = dict(
        schema="fixed-installed-metadata-protocol-v4",
        distributions=["numpy", "scipy", "pyulog", "pymavlink", "protobuf"],
        roots=[
            "/usr/lib/python3/dist-packages",
            "/usr/local/lib/python3.12/dist-packages",
            "/home/yuchen7509/.local/lib/python3.12/site-packages",
        ],
        package_database="/var/lib/dpkg/status",
        owner_tool="/usr/bin/dpkg-query",
        notices_root="/usr/share/doc",
        required_notice="copyright",
        transitive_license_certified=False,
    )
    require(protocol == expected, "fixed installed metadata protocol differs")
    roots_before = {}
    metadata, startup, found, trees = [], [], set(), []

    def fail(exc):
        raise exc

    for root in protocol["roots"]:
        if not os.path.isdir(root):
            roots_before[root] = None
            emit(dict(kind="installed-root-absent", path=root))
            continue
        names = sorted(os.listdir(root))
        require(len(names) <= 4096, "installed root enumeration bound")
        roots_before[root] = names
        for name in names:
            if name.endswith(".pth") or name in ("sitecustomize.py", "usercustomize.py"):
                startup.append(strict_path(root + "/" + name))
            selected = [
                package
                for package in protocol["distributions"]
                if name.lower().startswith(package + "-") and name.endswith((".dist-info", ".egg-info"))
            ]
            if not selected:
                continue
            directory = strict_path(root + "/" + name)
            require(os.lstat(directory).st_mode & 0o170000 == 0o040000, "metadata directory must not be a symlink")
            found.update(selected)
            rows = []
            for folder, dirs, files in os.walk(directory, onerror=fail, followlinks=False):
                dirs.sort()
                files.sort()
                for sub in dirs:
                    require(os.lstat(folder + "/" + sub).st_mode & 0o170000 == 0o040000, "metadata directory link unsupported")
                for filename in files:
                    rows.append(strict_path(folder + "/" + filename))
                    require(len(rows) <= 4096 and len(metadata) + len(rows) <= 8192, "metadata membership bound")
            require(rows and any(path.endswith(("/METADATA", "/PKG-INFO")) for path in rows), "distribution metadata incomplete")
            metadata.extend(rows)
            trees.append(dict(directory=directory, files=rows))
    startup_search = collect_startup_search(request)
    startup.extend(startup_search["files"])
    runtime = collect_python_runtime(request)
    require(found == set(protocol["distributions"]), "required installed distribution metadata missing")
    status = file_pin(protocol["package_database"], emit=emit)
    declared = sorted(set(request["coverage"]["tools"] + request["coverage"]["native-candidates"]))
    inputs = sorted({walk(path)[0] for path in declared if path.startswith(("/usr/bin/", "/usr/lib/", "/lib/", "/lib64/"))})
    require(inputs and len(inputs) <= 4096, "package owner input bound")
    before = [file_pin(path, emit=emit) for path in inputs]
    query_row = checked_query([protocol["owner_tool"], "-S", "--", *inputs], {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    emit(dict(kind="package-owner-query", status_before=status, inputs_before=before, query=query_row))
    require(
        query_row["exit"] == 0
        and query_row["error"] is None
        and query_row["reader_complete"]
        and query_row["cleanup"]["waited"]
        and not bytes.fromhex(query_row["stderr_hex"]),
        "full package owner query failed",
    )
    owners, owner_names_seen, mapped = set(), set(), set()
    for line in bytes.fromhex(query_row["stdout_hex"]).decode("utf8").splitlines():
        owner_names, selected = line.rsplit(": ", 1)
        require(selected in inputs, "unexpected package owner file")
        mapped.add(selected)
        for owner in owner_names.split(", "):
            package = owner.split(":", 1)[0]
            require(package and all(c in "abcdefghijklmnopqrstuvwxyz0123456789+-." for c in package), "package name invalid")
            owners.add(package)
            owner_names_seen.add(owner)
    require(mapped == set(inputs), "package owner membership incomplete")
    files_query = checked_query(
        [protocol["owner_tool"], "-L", "--", *sorted(owner_names_seen)], {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    )
    emit(dict(kind="package-files-query", query=files_query))
    require(
        files_query["exit"] == 0
        and files_query["error"] is None
        and files_query["reader_complete"]
        and files_query["cleanup"]["waited"]
        and not bytes.fromhex(files_query["stderr_hex"]),
        "full installed package files query failed",
    )
    runtime_files = []
    for selected in bytes.fromhex(files_query["stdout_hex"]).decode("utf8").splitlines():
        strict_path(selected)
        relevant = selected.startswith(("/usr/share/gz/", "/usr/share/sdformat", "/usr/share/OGRE")) or (
            selected.startswith(("/usr/lib/", "/lib/")) and ".so" in selected.rsplit("/", 1)[-1]
        )
        if relevant:
            info = os.lstat(selected)
            if info.st_mode & 0o170000 == 0o040000:
                continue
            require(info.st_mode & 0o170000 in (0o100000, 0o120000), "installed runtime member unsupported")
            runtime_files.append(selected)
            require(len(runtime_files) <= 8192, "installed runtime member bound")
    after = [file_pin(path, emit=emit) for path in inputs]
    status_after = file_pin(protocol["package_database"], emit=emit)
    require(before == after and status == status_after, "package query input/status mutation")
    notices = sorted(protocol["notices_root"] + "/" + owner + "/copyright" for owner in owners)
    for root, names in roots_before.items():
        require((sorted(os.listdir(root)) if os.path.isdir(root) else None) == names, "installed root membership changed")
    for tree in trees:
        current = sorted(
            folder + "/" + name
            for folder, _, files in os.walk(tree["directory"], onerror=fail, followlinks=False)
            for name in files
        )
        require(current == sorted(tree["files"]), "installed metadata tree changed")
    bytecode = collect_project_bytecode(request["source_root"])
    result = dict(
        coverage={
            "installed-packages": [protocol["package_database"]],
            "installed-notices": notices,
            "package-owner-inputs": inputs,
            "package-runtime-files": sorted(set(runtime_files)),
            "python-package-metadata": sorted(set(metadata)),
            "python-startup": sorted(set(startup)),
            "python-bytecode-inputs": bytecode,
            "python-runtime-inputs": runtime["files"],
        },
        distribution_names=list(protocol["distributions"]),
        directory_inventory=trees,
        owner_query=query_row,
        files_query=files_query,
        roots_inventory=roots_before,
        startup_search=startup_search,
        python_runtime=runtime,
        observer_sys_path=list(sys.path),
        status_before=status,
        status_after=status_after,
        inputs_before=before,
        inputs_after=after,
        transitive_license_certified=False,
    )
    emit(dict(kind="installed-metadata", result=result))
    return result


def materialize_recipe_request(request, emit):
    require(
        type(request) is dict
        and request.get("schema") == "static-recipe-request-v4"
        and request["source_root"] == source_root()
        and request["native_preidentity_observed"] is False
        and request["scene_copied"] is False,
        "literal prospective recipe request required",
    )
    coverage = request["coverage"]
    required = {
        "project-source",
        "sealed-scene",
        "agent-cache",
        "agent-bundle",
        "agent-metadata",
        "native-candidates",
        "catalog",
        "tools",
        "project-inputs",
        "px4-inputs",
        "original-models",
    }
    require(
        set(coverage) == required and all(type(v) is list and v for v in coverage.values()), "exact seed coverage roles required"
    )
    require(
        request["files"] == sorted({path for paths in coverage.values() for path in paths})
        and len(coverage["sealed-scene"]) == 45
        and len(coverage["agent-cache"]) == 14,
        "complete seed coverage membership differs",
    )
    for path in request["files"]:
        strict_path(path)
    metadata = collect_installed_metadata(request, emit)
    complete = dict(coverage, **metadata["coverage"])
    recipe = {
        key: request[key]
        for key in (
            "source_root",
            "source_sha256",
            "nonce",
            "unit",
            "sdk_environment",
            "static_limits",
            "versions",
            "expected_bytes",
            "metadata_protocol",
        )
    }
    recipe.update(
        schema="static-recipe-v4",
        coverage=complete,
        files=sorted({path for paths in complete.values() for path in paths}),
        request_sha256=sha256(encode_primitive(request)),
        metadata_observation=metadata,
    )
    require(len(recipe["files"]) <= 8192, "complete native prepin membership bound")
    audit_materialized_recipe(request, recipe)
    return recipe


def audit_metadata_inventory(recipe):
    observation = recipe["metadata_observation"]
    require(collect_python_runtime(recipe) == observation["python_runtime"], "current external Python runtime namespace changed")
    require(collect_startup_search(recipe) == observation["startup_search"], "current Python startup search changed")
    require(
        collect_project_bytecode(recipe["source_root"]) == observation["coverage"]["python-bytecode-inputs"],
        "current project bytecode membership changed",
    )
    for root, names in observation["roots_inventory"].items():
        require((sorted(os.listdir(root)) if os.path.isdir(root) else None) == names, "current installed metadata root changed")

    def fail(exc):
        raise exc

    for tree in observation["directory_inventory"]:
        actual = []
        for folder, dirs, files in os.walk(tree["directory"], onerror=fail, followlinks=False):
            for directory in dirs:
                require(
                    os.lstat(folder + "/" + directory).st_mode & 0o170000 == 0o040000,
                    "current metadata directory link unsupported",
                )
            actual.extend(folder + "/" + name for name in files)
        require(sorted(actual) == sorted(tree["files"]), "current installed metadata member changed")
    return observation


def audit_materialized_recipe(request, recipe):
    unchanged = (
        "source_root",
        "source_sha256",
        "nonce",
        "unit",
        "sdk_environment",
        "static_limits",
        "versions",
        "expected_bytes",
        "metadata_protocol",
    )
    require(
        type(recipe) is dict
        and set(recipe) == set(unchanged) | {"schema", "coverage", "files", "request_sha256", "metadata_observation"}
        and recipe["schema"] == "static-recipe-v4",
        "exact complete native recipe required",
    )
    require(
        all(recipe[k] == request[k] for k in unchanged) and recipe["request_sha256"] == sha256(encode_primitive(request)),
        "materialized original request differs",
    )
    extras = {
        "installed-packages",
        "installed-notices",
        "package-owner-inputs",
        "package-runtime-files",
        "python-package-metadata",
        "python-startup",
        "python-bytecode-inputs",
        "python-runtime-inputs",
    }
    groups = recipe["coverage"]
    require(
        set(groups) == set(request["coverage"]) | extras
        and all(groups[k] == request["coverage"][k] for k in request["coverage"]),
        "materialized seed coverage changed",
    )
    observation = recipe["metadata_observation"]
    require(
        observation["coverage"] == {k: groups[k] for k in extras}
        and observation["distribution_names"] == recipe["metadata_protocol"]["distributions"]
        and observation["transitive_license_certified"] is False,
        "complete installed metadata coverage differs",
    )
    require(
        all(
            type(groups[k]) is list and groups[k]
            for k in extras - {"python-startup", "package-runtime-files", "python-bytecode-inputs"}
        ),
        "installed metadata role missing",
    )
    union = sorted({path for values in groups.values() for path in values})
    require(recipe["files"] == union and len(union) <= 8192, "complete exact native membership differs")
    for path in union:
        strict_path(path)
    return recipe


def audit_identity_journal(value, *, recipe, reader):
    audit_preidentity(value, recipe=recipe, phase=value["phase"])
    journal = value.get("journal")
    require(
        type(journal) is dict
        and set(journal) == {"schema", "observer_pid", "members"}
        and journal["schema"] == "static-identity-query-journal-v4"
        and type(journal["observer_pid"]) is int
        and journal["observer_pid"] > 0,
        "actual query journal required",
    )
    refs = journal["members"]
    require(type(refs) is list and 1 <= len(refs) <= 65536, "query journal membership bound")
    base = recipe["source_root"] + "/results/target-bearing-runtime-freeze-v4-dev-1701/" + value["phase"] + "identity.frame"
    records, total = [], 0
    for number, ref in enumerate(refs, 1):
        expected = base + ".event-" + str(number).zfill(5)
        require(
            type(ref) is dict and set(ref) == {"path", "bytes", "sha256"} and ref["path"] == expected,
            "literal journal index differs",
        )
        data = reader(expected)
        total += len(data)
        require(total <= FRAME_CAP and len(data) == ref["bytes"] and sha256(data) == ref["sha256"], "actual journal bytes differ")
        records.append(decode_primitive(data))
    terminal = decode_primitive(reader(base + ".event-" + str(len(refs) + 1).zfill(5)))
    require(terminal == dict(terminal=True, error=None), "observer terminal failed/unavailable")
    files = {r["requested"]: r for r in value["files_before"]}
    tool = files["/usr/bin/sha256sum"]
    boot = records[0]
    require(
        set(boot) == {"kind", "path", "sha256", "identity", "reference"}
        and {k: boot[k] for k in ("kind", "path", "sha256", "identity")}
        == dict(kind="hash-tool-bootstrap", path="/usr/bin/sha256sum", sha256=tool["sha256"], identity=tool["identity"]),
        "hash tool bootstrap differs",
    )
    prefix = "/proc/" + str(journal["observer_pid"]) + "/fd/"
    require(
        boot["reference"].startswith(prefix) and boot["reference"][len(prefix) :].isdigit(), "owned bootstrap reference invalid"
    )
    phase, seen, phases, versions, helpers, installed, finals = None, [], [], [], [], [], []

    def query_ok(q):
        require(
            q["exit"] == 0 and q["error"] is None and q["reader_complete"] is True and q["cleanup"]["waited"] is True,
            "journal query failed/partial",
        )
        require(
            q["environment"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"} and q["cwd"] == recipe["source_root"],
            "journal query context differs",
        )
        start, end = q["started_monotonic_ns"], q["ended_monotonic_ns"]
        require(
            type(start) is int and type(end) is int and 0 <= start <= end and end - start == q["elapsed_ns"] <= 10_000_000_000,
            "journal query monotonic budget differs",
        )
        require(
            all(type(q[k]) is str and len(q[k]) == 20 and q[k].endswith("Z") for k in ("started_utc", "ended_utc")),
            "journal query UTC missing",
        )
        require(all(len(bytes.fromhex(q[k])) <= CAP for k in ("stdout_hex", "stderr_hex")), "journal query stream bound")

    for record in records[1:]:
        kind = record["kind"]
        if kind == "tool-byte-query":
            file, q = record["file"], record["query"]
            query_ok(q)
            require(
                record["error"] is None
                and file == files[file["requested"]]
                and q["root_before"] == tool
                and q["root_identity_after"] == tool["identity"]
                and q["input_identity_before"] == file["identity"] == q["input_identity_after"],
                "tool helper native pre/post differs",
            )
            require(len(q["argv"]) == 3 and q["argv"][:2] == [boot["reference"], "--"], "helper not bound to held bootstrap")
            ref = q["argv"][2]
            require(
                ref.startswith(prefix)
                and ref[len(prefix) :].isdigit()
                and bytes.fromhex(q["stdout_hex"]) == (file["sha256"] + "  " + ref + "\n").encode()
                and q["stderr_hex"] == "",
                "fresh tool helper output differs",
            )
            helpers.append(record)
            require(len(helpers) <= 2, "unjoined tool helper query")
            continue
        if kind == "hash-tool-final":
            require(
                record == dict(kind="hash-tool-final", file=tool) and not helpers and phase is None, "bootstrap final differs"
            )
            require(record is records[-1], "bootstrap final not last")
            continue
        if kind == "file-phase":
            require(not helpers, "unjoined tool witnesses before phase")
            if record["edge"] == "begin":
                require(phase is None and record["phase"] == ("before" if not phases else "after"), "file phase order differs")
                phase = record["phase"]
                seen = []
            else:
                require(
                    record["edge"] == "end" and phase == record["phase"] and seen == recipe["files"],
                    "complete phase hash membership differs",
                )
                phases.append(phase)
                phase = None
            continue
        if kind in ("file-hash-query", "version-query", "package-owner-query", "package-files-query"):
            q = record["query"]
            query_ok(q)
            require(
                len(helpers) == 2
                and helpers[0]["file"] == q["tool_before"] == files[q["tool_before"]["requested"]]
                and helpers[1]["file"] == q["tool_after"] == q["tool_before"],
                "actual per-call tool witnesses missing/different",
            )
            require(
                helpers[0]["query"]["ended_monotonic_ns"] <= q["started_monotonic_ns"]
                and q["ended_monotonic_ns"] <= helpers[1]["query"]["started_monotonic_ns"],
                "tool query clock sequence differs",
            )
            helpers = []
        if kind == "final-input-observation":
            require(
                phase == "after"
                and not helpers
                and record["error"] is None
                and record["path"] in files
                and record["file"] == files[record["path"]],
                "final native input observation differs",
            )
            finals.append(record["path"])
            continue
        if kind == "version-query":
            versions.append(record["query"])
            continue
        if kind != "file-hash-query":
            require(
                kind in ("installed-root-absent", "package-owner-query", "package-files-query", "installed-metadata"),
                "unknown observer journal event",
            )
            require(phase is None, "metadata interleaves file phase")
            if kind == "installed-metadata":
                installed.append(record["result"])
            elif kind in ("package-owner-query", "package-files-query"):
                name = "owner_query" if kind == "package-owner-query" else "files_query"
                require(q == recipe["metadata_observation"][name], "installed query/recipe bytes differ")
            continue
        q = record["query"]
        selected = q["input_requested"]
        require(selected in files, "hash input absent from final native coverage")
        before = files[selected]
        require(
            q["exit"] == 0
            and q["error"] is None
            and q["reader_complete"] is True
            and q["cleanup"]["waited"] is True
            and q["command_started"] is True
            and q["tool_before"] == tool == q["tool_after"]
            and q["input_identity_before"] == before["identity"] == q["input_identity_after"],
            "actual hash query pre/post differs",
        )
        require(
            q["environment"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"} and q["cwd"] == recipe["source_root"],
            "hash invocation context differs",
        )
        require(
            q["observer_pid"] == journal["observer_pid"]
            and len(q["argv"]) == 3
            and q["argv"][:2] == ["/usr/bin/sha256sum", "--"],
            "hash query argv/PID differs",
        )
        ref = q["argv"][2]
        prefix = "/proc/" + str(journal["observer_pid"]) + "/fd/"
        require(ref.startswith(prefix) and ref[len(prefix) :].isdigit(), "owned descriptor reference differs")
        require(
            bytes.fromhex(q["stdout_hex"]) == (before["sha256"] + "  " + ref + "\n").encode() and q["stderr_hex"] == "",
            "hash output does not bind actual baseline",
        )
        if phase is not None:
            seen.append(selected)
    require(
        phases == ["before", "after"]
        and phase is None
        and not helpers
        and versions == value["versions"]
        and finals == recipe["files"]
        and records[-1] == dict(kind="hash-tool-final", file=tool),
        "journal omitted phase/version queries/bootstrap final",
    )
    if "metadata_observation" in recipe:
        require(
            installed == ([recipe["metadata_observation"]] if value["phase"] == "pre" else []),
            "complete installed metadata event missing/different",
        )
    return value


def observe(request, output):
    observer_boundary()
    require(
        sys.flags.no_site and sys.flags.dont_write_bytecode and "time" in sys.builtin_module_names,
        "primitive observer startup policy denied",
    )
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        require(
            name != "json" and not name.startswith("json.") and not (filename and filename.endswith((".so", ".pyd", ".dylib"))),
            "primitive observer already contains nonprimitive imports",
        )
    fixed = fixed_paths()
    require(output in (fixed["pre"], fixed["post"]), "literal observer output required")
    require(request == fixed["request" if output == fixed["pre"] else "recipe"], "literal observer recipe request required")
    recipe = decode_primitive(read_bytes(request))
    phase = "pre" if output == fixed["pre"] else "post"
    write_exclusive(
        fixed["parent"] + "/" + phase + "identity-observer-start.frame",
        dict(
            schema="static-primitive-observer-start-v4",
            phase=phase,
            pid=os.getpid(),
            uid=os.getuid(),
            started_monotonic_ns=time.monotonic_ns(),
            request_sha256=sha256(encode_primitive(recipe)),
        ),
    )
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

    def operation(writer):
        nonlocal recipe
        before, versions, after = [], [], []
        primary = None

        def secondary(exc, label):
            nonlocal primary
            if primary is None:
                primary = exc
            else:
                primary.add_note(label + ": " + repr(exc))

        def retained(row):
            try:
                writer(row)
            except BaseException as exc:
                secondary(exc, "final writer secondary")

        try:
            require(recipe["source_root"] == source_root() and os.getcwd() == source_root(), "actual native recipe cwd differs")
            if phase == "pre":
                recipe = materialize_recipe_request(recipe, writer)
                write_exclusive(fixed["recipe"], recipe)
            audit_metadata_inventory(recipe)
            writer(dict(kind="file-phase", phase="before", edge="begin"))
            for path in recipe["files"]:
                before.append(file_pin(path, emit=writer))
            writer(dict(kind="file-phase", phase="before", edge="end"))
            for row in before:
                if row["requested"] in recipe.get("expected_bytes", {}):
                    require(
                        {k: row[k] for k in ("bytes", "sha256")} == recipe["expected_bytes"][row["requested"]],
                        "fixed original/current input bytes differ",
                    )
            for argv in recipe["versions"]:
                q = checked_query(argv, {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
                versions.append(q)
                writer(dict(kind="version-query", query=q))
        except BaseException as exc:
            primary = exc
        finally:
            try:
                audit_metadata_inventory(recipe)
            except BaseException as exc:
                secondary(exc, "final namespace observation secondary")
            retained(dict(kind="file-phase", phase="after", edge="begin"))
            for path in recipe["files"]:
                value, error = None, None
                try:
                    value = file_pin(path, emit=writer)
                    after.append(value)
                except BaseException as exc:
                    error = repr(exc)
                    secondary(exc, "final input observation secondary")
                retained(dict(kind="final-input-observation", path=path, file=value, error=error))
            retained(dict(kind="file-phase", phase="after", edge="end"))
        if primary is not None:
            raise primary
        return before, versions, after

    def body(writer):
        before, versions, after = with_hash_root(operation, writer)
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
            journal=dict(
                schema="static-identity-query-journal-v4",
                observer_pid=os.getpid(),
                members=[
                    dict(
                        path=output + ".event-" + str(n).zfill(5),
                        bytes=len(encode_primitive(row)),
                        sha256=sha256(encode_primitive(row)),
                    )
                    for n, row in enumerate(events, 1)
                ],
            ),
        )
        audit_preidentity(value, recipe=recipe, phase=phase)
        write_exclusive(output, value)
        return value

    return retain_observation(body, emit, fallback=lambda record: write_exclusive(output + ".failure-fallback", record))


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
        controls = {
            recipe["source_root"] + "/results/target-bearing-runtime-freeze-v4-dev-1701/" + name
            for name in ("sdk-start.frame", "sdk-preparation-entered.frame", "bootstrap-scope-before.frame")
        }
        if not path.startswith(generated) and path not in controls:
            require(
                any(all(value[k] == old[k] for k in ("resolved", "identity", "bytes", "sha256")) for old in before.values()),
                "new outside native input lacks original prepin",
            )
    return dict(files=list(after.values()), source_root=recipe["source_root"])


def audit_sdk_invocation_facts(facts, recipe, *, initial):
    require(
        type(facts) is dict and set(facts) == {"environment", "argv", "cwd", "executable", "no_site", "no_bytecode", "sys_path"},
        "actual SDK invocation facts required",
    )
    require(facts["environment"] == recipe["sdk_environment"], "actual SDK environment differs")
    root = recipe["source_root"]
    require(
        facts["argv"] == [root + "/tools/benchmark/static_v4_bootstrap.py", "--admitted-once"]
        and facts["cwd"] == root
        and facts["executable"] == "/usr/bin/python3"
        and facts["no_site"] is True
        and facts["no_bytecode"] is True,
        "actual SDK startup invocation differs",
    )
    paths = facts["sys_path"]
    require(
        type(paths) is list and all(type(path) is str and path.startswith("/") and ".." not in path.split("/") for path in paths),
        "actual SDK import path invalid",
    )
    observed = recipe.get("metadata_observation", {}).get("observer_sys_path", [])
    expected = [root + "/tools/benchmark", root + "/src", root] + [p for p in observed if p != root + "/tools/benchmark"]
    if initial:
        require(paths == expected, "actual SDK initial import path differs")
    else:
        allowed = recipe["metadata_observation"]["python_runtime"]["roots"] + [root, root + "/src", root + "/tools/benchmark"]
        require(
            all(any(path == base or (base != root and path.startswith(base + "/")) for base in allowed) for path in paths),
            "actual SDK import search escaped pinned namespaces",
        )
    return facts


def audit_sdk_admission_receipts(recipe, pre, claim, scope, marker, entered, preparation):
    audit_sdk_invocation_facts(scope["invocation"], recipe, initial=True)
    ticket = preparation["sdk_ticket"]
    validate_sdk_ticket(
        ticket, actual_scope=scope, recipe=recipe, preidentity=pre, claim=claim, marker=marker, now=marker["started_monotonic_ns"]
    )
    require(
        preparation["sdk_pid"] == marker["pid"]
        and entered
        == dict(schema="static-sdk-preparation-entry-v4", pid=marker["pid"], ticket_sha256=sha256(encode_primitive(ticket))),
        "SDK preparation entry/PID/reference differs",
    )
    q = scope["query"]
    tool = next(row for row in pre["files_before"] if row["requested"] == "/usr/bin/systemctl")
    require(
        q["tool_before"] == tool == q["tool_after"]
        and q["argv"]
        == ["/usr/bin/systemctl", "--user", "show", recipe["unit"], "--property=InvocationID", "--property=ControlGroup"]
        and q["environment"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/" + str(scope["uid"])},
        "saved SDK scope tool/invocation differs",
    )
    require(
        q["exit"] == 0
        and q["error"] is None
        and q["reader_complete"] is True
        and q["cleanup"]["waited"] is True
        and q["stderr_hex"] == ""
        and q["ended_monotonic_ns"] <= marker["started_monotonic_ns"],
        "saved SDK scope query failed/future",
    )
    props = {}
    for line in bytes.fromhex(q["stdout_hex"]).decode("utf8").splitlines():
        key, selected = line.split("=", 1)
        require(key not in props, "duplicate saved SDK scope property")
        props[key] = selected
    require(
        props == {"InvocationID": scope["InvocationID"], "ControlGroup": scope["ControlGroup"]},
        "saved SDK scope actual bytes differ",
    )
    return ticket


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
        marker = decode_primitive(payload(OUT / "sdk-start.frame"))
        scope = decode_primitive(payload(OUT / "bootstrap-scope-before.frame"))
        entered = decode_primitive(payload(OUT / "sdk-preparation-entered.frame"))
        audit_sdk_admission_receipts(recipe, pre, claim, scope, marker, entered, preparation)
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
        selected.update(
            native_path(OUT / name)
            for name in ("sdk-start.frame", "bootstrap-scope-before.frame", "sdk-preparation-entered.frame")
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
        from tools.benchmark.static_v4_executor import bounded_windows_command, load_windows_software_release

        load_windows_software_release()
        with (OUT / "post-request.frame").open("xb") as stream:
            stream.write(encode_primitive(request))
        raw = bounded_windows_command(
            [
                "wsl",
                "-d",
                "Ubuntu",
                "--",
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
                "--observe-fixed-post",
            ],
            cwd=ROOT,
            timeout=45,
        )
        primary = None
        if raw["exit"] != 0 or raw["error"] is not None or not raw["reader_complete"] or not raw["cleanup"]["waited"]:
            primary = ValueError("actual primitive postidentity failed: " + str(raw["error"]))
        try:
            with (OUT / "postidentity-outer.json").open("x", encoding="utf8") as stream:
                json.dump(raw, stream)
            with (OUT / "postidentity-command.json").open("x", encoding="utf8") as stream:
                json.dump(dict(exit=raw["exit"], stdout_hex=raw["stdout_hex"], stderr_hex=raw["stderr_hex"]), stream)
        except BaseException as exc:
            if primary is None:
                primary = exc
            else:
                primary.add_note("postidentity writer secondary: " + repr(exc))
            try:
                data = json.dumps(raw).encode("utf8")
                require(len(data) <= FRAME_CAP, "postidentity independent fallback bound")
                with (OUT / "postidentity-outer-fallback.json").open("xb") as stream:
                    require(stream.write(data) == len(data), "short postidentity fallback")
                    stream.flush()
            except BaseException as fallback:
                primary.add_note("postidentity fallback unavailable;durability UNKNOWN: " + repr(fallback))
        if primary is not None:
            raise primary

    def validate(self, request):
        OUT, ROOT, native_path, json, payload, digest, recipe, pre, claim, child, revised, selected, index_bytes = self.context
        sha = self.sha
        retained = decode_primitive(payload(OUT / "post-request.frame"))
        require(retained == request, "retained postrequest changed")
        command = json.loads(payload(OUT / "postidentity-command.json"))
        outer = json.loads(payload(OUT / "postidentity-outer.json"))
        require(
            outer["error"] is None
            and outer["reader_complete"] is True
            and outer["cleanup"]["waited"] is True
            and {k: outer[k] for k in ("exit", "stdout_hex", "stderr_hex")} == command,
            "retained outer postidentity failed/differs",
        )
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

        def native_reader(ref):
            prefix = recipe["source_root"] + "/results/target-bearing-runtime-freeze-v4-dev-1701/"
            strict_path(ref)
            require(ref.startswith(prefix), "journal transport outside literal native source root")
            return payload(OUT / ref[len(prefix) :])

        audit_identity_journal(pre, recipe=recipe, reader=native_reader)
        audit_identity_journal(post, recipe=revised, reader=native_reader)
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
    invocation = current_sdk_invocation(recipe)
    require(os.getuid() >= 0, "actual ownUID required")
    unit = recipe["unit"]
    require(unit == "fly-calibration-prepare-" + recipe["nonce"][:24] + ".scope", "nonce-bound unit required")
    group = read_virtual_bytes("/proc/self/cgroup", 65536).decode().strip().splitlines()
    require(len(group) == 1 and group[0].startswith("0::"), "unified own cgroup required")
    cg = group[0][3:]
    require(cg.endswith("/" + unit) and ".." not in cg.split("/"), "own exact unit cgroup required")
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "XDG_RUNTIME_DIR": "/run/user/" + str(os.getuid())}
    row = checked_query(["/usr/bin/systemctl", "--user", "show", unit, "--property=InvocationID", "--property=ControlGroup"], env)
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
        uid=os.getuid(),
        pid=os.getpid(),
        unit=unit,
        InvocationID=props["InvocationID"],
        ControlGroup=cg,
        limits=limits,
        query=row,
        invocation=invocation,
    )


def current_sdk_invocation(recipe):
    # Environment is checked before inspecting any other invocation field.
    require(dict(os.environ) == recipe["sdk_environment"], "actual SDK environment differs")
    facts = dict(
        environment=dict(os.environ),
        argv=list(sys.argv),
        cwd=os.getcwd(),
        executable=sys.executable,
        no_site=bool(sys.flags.no_site),
        no_bytecode=bool(sys.flags.dont_write_bytecode),
        sys_path=list(sys.path),
    )
    return audit_sdk_invocation_facts(facts, recipe, initial="site" not in sys.modules)


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
        "expected_bytes",
        "metadata_protocol",
        "metadata_observation",
        "coverage",
        "request_sha256",
    }
    require(
        set(recipe) == required
        and recipe["schema"] == "static-recipe-v4"
        and recipe["source_root"] == root
        and os.getcwd() == root,
        "literal complete production recipe required",
    )
    request = decode_primitive(read_bytes(fixed_paths()["request"]))
    audit_materialized_recipe(request, recipe)
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
    current_sdk_invocation(recipe)
    audit_metadata_inventory(recipe)
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
    require(sys.flags.no_site and sys.flags.dont_write_bytecode, "SDK must use admitted -S -B startup")
    fixed = fixed_paths()
    recipe = production_recipe(decode_primitive(read_bytes(fixed["recipe"])))
    pre = decode_primitive(read_bytes(fixed["pre"]))
    audit_identity_journal(pre, recipe=recipe, reader=read_bytes)
    exit_receipt = decode_primitive(read_bytes(fixed["parent"] + "/preidentity-exit.frame"))
    require(
        exit_receipt
        == dict(
            schema="static-preidentity-exit-v4",
            exit=0,
            preidentity_sha256=sha256(encode_primitive(pre)),
            recipe_sha256=sha256(encode_primitive(recipe)),
        ),
        "actual preidentity exit receipt differs",
    )
    claim = decode_primitive(read_bytes(fixed["claim"]))
    scope = actual_scope(recipe)
    pins = {r["requested"]: r for r in pre["files_before"]}
    require(
        scope["query"]["tool_before"] == pins["/usr/bin/systemctl"] == scope["query"]["tool_after"],
        "current scope tool differs from native prepin",
    )
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
    current = run_current_pin_gate(recipe, fixed, "revalidate")
    require(current == pre["files_before"], "current input/source/tool bytes differ from native preidentity")
    return result


def enter_sdk():
    fixed, recipe, pre, claim, scope = current_receipts()
    validate_sdk_claim(claim, actual_scope=scope, recipe=recipe, preidentity=pre, now=time.monotonic_ns())
    try:
        os.lstat(fixed["marker"])
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError("SDK-start already consumed")
    require(run_current_pin_gate(recipe, fixed, "preimport") == pre["files_before"], "SDK preimport current pin differs")
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
    return enter_preparation_after_gate(ticket, fixed)


_SDK_AUDIT_COUNTER = 0


def run_current_pin_gate(recipe, fixed, label):
    global _SDK_AUDIT_COUNTER
    require(label in ("preimport", "revalidate"), "literal SDK gate phase required")
    _SDK_AUDIT_COUNTER += 1
    base = fixed["parent"] + "/sdk-gate-" + str(os.getpid()) + "-" + str(_SDK_AUDIT_COUNTER).zfill(3)
    count, written = 0, 0

    def emit(row):
        nonlocal count, written
        count += 1
        written += len(encode_primitive(row))
        require(written <= FRAME_CAP, "SDK gate journal bound")
        write_exclusive(base + ".event-" + str(count).zfill(5), row)

    def body(writer):
        audit_metadata_inventory(recipe)
        return with_hash_root(lambda observed: [file_pin(path, emit=observed) for path in recipe["files"]], writer)

    return retain_observation(body, emit, fallback=lambda row: write_exclusive(base + ".failure-fallback", row))


def enter_preparation_after_gate(ticket, fixed):
    revalidate_sdk_reference(ticket)
    actual_fixed = fixed_paths()
    require(fixed == actual_fixed, "literal SDK entry paths changed")
    write_exclusive(
        fixed["parent"] + "/sdk-preparation-entered.frame",
        dict(schema="static-sdk-preparation-entry-v4", pid=os.getpid(), ticket_sha256=sha256(encode_primitive(ticket))),
    )
    # No project/site/JSON import above this point. Restore ordinary SDK site
    # initialization only after the primitive admission and SDK-start marker.
    # under the literal API name expected by inert prepare/study entry modules.
    sys.modules["tools.benchmark.static_v4_bootstrap"] = sys.modules[__name__]
    sys.path[:0] = [fixed["root"] + "/src", fixed["root"]]
    import site

    site.main()
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
