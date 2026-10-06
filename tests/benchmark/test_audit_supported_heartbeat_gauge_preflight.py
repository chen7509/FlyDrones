import json
from pathlib import Path

import pytest

from tests.benchmark.test_supported_heartbeat_gauge_preflight import base_package
from tools.benchmark import supported_heartbeat_gauge_preflight as preflight


def prepared(tmp_path):
    output = tmp_path / "preflight"
    preflight.prepare_study(
        output,
        source_study=base_package(tmp_path),
        capture_script=Path("/study/capture_disarmed_sensors.py"),
        python=Path("/usr/bin/python3"),
        resources=[],
    )
    return output


def test_dry_audit_qualifies_only_preflight(tmp_path):
    from tools.benchmark.audit_supported_heartbeat_gauge_preflight import audit

    output = prepared(tmp_path)
    result = audit(output)
    assert result["schema"] == "supported-heartbeat-gauge-preflight-audit-v1"
    assert result["preflight_qualified"] is True
    assert result["physical_run_completed"] is False
    assert result["vio_accuracy_qualified"] is False
    assert result["estimator_health_qualified"] is False
    assert result["fusion_eligible"] is False
    assert result["flight_ready"] is False
    assert result["failures"] == []


@pytest.mark.parametrize("tamper", [
    "policy", "command", "profile", "workload", "inventory", "code_inventory", "baseline",
    "source", "claim", "capture",
])
def test_dry_audit_refuses_tampering_or_existing_capture(tmp_path, tamper):
    from tools.benchmark.audit_supported_heartbeat_gauge_preflight import audit

    output = prepared(tmp_path)
    if tamper == "policy":
        path = output / "trajectory-gauge-policy.json"
        row = json.loads(path.read_text())
        row["screens"]["max_position_error_m"] = 0.5
        path.write_text(json.dumps(row))
    elif tamper == "command":
        path = output / "study-manifest.json"
        row = json.loads(path.read_text())
        row["command"].remove("--trajectory-gauge-policy")
        path.write_text(json.dumps(row))
    elif tamper in {"profile", "workload"}:
        path = output / "execution-contract.json"
        row = json.loads(path.read_text())
        if tamper == "profile":
            row["profiles"]["source_fanout_profile"] = "ready-shadow-v1"
        else:
            row["imu_hz"] = 249
        path.write_text(json.dumps(row))
    elif tamper in {"inventory", "code_inventory", "baseline"}:
        path = output / "runtime-binding-v3.json"
        row = json.loads(path.read_text())
        if tamper == "inventory":
            del row["inventory"]["runtime:trajectory-gauge-policy"]
        elif tamper == "code_inventory":
            del row["inventory"]["runtime:prospective-worker-policy-code"]
        else:
            row["baseline"]["files"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(row))
    elif tamper == "source":
        path = output / "study-manifest.json"
        row = json.loads(path.read_text())
        Path(row["source_records"][0]["path"]).write_text("changed")
    elif tamper == "claim":
        path = output / "study-manifest.json"
        row = json.loads(path.read_text())
        row["fusion_eligible"] = True
        path.write_text(json.dumps(row))
    else:
        (output / "capture-v1").mkdir()
    result = audit(output)
    assert result["preflight_qualified"] is False
    assert result["failures"]
    assert result["physical_run_completed"] is False
    assert result["fusion_eligible"] is False
    assert result["flight_ready"] is False
