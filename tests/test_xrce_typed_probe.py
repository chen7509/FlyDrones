"""Frozen synthetic CDR preparation and test-client refusal boundaries."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/connectome/xrce_typed_probe/frozen_cdr.py"
ARCHIVE = ROOT / "evidence/px4-ros2-synthetic-v6-parity-dev-1701.zip"
BODY_SHA = "fcd9a9219bb6b082906ba71a013132f500210367bf8737915e395270e530aa82"
CLIENT_DIR = "/tmp/flydrones-agent-humble-1701-v3/build/temp_install/microxrcedds_client-2.4.3"
MICROCDR_DIR = "/tmp/flydrones-agent-humble-1701-v3/build/temp_install/microcdr-2.0.1"


def test_humble_qos_tuple_accepts_warning_but_rejects_error() -> None:
    spec = spec_from_file_location("xrce_graph_wait", ROOT /
                                   "tools/connectome/xrce_typed_probe/graph_wait.py")
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    class Compatibility(Enum):
        OK = 0
        WARNING = 1
        ERROR = 2

    assert module.qos_acceptable((Compatibility.OK, ""))
    assert module.qos_acceptable((Compatibility.WARNING, "system default unknown"))
    assert not module.qos_acceptable((Compatibility.ERROR, "incompatible"))


def test_postrun_audit_refuses_failed_cleanup_and_forged_preflight() -> None:
    script_dir = ROOT / "tools/connectome/xrce_typed_probe"
    sys.path.insert(0, str(script_dir))
    try:
        from audit import checked_cleanup, checked_preflight
    finally:
        sys.path.remove(str(script_dir))
    directory = ROOT / "results/xrce-typed-odometry-dev-1701-v10"
    preflight = json.loads((directory / "runtime-preflight.json").read_text())
    runtime = json.loads((directory / "runtime-result.json").read_text())
    inside = json.loads((directory / "inside-result.json").read_text())
    checked_preflight(preflight, directory)
    checked_cleanup(runtime, inside)
    altered = copy.deepcopy(preflight)
    altered["local_hashes"]["body"] = "0" * 64
    with pytest.raises(ValueError, match="preflight"):
        checked_preflight(altered, directory)
    altered = copy.deepcopy(runtime)
    altered["owned_after"]["returncode"] = 1
    with pytest.raises(ValueError, match="owned_after"):
        checked_cleanup(altered, inside)
    altered = copy.deepcopy(inside)
    altered["agent_cleanup_error"] = "RuntimeError('failed')"
    with pytest.raises(ValueError, match="agent cleanup"):
        checked_cleanup(runtime, altered)


def invoke(archive: Path, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(archive), str(target)],
                          capture_output=True, text=True, cwd=ROOT, timeout=10)


def test_prepares_exact_frozen_cdr_body(tmp_path: Path) -> None:
    target = tmp_path / "odometry-body.bin"
    result = invoke(ARCHIVE, target)
    assert result.returncode == 0, result.stderr
    body = target.read_bytes()
    assert len(body) == 116
    assert hashlib.sha256(body).hexdigest() == BODY_SHA
    record = json.loads((tmp_path / "odometry-body.bin.json").read_text())
    assert record["synthetic_only"] is True
    assert record["px4_source_authenticated"] is False
    assert record["topic"] == "/fmu/out/vehicle_odometry"


def test_refuses_replaced_archive_before_output(tmp_path: Path) -> None:
    changed = tmp_path / "changed.zip"
    changed.write_bytes(ARCHIVE.read_bytes() + b"extra")
    target = tmp_path / "odometry-body.bin"
    result = invoke(changed, target)
    assert result.returncode != 0
    assert not target.exists()


def test_refuses_existing_output_without_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "odometry-body.bin"
    target.write_bytes(b"keep")
    result = invoke(ARCHIVE, target)
    assert result.returncode != 0
    assert target.read_bytes() == b"keep"


@pytest.mark.skipif(os.getenv("FLYDRONES_XRCE_WSL_SMOKE") != "1",
                    reason="requires pinned WSL XRCE Client libraries")
def test_native_client_describes_and_validates_frozen_body(tmp_path: Path) -> None:
    source = ROOT / "tools/connectome/xrce_typed_probe/client.c"
    target = tmp_path / "xrce_probe"
    body = tmp_path / "body.bin"
    prepared = invoke(ARCHIVE, body)
    assert prepared.returncode == 0, prepared.stderr

    def wsl_path(path: Path) -> str:
        return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]

    compile_ = subprocess.run(
        ["wsl", "-d", "Ubuntu", "--", "gcc", "-std=c99", "-Wall", "-Wextra", "-Werror",
         "-I" + CLIENT_DIR + "/include", "-I" + MICROCDR_DIR + "/include",
         wsl_path(source), "-L" + CLIENT_DIR + "/lib", "-L" + MICROCDR_DIR + "/lib",
         "-Wl,-rpath," + CLIENT_DIR + "/lib", "-Wl,-rpath," + MICROCDR_DIR + "/lib",
         "-lmicroxrcedds_client", "-lmicrocdr", "-o", wsl_path(target)],
        capture_output=True, text=True, timeout=30,
    )
    assert compile_.returncode == 0, compile_.stderr
    describe = subprocess.run(["wsl", "-d", "Ubuntu", "--", wsl_path(target), "--describe"],
                              capture_output=True, text=True, timeout=10)
    assert describe.returncode == 0, describe.stderr
    identity = json.loads(describe.stdout)
    assert identity["topic"] == "rt/fmu/out/vehicle_odometry"
    assert identity["type"] == "px4_msgs::msg::dds_::VehicleOdometry_"
    assert identity["message_version"] == 0
    accepted = subprocess.run(["wsl", "-d", "Ubuntu", "--", wsl_path(target),
                               "--self-test", wsl_path(body)], capture_output=True, text=True,
                              timeout=10)
    assert accepted.returncode == 0, accepted.stderr
    short = tmp_path / "short.bin"
    short.write_bytes(b"too-short")
    rejected = subprocess.run(["wsl", "-d", "Ubuntu", "--", wsl_path(target),
                               "--self-test", wsl_path(short)], capture_output=True, text=True,
                              timeout=10)
    assert rejected.returncode != 0

    for values, allowed in ((["0", "0", "0", "0"], True),
                            (["1", "0", "0", "0"], True),
                            (["0", "0", "0", "128"], False)):
        checked = subprocess.run(["wsl", "-d", "Ubuntu", "--", wsl_path(target),
                                  "--check-statuses", *values], capture_output=True,
                                 text=True, timeout=10)
        assert (checked.returncode == 0) is allowed

    ready = tmp_path / "ready.txt"
    ready.write_bytes(b"ready\n")
    marker = subprocess.run(["wsl", "-d", "Ubuntu", "--", wsl_path(target),
                             "--check-ready", wsl_path(ready)], capture_output=True,
                            text=True, timeout=10)
    assert marker.returncode == 0
    ready.write_bytes(b"ready-but-not-exact\n")
    malformed = subprocess.run(["wsl", "-d", "Ubuntu", "--", wsl_path(target),
                                "--check-ready", wsl_path(ready)], capture_output=True,
                               text=True, timeout=10)
    assert malformed.returncode != 0
