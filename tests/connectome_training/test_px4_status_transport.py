"""Pinned PX4 DDS status preflight, without launching or changing firmware."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/px4_status_transport"
BASE = (FIXTURES / "dds_topics.d6f12ad.yaml").read_bytes()
MESSAGE = (FIXTURES / "EstimatorStatus.d6f12ad.msg").read_bytes()
NEWER_MESSAGE = (FIXTURES / "EstimatorStatus.newer-px4-msg.msg").read_bytes()
ANCHOR = (b"  - topic: /fmu/out/estimator_status_flags\n"
          b"    type: px4_msgs::msg::EstimatorStatusFlags\n"
          b"    rate_limit: 5.\n")
ADDITION = (b"  - topic: /fmu/out/estimator_status\n"
            b"    type: px4_msgs::msg::EstimatorStatus\n"
            b"    rate_limit: 20.\n")


def _candidate() -> bytes:
    assert BASE.count(ANCHOR) == 1
    return BASE.replace(ANCHOR, ANCHOR + ADDITION)


def _audit(tmp_path, *, base=BASE, candidate=None, px4_msg=MESSAGE, ros_msg=MESSAGE):
    files = {}
    for name, content in (
            ("base", base), ("candidate", base if candidate is None else candidate),
            ("px4_msg", px4_msg), ("ros_msg", ros_msg)):
        path = tmp_path / name
        path.write_bytes(content)
        files[name] = path
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    process = subprocess.run(
        [sys.executable, "-m", "flydrones.connectome_training.px4_status_transport",
         "--base", str(files["base"]), "--candidate", str(files["candidate"]),
         "--px4-msg", str(files["px4_msg"]), "--ros-msg", str(files["ros_msg"])],
        env=env, text=True, capture_output=True, timeout=10, check=False,
    )
    return process, json.loads(process.stdout) if process.stdout.strip() else {}


def test_actual_pinned_config_explicitly_reports_missing_transport(tmp_path):
    process, result = _audit(tmp_path)
    assert process.returncode == 0, process.stderr
    assert result["base_status_published"] is False
    assert result["source_candidate_ready"] is False
    assert result["missing"] == ["/fmu/out/estimator_status"]
    assert result["firmware_compiled_verified"] is False
    assert result["training_eligible"] is False


def test_exact_candidate_changes_one_publication_but_never_grants_runtime(tmp_path):
    process, result = _audit(tmp_path, candidate=_candidate())
    assert process.returncode == 0, process.stderr
    assert result["base_status_published"] is False
    assert result["source_candidate_ready"] is True
    assert result["candidate_status_rate_hz"] == 20.0
    for key in ("firmware_compiled_verified", "live_source_authenticated",
                "camera_calibration_qualified", "fusion_qualified", "training_eligible"):
        assert result[key] is False


@pytest.mark.parametrize("candidate", [
    _candidate().replace(b"rate_limit: 20.", b"rate_limit: 5."),
    _candidate().replace(b"px4_msgs::msg::EstimatorStatus\n",
                         b"px4_msgs::msg::EstimatorStatusFlags\n"),
    _candidate().replace(ADDITION, ADDITION + ADDITION),
    _candidate() + b"\npublications: []\n",
])
def test_candidate_rate_type_duplicate_or_extra_mapping_refuses(tmp_path, candidate):
    process, result = _audit(tmp_path, candidate=candidate)
    assert process.returncode != 0
    assert result["source_candidate_ready"] is False
    assert result["training_eligible"] is False


def test_nonpinned_base_and_missing_status_field_refuse(tmp_path):
    changed_base = BASE.replace(b"#####\n", b"####x\n", 1)
    process, result = _audit(tmp_path, base=changed_base, candidate=_candidate())
    assert process.returncode != 0
    assert result["source_candidate_ready"] is False
    bad_message = MESSAGE.replace(b"uint32 filter_fault_flags", b"uint32 hidden_fault_flags")
    process, result = _audit(tmp_path, candidate=_candidate(), px4_msg=bad_message)
    assert process.returncode != 0
    assert result["source_candidate_ready"] is False


def test_earlier_newer_px4_msgs_snapshot_is_not_a_matched_interface(tmp_path):
    process, result = _audit(tmp_path, candidate=_candidate(), ros_msg=NEWER_MESSAGE)
    assert process.returncode != 0
    assert result["source_candidate_ready"] is False
    assert result["ros_msg_exact"] is False


def test_malformed_yaml_key_still_returns_a_structured_refusal(tmp_path):
    process, result = _audit(tmp_path, candidate=b"publications:\n  ? [x]\n  : 1\n")
    assert process.returncode != 0
    assert result["source_candidate_ready"] is False
    assert result["training_eligible"] is False


def test_candidate_artifact_is_exactly_the_declared_change():
    candidate = ROOT / "configs/px4/estimator-status-dds-candidate.yaml"
    assert candidate.read_bytes() == _candidate()
