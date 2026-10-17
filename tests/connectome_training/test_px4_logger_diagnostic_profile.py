"""The logger file is an offline source diagnostic candidate, never a flight grant."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOPICS = (
    b"vehicle_odometry 0 0\n"
    b"vehicle_status 100 0\n"
    b"vehicle_attitude 20 0\n"
    b"vehicle_local_position 20 0\n"
    b"estimator_status 20 0\n"
    b"estimator_selector_status 100 0\n"
    b"sensor_combined 0 0\n"
    b"timesync_status 1000 0\n"
    b"logger_status 100 0\n"
    b"failsafe_flags 100 0\n"
)
DECLARATION = {
    "schema": "flydrones.px4_logger_diagnostic.v1",
    "profile_id": "source-diagnostic-v1",
    "px4_commit": "d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
    "logger_source_sha256": "33c1cd7c55dc81d4fa53153b7f269401b67c7f6edc929707ec536203096bcfe5",
    "sdlog_profile": 0,
    "diagnostic_only": True,
    "topics_sha256": "0bb9a3d9b57c6a73c73e8fee75569b9e690857654c4631b6f6cd5b6654328994",
}


def api():
    return importlib.import_module("flydrones.connectome_training.px4_logger_diagnostic_profile")


def test_exact_diagnostic_profile_is_only_an_offline_candidate():
    result = api().audit_profile(TOPICS, DECLARATION)
    assert result.logger_file_candidate is True
    assert result.reason == "logger_file_candidate_only"
    assert result.runtime_topic_selection_verified is False
    assert result.dds_ulog_parity_verified is False
    assert result.source_authenticated is False
    assert result.eligible_for_training is False


@pytest.mark.parametrize("mutated", [
    TOPICS.replace(b"vehicle_odometry 0 0", b"vehicle_odometry 20 0"),
    TOPICS + b"vehicle_odometry 0 0\n",
    TOPICS + b"sensor_gyro 0 0\n",
    TOPICS.replace(b"\n", b"\r\n"),
    TOPICS[:-1],
    TOPICS.replace(b"timesync_status 1000 0", b"timesync_status -1 0"),
])
def test_changed_or_malformed_topic_file_refuses(mutated):
    result = api().audit_profile(mutated, DECLARATION)
    assert result.logger_file_candidate is False
    assert result.reason != "logger_file_candidate_only"
    assert result.eligible_for_training is False


@pytest.mark.parametrize("change", [
    {"sdlog_profile": True},
    {"sdlog_profile": 131},
    {"diagnostic_only": False},
    {"px4_commit": "other"},
    {"logger_source_sha256": "0" * 64},
    {"topics_sha256": "0" * 64},
    {"extra": "unreviewed"},
])
def test_changed_declaration_refuses(change):
    result = api().audit_profile(TOPICS, DECLARATION | change)
    assert result.logger_file_candidate is False
    assert result.source_authenticated is False


def test_committed_fixtures_match_spec_literal():
    topics = ROOT / "config/px4/source-diagnostic-v1/logger_topics.txt"
    declaration = ROOT / "config/px4/source-diagnostic-v1/profile.json"
    assert topics.read_bytes() == TOPICS
    assert len(topics.read_bytes()) == 230
    assert json.loads(declaration.read_text(encoding="utf-8")) == DECLARATION


def run_cli(topics: Path, declaration: Path):
    script = ROOT / "tools/connectome/audit_px4_logger_diagnostic.py"
    return subprocess.run(
        [sys.executable, str(script), "--topics", str(topics),
         "--declaration", str(declaration)],
        capture_output=True, text=True, check=False, timeout=10,
    )


def test_cli_accepts_only_offline_candidate_without_training_grant():
    folder = ROOT / "config/px4/source-diagnostic-v1"
    completed = run_cli(folder / "logger_topics.txt", folder / "profile.json")
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["audit"]["logger_file_candidate"] is True
    assert result["audit"]["source_authenticated"] is False
    assert result["audit"]["eligible_for_training"] is False


def test_cli_retains_structured_refusal_for_mutation_and_missing_file(tmp_path):
    topics = tmp_path / "logger_topics.txt"
    topics.write_bytes(TOPICS.replace(b"vehicle_odometry 0 0", b"vehicle_odometry 20 0"))
    declaration = ROOT / "config/px4/source-diagnostic-v1/profile.json"
    changed = run_cli(topics, declaration)
    assert changed.returncode == 1
    assert json.loads(changed.stdout)["audit"]["logger_file_candidate"] is False
    missing = run_cli(tmp_path / "missing.txt", declaration)
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["audit"]["reason"] == "input_unavailable"


def test_cli_refuses_duplicate_declaration_keys(tmp_path):
    declaration = tmp_path / "profile.json"
    declaration.write_text(
        json.dumps(DECLARATION)[:-1] + ', "sdlog_profile": 0}', encoding="utf-8"
    )
    topics = ROOT / "config/px4/source-diagnostic-v1/logger_topics.txt"
    completed = run_cli(topics, declaration)
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["audit"]["reason"] == "declaration_json_invalid"


def test_cli_missing_required_option_keeps_structured_refusal():
    script = ROOT / "tools/connectome/audit_px4_logger_diagnostic.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--topics", str(ROOT / "config/px4/source-diagnostic-v1/logger_topics.txt")],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["audit"]["reason"] == "cli_arguments_invalid"
    assert result["audit"]["logger_file_candidate"] is False
    assert result["eligible_for_live_capture"] is False
