"""Parse only the pinned PX4 read-only ``mavlink status`` startup evidence.

This is text syntax validation, not an owned socket, live link, or fusion proof.
"""
from __future__ import annotations

import re

_MAX_BYTES = 32_768
_MODE = re.compile(rb"\tmode: ([A-Za-z][A-Za-z -]*)\Z")
_UDP = re.compile(rb"\ttransport protocol: UDP \(([0-9]{1,5}), remote port: ([0-9]{1,5})\)\Z")
_LOCAL, _REMOTE = 14_588, 14_548


def parse_mavlink_status(raw: bytes, exit_code: int) -> dict:
    """Require one exact Onboard UDP endpoint within one complete PX4 response."""
    if type(raw) is not bytes or len(raw) > _MAX_BYTES or type(exit_code) is not int:
        raise ValueError("invalid MAVLink status response type or size")
    if exit_code == 1 and raw == b"":
        return dict(phase="pending", reason="no-instances", authority=False,
                    fusion_qualified=False)
    if exit_code != 0 or not raw.startswith(b"\ninstance #0:\n") or not raw.endswith(b"\n"):
        raise ValueError("incomplete or failed MAVLink status response")
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("non-ASCII MAVLink status response") from exc
    parts = raw.split(b"\ninstance #")
    if parts[0] != b"" or len(parts) < 2:
        raise ValueError("MAVLink status instance framing")
    selected = []
    for ordinal, part in enumerate(parts[1:]):
        lines = part.split(b"\n")
        if lines[0] != str(ordinal).encode() + b":" or lines[-1] != b"":
            raise ValueError("MAVLink status instance order or terminal newline")
        modes = [line for line in lines[1:-1] if line.startswith(b"\tmode:")]
        transports = [line for line in lines[1:-1] if line.startswith(b"\ttransport protocol:")]
        if len(modes) != 1 or len(transports) != 1:
            raise ValueError("MAVLink status mode/transport count")
        mode = _MODE.fullmatch(modes[0])
        if mode is None:
            raise ValueError("MAVLink status mode syntax")
        udp = _UDP.fullmatch(transports[0])
        if udp is None:
            # This declared SITL profile starts only UDP instances. Accepting a
            # malformed non-selected line would make the whole response weaker.
            raise ValueError("MAVLink status transport is not pinned UDP syntax")
        local, remote = (int(udp[1]), int(udp[2]))
        if not 1 <= local <= 65_535 or not 1 <= remote <= 65_535:
            raise ValueError("MAVLink status UDP port range")
        if local == _LOCAL or remote == _REMOTE:
            if (local, remote) != (_LOCAL, _REMOTE) or mode[1] != b"Onboard":
                raise ValueError("selected MAVLink endpoint identity changed")
            selected.append(ordinal)
    if len(selected) != 1:
        raise ValueError("missing or duplicate selected MAVLink endpoint")
    return dict(phase="ready", instance=selected[0], local_port=_LOCAL,
                remote_port=_REMOTE, authority=False, fusion_qualified=False)
