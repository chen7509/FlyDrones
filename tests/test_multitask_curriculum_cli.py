from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from flydrones.multitask_curriculum import CurriculumConfig, RunLock
from tools.run_multitask_curriculum import _success_score

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


def test_conventional_reflex_trains_actor_but_cannot_claim_live_malecns(tmp_path):
    run_cli(
        "--output",
        str(tmp_path),
        "--reflex-backend",
        "conventional",
        "--max-batches",
        "1",
    )

    state = read_state(tmp_path)
    report_path = next((tmp_path / "reports").glob("batch-*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["training"]["actor_samples"] > 0
    assert report["training"]["male_cns_backend"] == "geometric-v1"
    assert report["evaluation"]["male_cns_backend"] == "geometric-v1"
    assert report["promotion"]["live_malecns"] is False
    assert report["promotion"]["promoted"] is False
    with pytest.raises(subprocess.CalledProcessError):
        run_cli("--output", str(tmp_path), "--max-batches", "1")
    assert read_state(tmp_path) == state


def test_conventional_backend_advances_training_without_deployment_promotion(tmp_path):
    changed = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    first = changed["profiles"]["desktop"][0]
    first["steps_per_batch"] = 512
    first["maximum_batches"] = 1
    first["patience"] = 1
    config = tmp_path / "reachable.yaml"
    config.write_text(yaml.safe_dump(changed), encoding="utf-8")
    output = tmp_path / "run"

    run_cli(
        "--profile",
        "desktop",
        "--output",
        str(output),
        "--reflex-backend",
        "conventional",
        "--max-batches",
        "1",
        config=config,
    )

    state = read_state(output)
    report = json.loads(
        (output / "reports" / "batch-0-0.json").read_text(encoding="utf-8")
    )
    assert report["evaluation"]["metrics"]["exit_success"] == 1.0
    assert report["promotion"]["curriculum_advanced"] is True
    assert report["promotion"]["promoted"] is False
    assert state["stage_index"] == 1
    assert state["best_score"] is None


def test_success_score_uses_positive_outcomes_and_inverts_error_metrics():
    config = CurriculumConfig.load(CONFIG)
    search = config.profiles["desktop"][3]
    formation = config.profiles["desktop"][4]

    assert _success_score(
        search,
        {"search_coverage": 1.0, "duplicate_coverage": 0.18},
    ) == 1.0
    assert _success_score(formation, {"formation_rmse_m": 0.1}) == 0.75
