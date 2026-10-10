import copy

import pytest

from tools.benchmark.audit_renderer_first_step_probe import audit_documents


def documents():
    added = [{"path": "/tmp/new.so", "device": "08:30", "inode": 1}]
    result = {
        "schema": "renderer-first-step-probe-v1", "status": "probe_completed",
        "runtime_closure_qualified": True, "physical_execution_qualified": False,
        "fusion_eligible": False, "flight_ready": False, "px4_started": False,
        "openvins_started": False, "training_started": False, "force_applied": False,
        "historical": {"libraries": added},
        "mapping": {"added": added, "historical_additions": added, "baseline_additions": [],
                    "exact_delta": True, "cache_absent": True, "runtime_closure_qualified": True},
        "packages": {"libraries": [{"mapping": added[0], "file": {}, "package": "pkg"}],
                     "packages": [{"package": "pkg", "version": "1", "status": "install ok installed"}]},
        "subscriptions": {"rgb": 1, "depth": 1, "info": 1, "imu": 1}, "step_wall_s": 1.0,
        "environment": {"materialized": {"MESA_SHADER_CACHE_DISABLE": "true"}},
    }
    supervisor = {
        "status": "worker_exited", "worker_exit": 0, "capture_status": "probe_completed", "errors": [],
        "cleanup": {"graceful_group_cleanup_verified": True, "sigkill_dispatched": False,
                    "no_executing_members": True, "group_absent": True, "errors": [],
                    "all_descendant_cleanup_qualified": False},
    }
    launch = {"schema": "renderer-first-step-launch-v1", "timeout_s": 60,
              "runtime_closure_qualified": False}
    environment = {"ambient_inherited": False, "materialized": result["environment"]["materialized"]}
    return result, supervisor, launch, environment


def test_audit_documents_accepts_narrow_completed_probe():
    assert audit_documents(*documents()) is True


@pytest.mark.parametrize(
    "target,key,value",
    [
        (0, "status", "probe_failed"), (0, "physical_execution_qualified", True),
        (0, "px4_started", True), (1, "worker_exit", 2),
        (2, "timeout_s", 61), (3, "ambient_inherited", True),
    ],
)
def test_audit_documents_refuses_false_or_broadened_claims(target, key, value):
    docs = list(documents())
    docs[target] = copy.deepcopy(docs[target])
    docs[target][key] = value
    with pytest.raises(ValueError):
        audit_documents(*docs)
