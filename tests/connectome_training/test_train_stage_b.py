import json
import subprocess
import sys


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
    assert report["trainable"] == [
        "input_gain",
        "type_bias_mv",
        "tau_m_ms",
        "descending_readout",
    ]
    assert json.loads(completed.stdout)["passed"] is True
