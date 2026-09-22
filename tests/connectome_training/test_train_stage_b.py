import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


def test_stage_b_cli_reduces_loss_and_writes_identity_artifacts(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "tools/connectome_training/train_stage_b.py",
            "--epochs",
            "25",
            "--output",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(
        (tmp_path / "smoke_report.json").read_text(encoding="utf-8")
    )
    assert report["schema"] == "flydrones-connectome-stage-b-smoke-v1"
    assert report["identity"] == "connectome-constrained-training-smoke"
    assert report["final_validation_loss"] < report["initial_validation_loss"]
    assert report["train_feature_sha256"] != report["validation_feature_sha256"]
    assert report["trainable"] == [
        "input_gain",
        "type_bias_mv",
        "tau_m_ms",
        "descending_readout",
    ]
    assert json.loads(completed.stdout)["passed"] is True


def test_stage_b_cli_rejects_an_unsupported_optimizer(tmp_path):
    config = yaml.safe_load(
        Path("configs/connectome_training_stage_b_v1.yaml").read_text(encoding="utf-8")
    )
    config["optimizer"]["name"] = "sgd"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as error:
        subprocess.run(
            [
                sys.executable,
                "tools/connectome_training/train_stage_b.py",
                "--epochs",
                "1",
                "--config",
                str(config_path),
                "--output",
                str(tmp_path / "output"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    assert "unsupported optimizer" in error.value.stderr
