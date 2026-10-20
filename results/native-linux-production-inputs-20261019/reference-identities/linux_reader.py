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


reason=None
attempted=0
complete=False
emit(dict(type="start",selected=len(selection["selected"]),pid=os.getpid(),identity_only=True,no_linux_file_writes=True))
try:
    for item in selection["selected"]:
        check()
        if time.monotonic()-started>=10:raise Stop("identity metadata window exhausted")
        path=item["path"];attempted+=1
        try:
            identity=resolve(path)
            emit(dict(type="identity",path=path,**identity,status="observed",content_read=False))
        except (FileNotFoundError,NotADirectoryError) as exc:
            emit(dict(type="identity",path=path,status="unavailable",error=repr(exc),content_read=False))
    complete=True
except BaseException as exc:reason=repr(exc)
try:
    emit(dict(type="completion",complete=complete,identity_only=True,attempted=attempted,payload_bytes=0,
              reason=reason,elapsed_s=time.monotonic()-started,all_qualifications=False,dispatchable=False),final=True)
finally:signal.alarm(0)
