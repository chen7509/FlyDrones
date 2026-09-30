from __future__ import annotations

import hashlib
import json
import subprocess

from flydrones.multitask_summary import build_summary, write_summary


def test_summary_uses_git_hashes_and_completed_verification_record(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("schema_version: 2\n", encoding="utf-8")
    output = tmp_path / "run"
    reports = output / "reports"
    reports.mkdir(parents=True)
    (output / "latest-trainer.pt").write_bytes(b"trainer")
    (output / "best-actor.pt").write_bytes(b"actor")
    (output / "state.json").write_text(
        json.dumps(
            {
                "last_committed_batch": 3,
                "latest_checkpoint": "latest-trainer.pt",
                "best_actor": "best-actor.pt",
            }
        ),
        encoding="utf-8",
    )
    (reports / "batch-0-3.json").write_text(
        json.dumps(
            {
                "stage_index": 0,
                "batch_index": 3,
                "evaluation": {
                    "male_cns_backend": "unavailable",
                    "male_cns_fallbacks": 7,
                    "missing_evidence": ["male_cns_backend"],
                    "admission": {"passed": False},
                    "telemetry": {
                        "disturbance_injections": {"wind": 4},
                        "safety_failures": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    verification = tmp_path / "verification.json"
    verification.write_text(
        json.dumps({"command": "python -m pytest -q", "result": "267 passed"}),
        encoding="utf-8",
    )

    summary = build_summary(config, output, verification)

    expected_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert summary["git_commit"] == expected_commit
    assert summary["config_digest"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert summary["trainer_checkpoint_digest"] == hashlib.sha256(b"trainer").hexdigest()
    assert summary["best_actor_digest"] == hashlib.sha256(b"actor").hexdigest()
    assert summary["test_command"] == "python -m pytest -q"
    assert summary["test_result"] == "267 passed"
    assert summary["admission_passed"] is False

    destination = write_summary(config, output, verification)
    assert json.loads(destination.read_text(encoding="utf-8")) == summary
