import json

import pytest

from tests.benchmark.test_estimator_aware_readiness_preflight import (
    build,
    fake_source_auditor,
    write_json,
)


def run_audit(output):
    from tools.benchmark.audit_estimator_aware_readiness_preflight import audit

    return audit(output, source_auditor=fake_source_auditor, policy_validator=lambda value: value)


def test_audit_accepts_exact_prepare_only_package(tmp_path):
    output, _, _ = build(tmp_path)
    result = run_audit(output)
    assert result["prepare_qualified"] is True
    assert result["physical_execution_qualified"] is False
    assert result["runtime_closure_qualified"] is False


@pytest.mark.parametrize(
    "failure",
    ["extra", "capture", "manifest", "binding", "contract", "readiness", "source"],
)
def test_audit_rejects_package_or_source_drift(tmp_path, failure):
    output, source, _ = build(tmp_path)
    if failure == "extra":
        (output / "extra").write_text("x")
    elif failure == "capture":
        (output / "capture-v1").mkdir()
    elif failure == "source":
        (source / "lazy-runtime-contract.json").write_text("{}")
    else:
        names = {
            "manifest": "study-manifest.json",
            "binding": "runtime-binding-v3.json",
            "contract": "execution-contract.json",
            "readiness": "estimator-readiness-contract.json",
        }
        path = output / names[failure]
        row = json.loads(path.read_text())
        if failure == "manifest":
            row["fusion_eligible"] = True
        elif failure == "binding":
            row["runtime_maps"] = {}
        elif failure == "contract":
            row["profiles"]["source_fanout_profile"] = "ready-shadow-heartbeat-v1"
        else:
            row["truth_used"] = True
        write_json(path, row)
    result = run_audit(output)
    assert result["prepare_qualified"] is False
    assert result["failures"]
