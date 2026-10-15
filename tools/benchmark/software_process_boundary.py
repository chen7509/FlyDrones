"""Default process boundary for audited static-executor software test bodies.

This is not an adversarial Python/FFI or collection-time sandbox. Deliberate
native studies run outside these executor unit tests with their own admission.
"""

import os
import re
import subprocess
from pathlib import Path


class ProcessBoundaryError(RuntimeError):
    pass


def guard_required(path):
    name = Path(path).name
    return (
        name == "test_static_harness_containment.py"
        or name
        in {
            "test_native_loader_paths_v4.py",
            "test_native_entry_context_v4.py",
            "test_calibration_capture_study_v4.py",
        }
        or re.fullmatch(r"test_calibration_static_v[0-9]+_executor\.py", name) is not None
    )


def install(monkeypatch, *, process_api=subprocess, os_api=os):
    def denied(*args, **kwargs):
        raise ProcessBoundaryError("external OS process forbidden in static executor software test; use an inert protocol")

    # Patching the class method also catches an original Popen class reference
    # saved before fixture installation; ordinary subprocess helpers use it.
    monkeypatch.setattr(process_api.Popen, "_execute_child", denied)
    for name in (
        "system",
        "startfile",
        "fork",
        "forkpty",
        "posix_spawn",
        "posix_spawnp",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
    ):
        if hasattr(os_api, name):
            monkeypatch.setattr(os_api, name, denied)
