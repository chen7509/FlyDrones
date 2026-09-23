from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from flydrones.multitask_curriculum import RunLock

CONFIG = Path("configs/multitask_training.yaml")


def run_cli(*arguments: str, config: Path = CONFIG):
    return subprocess.run(
        [
            sys.executable,
            "tools/run_multitask_curriculum.py",
            "--config",
            str(config),
            "--device",
            "cpu",
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def read_state(output: Path) -> dict[str, object]:
    return json.loads((output / "state.json").read_text(encoding="utf-8"))


@contextmanager
def held_run_lock(output: Path):
    with RunLock(output):
        yield


def test_smoke_curriculum_runs_and_resumes_without_repeating_batch(tmp_path):
    run_cli(
        "--profile",
        "smoke",
        "--output",
        str(tmp_path),
        "--max-batches",
        "1",
    )
    first = read_state(tmp_path)
    run_cli(
        "--profile",
        "smoke",
        "--output",
        str(tmp_path),
        "--max-batches",
        "1",
    )
    second = read_state(tmp_path)

    assert second["last_committed_batch"] == first["last_committed_batch"] + 1
    assert second["batch_index"] == first["batch_index"] + 1
    assert (tmp_path / "latest-trainer.pt").exists()
    assert (tmp_path / "best-actor.pt").exists()
    assert list((tmp_path / "reports").glob("batch-*.json"))


def test_config_change_and_concurrent_writer_fail_closed(tmp_path):
    output = tmp_path / "run"
    run_cli("--output", str(output), "--max-batches", "1")
    before = read_state(output)
    changed = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    changed["seed"] += 1
    changed_path = tmp_path / "changed.yaml"
    changed_path.write_text(yaml.safe_dump(changed), encoding="utf-8")

    with pytest.raises(subprocess.CalledProcessError):
        run_cli(
            "--output",
            str(output),
            "--max-batches",
            "1",
            config=changed_path,
        )
    with held_run_lock(output):
        with pytest.raises(subprocess.CalledProcessError):
            run_cli("--output", str(output), "--max-batches", "1")

    assert read_state(output) == before


def test_restart_preserves_existing_evidence_in_a_new_run_directory(tmp_path):
    run_cli("--output", str(tmp_path), "--max-batches", "1")
    original = read_state(tmp_path)

    completed = run_cli(
        "--output",
        str(tmp_path),
        "--restart",
        "--max-batches",
        "1",
    )

    restarted_path = Path(json.loads(completed.stdout)["output_directory"])
    assert restarted_path.parent == tmp_path
    assert restarted_path != tmp_path
    assert read_state(tmp_path) == original
    assert (restarted_path / "state.json").exists()
