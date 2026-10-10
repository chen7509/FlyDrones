import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.connectome_training import profile_baseline


def test_profile_cli_writes_versioned_report_with_fake_controller(tmp_path):
    script = Path("tools/connectome_training/profile_baseline.py")
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--fake",
            "--samples",
            "4",
            "--warmup",
            "1",
            "--seed",
            "17",
            "--output",
            str(tmp_path / "profile.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    assert report["schema"] == "flydrones-connectome-profile-v2"
    assert report["controller_identity"] == "deterministic-fake"
    assert report["latency"]["samples"] == 4
    assert report["gates"]["complete_fly_p95_s"] == 0.035
    assert report["model"]["reset_seed"] == 17
    assert report["passed_complete_fly_p95"] is False
    assert report["latency_gate"]["eligible"] is False
    assert "not_complete_model" in report["latency_gate"]["reasons"]
    assert len(report["latency"]["raw_samples"]) == 4
    assert report["trained_policy_verified"] is False
    assert json.loads(completed.stdout)["output"].endswith("profile.json")


def test_fake_controller_never_passes_complete_fly_gate(tmp_path, monkeypatch):
    output = tmp_path / "fake.json"
    monkeypatch.setattr(sys, "argv", ["profile", "--fake", "--output", str(output)])
    profile_baseline.main()
    report = json.loads(output.read_text())
    assert report["passed_complete_fly_p95"] is False


def test_existing_evidence_is_not_overwritten(tmp_path, monkeypatch):
    output = tmp_path / "existing.json"
    output.write_bytes(b"previous failure evidence\n")
    monkeypatch.setattr(sys, "argv", ["profile", "--fake", "--output", str(output)])
    with pytest.raises(FileExistsError):
        profile_baseline.main()
    assert output.read_bytes() == b"previous failure evidence\n"


@pytest.mark.parametrize("outer, samples, neurons, connections, digest, expected", [
    (0.1, 30, 166700, 25582837, "a" * 64, False),
    (0.035, 30, 166700, 25582837, "a" * 64, True),
    (0.001, 1, 166700, 25582837, "a" * 64, False),
    (0.001, 30, 10, 25582837, "a" * 64, False),
    (0.001, 30, 166700, 1, "a" * 64, False),
    (0.001, 30, 166700, 25582837, "not-a-digest", False),
])
def test_gate_uses_outer_latency_and_full_identity(
    outer, samples, neurons, connections, digest, expected
):
    result = profile_baseline.evaluate_latency_gate(
        {"outer_s": {"p95": outer}, "total_s": {"p95": 0.001}, "samples": samples},
        identity="full-male-cns",
        model={"neurons": neurons, "connections": connections, "sha256": digest},
        maximum_p95_s=0.035, minimum_samples=30,
    )
    assert result["passed"] is expected
    assert result["basis"] == "outer_controller_step_wall_s"
