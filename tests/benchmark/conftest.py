"""Executor software tests may never rely on a missing per-test process stub."""

import pytest

from tools.benchmark.software_process_boundary import guard_required, install


@pytest.fixture(autouse=True)
def static_executor_process_boundary(request, monkeypatch):
    if guard_required(request.node.path):
        install(monkeypatch)
