"""Inert backend proof only; never starts an external process."""

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_autouse_guard_is_installed_without_calling_os_backend():
    import os
    import subprocess

    expected_module = "tools.benchmark.software_process_boundary"
    assert subprocess.Popen._execute_child.__module__ == expected_module
    assert subprocess.Popen._execute_child.__name__ == "denied"
    assert os.system is subprocess.Popen._execute_child


def test_guard_blocks_saved_popen_class_without_reaching_backend(monkeypatch):
    from tools.benchmark.software_process_boundary import ProcessBoundaryError, install

    calls = []

    class SavedPopen:
        def _execute_child(self, *a, **kw):
            calls.append(a)

        def __init__(self, *a, **kw):
            self._execute_child(*a, **kw)

    process = SimpleNamespace(Popen=SavedPopen)
    operating = SimpleNamespace(system=lambda *a: calls.append(a), execve=lambda *a: calls.append(a))
    install(monkeypatch, process_api=process, os_api=operating)
    with pytest.raises(ProcessBoundaryError):
        SavedPopen(["wsl", "fixture"])
    with pytest.raises(ProcessBoundaryError):
        operating.system("fixture command")
    with pytest.raises(ProcessBoundaryError):
        operating.execve("/fixture", [], {})
    assert calls == []


def test_guard_permits_explicit_inert_protocol_double(monkeypatch):
    from tools.benchmark.software_process_boundary import install

    class SavedPopen:
        def _execute_child(self):
            raise AssertionError("inert original must not run")

    process = SimpleNamespace(Popen=SavedPopen)
    install(monkeypatch, process_api=process, os_api=SimpleNamespace())
    marker = object()
    monkeypatch.setattr(process, "Popen", lambda *a, **kw: marker)
    assert process.Popen("inert protocol") is marker


@pytest.mark.parametrize(
    "name,expected",
    [
        ("test_calibration_static_v3_executor.py", True),
        ("test_calibration_static_v4_executor.py", True),
        ("test_static_harness_containment.py", True),
        ("test_openvins_dataset_consumer.py", False),
        ("test_capture_contract.py", False),
    ],
)
def test_guard_selection_is_explicit(name, expected):
    from tools.benchmark.software_process_boundary import guard_required

    assert guard_required(Path(name)) is expected
