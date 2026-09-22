import json
from pathlib import Path
import subprocess
import sys


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
            "--output",
            str(tmp_path / "profile.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    assert report["schema"] == "flydrones-connectome-profile-v1"
    assert report["controller_identity"] == "deterministic-fake"
    assert report["latency"]["samples"] == 4
    assert report["gates"]["complete_fly_p95_s"] == 0.035
    assert json.loads(completed.stdout)["output"].endswith("profile.json")
