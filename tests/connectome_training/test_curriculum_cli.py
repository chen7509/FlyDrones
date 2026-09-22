import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


def smoke_config(tmp_path: Path) -> Path:
    value = yaml.safe_load(
        Path("configs/connectome_curriculum_v1.yaml").read_text(encoding="utf-8")
    )
    for stage in value["stages"][:2]:
        stage["epochs_per_batch"] = 15
        stage["max_batches"] = 2
        stage["maximum_validation_loss"] = 1.0
        stage["maximum_loss_ratio"] = 1.0
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def run_cli(config: Path, output: Path, *extra: str):
    return subprocess.run(
        [
            sys.executable,
            "tools/connectome_training/run_curriculum.py",
            "--config",
            str(config),
            "--profile",
            "smoke",
            "--output",
            str(output),
            *extra,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_cli_smoke_stops_and_resumes_without_replaying_batch(tmp_path):
    config = smoke_config(tmp_path)
    output = tmp_path / "run"
    first = run_cli(config, output, "--max-batches", "1")
    first_payload = json.loads(first.stdout)
    assert first_payload["status"] == "COMMITTED"
    assert first_payload["completed_stages"] == ["stability"]
    second = run_cli(config, output)
    second_payload = json.loads(second.stdout)
    assert second_payload["status"] == "COMPLETE"
    assert second_payload["completed_stages"] == ["stability", "looming"]
    reports = list((output / "reports").glob("*.json"))
    assert len(reports) == 2
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["evidence_class"] == "synthetic-connectome-curriculum-smoke"
    assert summary["model_identity"].startswith("tiny-connectome:")


def test_cli_restart_refuses_an_active_lock(tmp_path):
    config = smoke_config(tmp_path)
    output = tmp_path / "run"
    output.mkdir()
    (output / "run.lock").write_text('{"pid": 123}\n', encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_cli(config, output, "--restart", "--max-batches", "1")
    assert "already locked" in error.value.stderr


def test_full_profile_fails_closed_when_sequence_evidence_is_absent(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "tools/connectome_training/run_curriculum.py",
            "--config",
            "configs/connectome_curriculum_v1.yaml",
            "--profile",
            "desktop",
            "--output",
            str(tmp_path / "full"),
            "--max-batches",
            "1",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "sequence evidence path does not exist" in completed.stderr
