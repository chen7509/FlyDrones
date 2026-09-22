import json
import subprocess
import sys

import pytest
import torch

from tools.train_multitask import _gae_targets


def test_train_and_evaluate_smoke_are_reproducible(tmp_path):
    checkpoint = tmp_path / "checkpoint.pt"
    train_report = tmp_path / "train.json"
    command = [
        sys.executable,
        "tools/train_multitask.py",
        "--level",
        "0",
        "--seed",
        "5",
        "--steps",
        "16",
        "--checkpoint",
        str(checkpoint),
        "--report",
        str(train_report),
    ]
    subprocess.run(command, check=True)
    first = json.loads(train_report.read_text(encoding="utf-8"))
    subprocess.run(command, check=True)
    second = json.loads(train_report.read_text(encoding="utf-8"))
    assert first["manifest_digest"] == second["manifest_digest"]
    assert first["seed"] == second["seed"] == 5
    assert checkpoint.exists()

    evaluation = tmp_path / "evaluation.json"
    subprocess.run(
        [
            sys.executable,
            "tools/evaluate_multitask.py",
            "--checkpoint",
            str(checkpoint),
            "--seeds",
            "5,6",
            "--episodes",
            "2",
            "--report",
            str(evaluation),
        ],
        check=True,
    )
    result = json.loads(evaluation.read_text(encoding="utf-8"))
    assert result["central_control_commands"] == 0
    assert len(result["episodes"]) == 2
    assert result["admission"]["passed"] is False
    assert result["admission"]["failures"]

    summary = tmp_path / "summary.json"
    subprocess.run(
        [
            sys.executable,
            "tools/evaluate_multitask.py",
            "--summary",
            "--train-report",
            str(train_report),
            "--evaluation-report",
            str(evaluation),
            "--config",
            "configs/multitask_training.yaml",
            "--test-command",
            "pytest tests/test_multitask_tools.py -q",
            "--test-result",
            "1 passed",
            "--report",
            str(summary),
        ],
        check=True,
    )
    evidence = json.loads(summary.read_text(encoding="utf-8"))
    assert evidence["checkpoint_digest"] == result["checkpoint_digest"]
    assert len(evidence["scenario_digests"]) == 3
    assert evidence["test_result"] == "1 passed"


def test_gae_keeps_interleaved_vehicle_trajectories_independent():
    samples = [
        {"vehicle_id": 0, "reward": 1.0, "value": torch.tensor(0.0), "done": False},
        {"vehicle_id": 1, "reward": 10.0, "value": torch.tensor(0.0), "done": False},
        {"vehicle_id": 0, "reward": 2.0, "value": torch.tensor(0.0), "done": True},
        {"vehicle_id": 1, "reward": 20.0, "value": torch.tensor(0.0), "done": True},
    ]
    advantages, returns = _gae_targets(samples, gamma=0.99, gae_lambda=0.95)
    factor = 0.99 * 0.95
    assert advantages.tolist() == pytest.approx(
        [1.0 + factor * 2.0, 10.0 + factor * 20.0, 2.0, 20.0]
    )
    assert returns.tolist() == pytest.approx(advantages.tolist())
