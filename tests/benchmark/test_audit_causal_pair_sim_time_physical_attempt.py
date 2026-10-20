import json
import shutil
from pathlib import Path

from tools.benchmark.audit_causal_pair_sim_time_physical_attempt import audit

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/study-v16/capture-v1"
DISPATCH = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v8-dispatch.json"
COMPLETION = ROOT / "results/estimator-physical-refusal-diagnosis-dev-1701/physical-run-v8-completion.json"


def test_real_attempt_is_wall_pair_age_refusal_and_fixed_replay_passes():
    result = audit(CAPTURE, DISPATCH, COMPLETION)
    assert result["failure_evidence_qualified"]
    assert result["classification"] == "camera-pair-wall-age-slow-simulation-refusal"
    assert result["pair_wall_age_ns"] == 355_099_344
    assert result["idle_wall_age_ns"] == 294_079_878
    assert result["pair_sim_age_ns"] == 0
    assert result["fixed_replay_camera_released"]
    assert result["simulation_silence_refused"]
    assert result["fruit_fly_policy_failure"] is False


def test_terminal_cause_drift_is_rejected(tmp_path):
    capture = tmp_path / "capture"
    capture.mkdir()
    for name in ("result.json", "supervisor.json", "events.jsonl", "source-fanout.jsonl"):
        shutil.copy2(CAPTURE / name, capture / name)
    value = json.loads((capture / "result.json").read_text())
    value["source_fanout"]["failure"] = "other"
    (capture / "result.json").write_text(json.dumps(value))
    assert not audit(capture, DISPATCH, COMPLETION)["failure_evidence_qualified"]
