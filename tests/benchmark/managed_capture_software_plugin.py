"""Windows-only modeled POSIX flags for injected wire fixtures, no native claim."""

import os
import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def inert_os_boundary(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("native process/network forbidden in software fixture")

    if os.name == "nt":
        monkeypatch.setattr(socket, "MSG_DONTWAIT", 64, raising=False)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(os, "system", denied)
