"""Construct machine-readable curriculum evidence only from committed artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"evidence file does not exist: {source}")
    return hashlib.sha256(source.read_bytes()).hexdigest()


def read_git_commit(directory: str | Path = ".") -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(directory),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _json_object(path: Path) -> dict[str, object]:
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError(f"evidence must contain an object: {path}")
    return values


def _latest_report(output: Path) -> dict[str, object]:
    candidates: list[tuple[tuple[int, int], dict[str, object]]] = []
    for path in (output / "reports").glob("batch-*.json"):
        report = _json_object(path)
        try:
            key = (int(report["stage_index"]), int(report["batch_index"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid committed batch report: {path}") from exc
        candidates.append((key, report))
    if not candidates:
        raise ValueError("no committed batch report is available")
    return max(candidates, key=lambda item: item[0])[1]


def build_summary(
    config_path: str | Path,
    output_directory: str | Path,
    verification_record_path: str | Path,
) -> dict[str, object]:
    config = Path(config_path).resolve()
    output = Path(output_directory).resolve()
    state = _json_object(output / "state.json")
    verification = _json_object(Path(verification_record_path))
    command = verification.get("command")
    result = verification.get("result")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("verification record command must be non-empty")
    if not isinstance(result, str) or not result.strip():
        raise ValueError("verification record result must be non-empty")
    latest_checkpoint = state.get("latest_checkpoint")
    best_actor = state.get("best_actor")
    if not isinstance(latest_checkpoint, str) or not isinstance(best_actor, str):
        raise ValueError("curriculum state does not reference committed models")
    report = _latest_report(output)
    evaluation = report.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise ValueError("latest report has no evaluation evidence")
    telemetry = evaluation.get("telemetry")
    admission = evaluation.get("admission")
    if not isinstance(telemetry, Mapping) or not isinstance(admission, Mapping):
        raise ValueError("latest evaluation evidence is incomplete")
    return {
        "schema_version": 1,
        "git_commit": read_git_commit(),
        "config_digest": sha256_file(config),
        "trainer_checkpoint_digest": sha256_file(output / latest_checkpoint),
        "best_actor_digest": sha256_file(output / best_actor),
        "last_committed_batch": int(state["last_committed_batch"]),
        "male_cns_backend": str(evaluation.get("male_cns_backend", "unavailable")),
        "male_cns_fallbacks": int(evaluation.get("male_cns_fallbacks", 0)),
        "disturbance_injections": dict(
            telemetry.get("disturbance_injections", {})
        ),
        "safety_failures": list(telemetry.get("safety_failures", [])),
        "missing_evidence": list(evaluation.get("missing_evidence", [])),
        "admission_passed": admission.get("passed") is True,
        "test_command": command,
        "test_result": result,
    }


def write_summary(
    config_path: str | Path,
    output_directory: str | Path,
    verification_record_path: str | Path,
) -> Path:
    output = Path(output_directory).resolve()
    destination = output / "summary.json"
    summary = build_summary(config_path, output, verification_record_path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return destination
