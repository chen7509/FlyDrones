"""Bounded read-only PX4 startup log observer for a separate diagnostic run.

First-observed monotonic times are upper bounds on file visibility, never PX4
event times. This observer does not launch PX4, Gazebo, or MAVLink traffic.
"""

from __future__ import annotations

import argparse
import json
import os
import stat as statmod
import time
from collections.abc import Callable
from pathlib import Path

MARKERS = (
    "Gazebo world is ready",
    "PX4_GZ_MODEL_NAME set",
    "setting initial absolute time",
    "world: fly_ego_benchmark",
    "[mavlink] mode: Onboard",
    "Startup script returned successfully",
    "Startup script returned with return value:",
)
_MAX_LOG_BYTES = 1_048_576
_POLL_SECONDS = 0.02


def observe_px4_startup(
    log_path: Path,
    output_path: Path,
    *,
    max_wall_ns: int,
    now_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
    on_ready: Callable[[], None] | None = None,
) -> dict:
    """Observe a newly created log; announce readiness after the absence check."""
    if type(max_wall_ns) is not int or not 0 < max_wall_ns <= 300_000_000_000:
        raise ValueError("observer deadline invalid")
    log_path = Path(log_path)
    output_path = Path(output_path)
    if log_path.resolve(strict=False) == output_path.resolve(strict=False):
        raise ValueError("log and output refer to the same path")
    with output_path.open("x", encoding="utf8") as output:
        start = now_ns()
        result: dict = {
            "schema": "flydrones-px4-startup-observer-v1",
            "status": "observer_failed",
            "time_semantics": "first_observed_not_px4_event_time",
            "started_mono_ns": start,
            "ended_mono_ns": None,
            "deadline_ns": max_wall_ns,
            "log_path": str(log_path.absolute()),
            "log_identity": None,
            "bytes_read": 0,
            "markers": dict.fromkeys(MARKERS),
        }
        identity = None
        consumed = b""
        pending = b""
        line_number = 0
        try:
            try:
                log_path.lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError("log existed before observer start")
            if on_ready is not None:
                on_ready()
            while True:
                if now_ns() - start >= max_wall_ns:
                    result["status"] = "deadline_partial" if identity else "deadline_without_log"
                    break
                try:
                    path_stat = log_path.lstat()
                except FileNotFoundError:
                    path_stat = None
                if path_stat is not None:
                    if not statmod.S_ISREG(path_stat.st_mode):
                        raise ValueError("log is not a regular file")
                    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                    with os.fdopen(os.open(log_path, flags), "rb") as source:
                        file_stat = os.fstat(source.fileno())
                        current = (file_stat.st_dev, file_stat.st_ino)
                        if current != (path_stat.st_dev, path_stat.st_ino):
                            raise ValueError("log identity changed")
                        if identity is None:
                            identity = current
                            result["log_identity"] = {"device": file_stat.st_dev, "inode": file_stat.st_ino}
                        elif current != identity:
                            raise ValueError("log identity changed")
                        if file_stat.st_size < len(consumed):
                            raise ValueError("log was truncated")
                        if file_stat.st_size > _MAX_LOG_BYTES:
                            raise ValueError("log exceeded byte limit")
                        all_data = source.read(_MAX_LOG_BYTES + 1)
                    try:
                        after_stat = log_path.lstat()
                    except FileNotFoundError as exc:
                        raise ValueError("log disappeared after observation") from exc
                    if (after_stat.st_dev, after_stat.st_ino) != current:
                        raise ValueError("log identity changed")
                    if len(all_data) > _MAX_LOG_BYTES:
                        raise ValueError("log exceeded byte limit")
                    if not all_data.startswith(consumed):
                        raise ValueError("log prefix changed after observation")
                    new = all_data[len(consumed):]
                    consumed = all_data
                    result["bytes_read"] = len(consumed)
                    pending += new
                    while b"\n" in pending:
                        raw, pending = pending.split(b"\n", 1)
                        line_number += 1
                        line = raw.decode("utf8", errors="replace")
                        observed_at = now_ns()
                        if observed_at - start >= max_wall_ns:
                            result["status"] = "deadline_partial"
                            break
                        for marker in MARKERS:
                            if marker in line and result["markers"][marker] is None:
                                result["markers"][marker] = {
                                    "observed_mono_ns": observed_at, "line": line_number,
                                }
                    if result["status"] == "deadline_partial":
                        break
                    if result["markers"][MARKERS[-1]] is not None:
                        result["status"] = "startup_failed"
                        break
                    if result["markers"][MARKERS[-2]] is not None:
                        result["status"] = "startup_completed"
                        break
                elif identity is not None:
                    raise ValueError("log disappeared after observation")
                sleep(_POLL_SECONDS)
        except Exception as exc:
            result["failure"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            result["ended_mono_ns"] = now_ns()
            json.dump(result, output, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-wall-seconds", type=int, default=15)
    args = parser.parse_args()
    result = observe_px4_startup(
        args.log, args.output, max_wall_ns=args.max_wall_seconds * 1_000_000_000,
    )
    return 0 if result["status"] == "startup_completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
