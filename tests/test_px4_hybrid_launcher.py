import shutil
import subprocess
from pathlib import Path

import pytest


def test_launcher_resolves_repo_to_a_wsl_mount_path_without_starting_simulation():
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    script = Path(__file__).parents[1] / "Start-PX4-Hybrid-Swarm.ps1"
    completed = subprocess.run(
        [powershell, "-NoProfile", "-File", str(script), "-ResolveOnly"],
        check=True,
        capture_output=True,
        text=True,
    )
    resolved = completed.stdout.strip().replace("\\", "/")
    assert resolved.startswith("/mnt/")
    assert resolved.endswith("/FlyDrones")
