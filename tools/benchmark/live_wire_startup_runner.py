"""Run one capture only after the read-only PX4 startup observer is ready.

This is a diagnostic runner, not a study declaration or permission to start a
physical capture. Its summary never grants bootstrap or fusion qualification.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from tools.benchmark.observe_px4_startup import observe_px4_startup

_SHA = re.compile(r"[0-9a-f]{64}\Z")


def run_observed_capture(
    command: list[str],
    *,
    log_path: Path,
    observation_path: Path,
    summary_path: Path,
    observer_deadline_ns: int,
    ready_timeout_s: float,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    study_manifest_sha256: str | None = None,
    diagnostic_declaration_sha256: str | None = None,
    **runner_kwargs,
) -> subprocess.CompletedProcess:
    """Preserve independent capture and observer results without inventing success."""
    if (type(observer_deadline_ns) is not int or not 0 < observer_deadline_ns <= 300_000_000_000
            or type(ready_timeout_s) not in (int, float) or not 0 < ready_timeout_s <= 10):
        raise ValueError("startup diagnostic deadline invalid")
    for digest in (study_manifest_sha256, diagnostic_declaration_sha256):
        if digest is not None and (type(digest) is not str or _SHA.fullmatch(digest) is None):
            raise ValueError("startup diagnostic identity invalid")
    paths = [Path(log_path), Path(observation_path), Path(summary_path)]
    resolved = [path.resolve(strict=False) for path in paths]
    if len(set(resolved)) != 3:
        raise ValueError("startup diagnostic paths overlap")
    if os.path.lexists(paths[1]) or os.path.lexists(paths[2]):
        raise ValueError("startup diagnostic output already exists")

    ready = threading.Event()
    state: dict = {}
    started = time.monotonic_ns()
    summary = {
        "schema": "flydrones-live-wire-startup-diagnostic-v1",
        "started_mono_ns": started,
        "ended_mono_ns": None,
        "observer_deadline_ns": observer_deadline_ns,
        "study_manifest_sha256": study_manifest_sha256,
        "diagnostic_declaration_sha256": diagnostic_declaration_sha256,
        "observer_ready": False,
        "observer_status": None,
        "observer_failure": None,
        "observer_thread_alive": None,
        "runner_invoked": False,
        "capture_returncode": None,
        "capture_failure": None,
        "qualification_granted": False,
    }

    def observe() -> None:
        try:
            state["observation"] = observe_px4_startup(
                paths[0], paths[1], max_wall_ns=observer_deadline_ns, on_ready=ready.set,
            )
        except BaseException as exc:
            state["observer_error"] = exc
        finally:
            ready.set()

    thread = threading.Thread(target=observe, name="px4-startup-observer", daemon=True)
    thread.start()
    completed = None
    failure = None
    try:
        if not ready.wait(ready_timeout_s):
            raise ValueError("observer readiness timeout before capture")
        if "observer_error" in state:
            raise ValueError("observer failed before capture") from state["observer_error"]
        summary["observer_ready"] = True
        summary["runner_invoked"] = True
        completed = runner(command, **runner_kwargs)
        if type(completed.returncode) is not int:
            raise ValueError("capture return code invalid")
        summary["capture_returncode"] = completed.returncode
    except BaseException as exc:
        failure = exc
        if summary["runner_invoked"]:
            summary["capture_failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        # The observer is bounded by its own deadline; a stuck observer is an
        # explicit diagnostic failure, not grounds to modify the capture result.
        thread.join(timeout=observer_deadline_ns / 1_000_000_000 + 2)
        summary["observer_thread_alive"] = thread.is_alive()
        observation = state.get("observation")
        if observation is not None:
            summary["observer_status"] = observation["status"]
        if "observer_error" in state:
            exc = state["observer_error"]
            summary["observer_failure"] = f"{type(exc).__name__}: {exc}"
        if thread.is_alive():
            summary["observer_failure"] = "observer thread exceeded bounded join"
        summary["ended_mono_ns"] = time.monotonic_ns()
        with paths[2].open("x", encoding="utf8") as output:
            json.dump(summary, output, indent=2, allow_nan=False)
            output.write("\n")
    if failure is not None:
        raise failure
    if summary["observer_failure"] is not None:
        raise ValueError("observer failed after capture")
    assert completed is not None
    return completed
