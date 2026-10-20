import json
from types import SimpleNamespace

import pytest

from tools.benchmark.execute_openvins_health_physical_run import execute


def study(tmp_path, *, role="development"):
    root = tmp_path / "study"
    root.mkdir()
    destination = root / "capture-v1"
    manifest = {
        "schema": "openvins-health-physical-run-preflight-v1",
        "prepare_only": True,
        "run_id": "development-seed-27101" if role == "development" else "held-out-seed-27111",
        "role": role,
        "seed": 27101 if role == "development" else 27111,
        "future_destination": str(destination),
        "command": ["python3", "capture.py", "--output", str(destination)],
        "held_out_results_viewed": False,
        "test_set_tuning_allowed": False,
        "fusion_eligible": False,
    }
    (root / "study-manifest.json").write_text(json.dumps(manifest))
    return root


def test_development_run_records_single_exact_dispatch_and_completion(tmp_path):
    root = study(tmp_path)

    def runner(command, **kwargs):
        assert command[-1] == str(root / "capture-v1")
        (root / "capture-v1").mkdir()
        return SimpleNamespace(returncode=0)

    assert execute(root, resources_fn=lambda: [], runner=runner) == 0
    dispatch = json.loads((root / "physical-dispatch.json").read_text())
    completion = json.loads((root / "physical-completion.json").read_text())
    assert dispatch["single_actual_attempt"] is True
    assert dispatch["role"] == "development"
    assert completion["command_returncode"] == 0
    assert completion["resources_after"] == []


def test_held_out_run_refuses_without_completed_development_gate(tmp_path):
    root = study(tmp_path, role="held_out")
    with pytest.raises(ValueError, match="development gate"):
        execute(root, resources_fn=lambda: [], runner=lambda *a, **k: None)
    assert not (root / "physical-dispatch.json").exists()
