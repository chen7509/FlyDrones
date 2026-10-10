"""The logger file is an offline source diagnostic candidate, never a flight grant."""

import importlib
import json
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
