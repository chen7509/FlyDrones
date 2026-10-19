"""Read-only Linux input observer; stdout frames are the only output, no Linux file writes."""

import collections
import hashlib
import json
import os
import signal
import stat
import struct
import sys
import time

# Selection literal is prepended by the Windows parent; no Linux input/config discovery.
caps = SELECTION["caps"]  # noqa: F821
selection = SELECTION  # noqa: F821
started = time.monotonic()
deadline = started + caps["read_seconds"]
signal.signal(signal.SIGALRM, signal.SIG_DFL)
signal.alarm(caps["read_seconds"])
wire = sys.stdout.buffer
metadata_bytes = 0
payload_bytes = 0


class Stop(Exception):
    pass


def check():
    if time.monotonic() >= deadline:
        raise Stop("read deadline; no second selection")


def emit(row, final=False):
    global metadata_bytes
    raw = json.dumps(row, separators=(",", ":"), ensure_ascii=True).encode()
    if metadata_bytes + len(raw) > caps["metadata_bytes"] - (0 if final else 8192):
        raise Stop("2MiB metadata cap; no second selection")
    wire.write(b"J" + struct.pack(">I", len(raw)) + raw)
    wire.flush()
    metadata_bytes += len(raw)


def info(s):
    return dict(dev=s.st_dev, ino=s.st_ino, mode=s.st_mode, uid=s.st_uid, gid=s.st_gid,
                nlink=s.st_nlink, bytes=s.st_size, mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns)


def forbidden(path):
    return any(path == p or path.startswith(p + "/") for p in selection["forbidden_prefixes"])


def resolve(path):
    pending = collections.deque(path.split("/"))
    current, links = "/", []
    while pending:
        check()
        part = pending.popleft()
        if part in ("", "."):
            continue
        if part == "..":
            current = os.path.dirname(current)
            continue
        candidate = os.path.join(current, part)
        if forbidden(candidate):
            raise ValueError("forbidden old build/library/object prefix; not stat/open/read")
        before = os.lstat(candidate)
        if stat.S_ISLNK(before.st_mode):
            if len(links) >= caps["symlink_hops"]:
                raise ValueError("symlink hop bound")
            target = os.readlink(candidate)
            after = os.lstat(candidate)
            if info(before) != info(after):
                raise ValueError("symlink changed during readlink")
            links.append(dict(path=candidate, target=target, before=info(before), after=info(after)))
            if os.path.isabs(target):
                current = "/"
            pending.extendleft(reversed(target.split("/")))
        else:
            current = candidate
    if forbidden(current):
        raise ValueError("forbidden resolved target")
    endpoint = os.lstat(current)
    return dict(resolved=current, stat=info(endpoint), links=links)


identities, excluded_ids, new_ids = {}, {tuple(key) for key in selection['excluded_native_identities']}, set()
reason, complete, attempted = None, False, 0
emit(dict(type="start", pid=os.getpid(), interpreter=sys.executable, selected=len(selection["selected"]),
          no_linux_file_writes=True, no_compiler_or_target=True, no_resource_query=True))
try:
    # First pass is metadata only, including prior regular inputs. Never read old contents.
    for item in selection["selected"]:
        check()
        if time.monotonic() - started >= 10:
            raise Stop("10s identity metadata window exhausted; no second selection")
        path = item["path"]
        attempted += 1
        row = dict(type="identity", path=path)
        try:
            identity = resolve(path)
            row.update(identity, status="observed")
            identities[path] = identity
            if path in selection["excluded"] or identity["resolved"] in selection["excluded"]:
                excluded_ids.add((identity["stat"]["dev"], identity["stat"]["ino"]))
                row["content_action"] = "prior_payload_excluded_no_open_no_rehash"
            else:
                row["content_action"] = "new_candidate_pending"
        except Exception as exc:
            if isinstance(exc, Stop):
                raise
            row.update(status="unavailable_or_unresolved", error=repr(exc), content_action="none")
        emit(row)

    for index, item in enumerate(selection["selected"]):
        check()
        path = item["path"]
        identity = identities.get(path)
        if not identity:
            continue
        endpoint = identity["resolved"]
        pin = identity["stat"]
        key = pin["dev"], pin["ino"]
        if path in selection["excluded"] or endpoint in selection["excluded"] or key in excluded_ids:
            emit(dict(type="skip", path=path, resolved=endpoint, reason="prior path/resolved/inode content excluded"))
            continue
        if key in new_ids:
            emit(dict(type="skip", path=path, resolved=endpoint, reason="same current inode already acquired this selection"))
            continue
        if not stat.S_ISREG(pin["mode"]):
            emit(dict(type="skip", path=path, resolved=endpoint, reason="not a regular file"))
            continue
        if pin["bytes"] > caps["file_bytes"]:
            raise Stop("64MiB file cap; stop exact five without refill")
        if payload_bytes + pin["bytes"] > caps["total_payload_bytes"]:
            raise Stop("192MiB aggregate cap before next file; no fit-to-budget selection")
        if endpoint not in selection["allowed_content_endpoints"]:
            raise Stop("endpoint outside exact five; no content read or replacement")
        fd = os.open(endpoint, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            before = info(os.fstat(fd))
            if before != pin or (before["dev"], before["ino"]) in excluded_ids:
                raise ValueError("endpoint drift or acquired inode; no content read")
            current = resolve(path)
            if current != identity:
                raise ValueError("path/link identity changed before read")
            emit(dict(type="begin", id=index, path=path, resolved=endpoint, before=before))
            digest, size = hashlib.sha256(), 0
            while size < before["bytes"]:
                check()
                block = os.read(fd, min(1024**2, before["bytes"] - size))
                if not block:
                    raise ValueError("unexpected EOF; partial retained")
                digest.update(block)
                size += len(block)
                payload_bytes += len(block)
                wire.write(b"D" + struct.pack(">I", len(block)) + block)
                wire.flush()
            after = info(os.fstat(fd))
            current = resolve(path)
            if before != after or current != identity:
                raise ValueError("native file/link identity changed during read; partial unknown")
            new_ids.add(key)
            emit(dict(type="end", id=index, path=path, resolved=endpoint, after=after, bytes=size,
                      sha256=digest.hexdigest(), stable=True))
        finally:
            os.close(fd)
    complete = True
except BaseException as exc:
    reason = repr(exc)
try:
    emit(dict(type="completion", complete=complete, reason=reason, elapsed_s=time.monotonic() - started,
              identity_paths_attempted=attempted, payload_bytes=payload_bytes, new_inodes=len(new_ids),
              metadata_bytes_before_completion=metadata_bytes, all_qualifications=False, dispatchable=False), final=True)
finally:
    signal.alarm(0)
