import json
from types import SimpleNamespace

import pytest


def study(tmp_path, *, role="source_loss", expected=2):
    root = tmp_path / "study"
    root.mkdir()
    destination = root / "capture-v1"
    profile = (
        "imu-source-loss-after-8s-v1" if role == "source_loss" else "native-restart-after-8s-v1"
    )
    status = "capture_failed" if role == "source_loss" else "capture_completed"
    manifest = {
        "schema": "openvins-health-physical-fault-preflight-v1",
        "prepare_only": True,
        "run_id": role + "-seed-1",
        "role": role,
        "seed": 1,
        "health_fault_profile": profile,
        "expected_capture_status": status,
        "expected_command_returncode": expected,
        "future_destination": str(destination),
        "command": ["python", "capture.py"],
        "fault_result_viewed": False,
        "test_set_tuning_allowed": False,
        "fusion_eligible": False,
    }
    (root / "study-manifest.json").write_text(json.dumps(manifest))
    return root, destination


@pytest.mark.parametrize("role,expected", [("source_loss", 2), ("native_restart", 0)])
def test_fault_executor_preserves_expected_failure_and_success(role, expected, tmp_path):
    from tools.benchmark.execute_openvins_health_physical_fault import execute

    root, destination = study(tmp_path, role=role, expected=expected)

    def runner(*args, **kwargs):
        destination.mkdir()
        (destination / "result.json").write_text(
            json.dumps({"status": "capture_failed" if expected else "capture_completed"})
        )
        return SimpleNamespace(returncode=expected)

    assert execute(root, resources_fn=lambda: [], runner=runner) == 0
    completion = json.loads((root / "physical-completion.json").read_text())
    assert completion["command_returncode"] == expected
    assert completion["outcome_matches_expectation"] is True
    assert completion["resources_after"] == []
    assert completion["fusion_eligible"] is False


def test_fault_executor_rejects_tampered_expected_outcome_before_dispatch(tmp_path):
    from tools.benchmark.execute_openvins_health_physical_fault import execute

    root, _ = study(tmp_path, role="source_loss", expected=0)
    with pytest.raises(ValueError, match="fault preflight"):
        execute(root, resources_fn=lambda: [])
    assert not (root / "physical-dispatch.json").exists()


def test_fault_executor_keeps_unexpected_result_and_returns_failure(tmp_path):
    from tools.benchmark.execute_openvins_health_physical_fault import execute

    root, destination = study(tmp_path, role="native_restart", expected=0)

    def runner(*args, **kwargs):
        destination.mkdir()
        (destination / "result.json").write_text(json.dumps({"status": "capture_failed"}))
        return SimpleNamespace(returncode=2)

    assert execute(root, resources_fn=lambda: [], runner=runner) == 2
    completion = json.loads((root / "physical-completion.json").read_text())
    assert completion["outcome_matches_expectation"] is False
    assert completion["command_returncode"] == 2
