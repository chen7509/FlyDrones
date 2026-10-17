import json

import pytest


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def startup(tmp_path):
    root = tmp_path / "startup"
    root.mkdir()
    write(root / "result.json", {
        "status": "capture_completed", "startup_preflight_only": True,
        "startup_preflight_completed": True, "errors": [],
        "runtime_binding": {"pre_recorded": True, "declared_files_stable": True,
                            "local_file_graph_verified": True,
                            "runtime_mapping_coverage_verified": False},
    })
    write(root / "supervisor.json", {
        "worker_exit": 0, "cleanup": {"graceful_group_cleanup_verified": True},
    })
    audit = tmp_path / "audit.json"
    write(audit, {"failures": [], "startup_preflight_qualified": True})
    return root, audit


def test_accepts_narrow_startup_preflight(tmp_path):
    from tools.benchmark.physical_retry_preflight import validate_startup

    root, audit = startup(tmp_path)
    assert validate_startup(root, audit)[0] == root.resolve()


@pytest.mark.parametrize("failure", ["status", "binding", "audit", "px4"])
def test_rejects_startup_drift_or_downstream_artifact(tmp_path, failure):
    from tools.benchmark.physical_retry_preflight import validate_startup

    root, audit = startup(tmp_path)
    if failure == "audit":
        write(audit, {"failures": ["bad"], "startup_preflight_qualified": False})
    elif failure == "px4":
        (root / "process.json").write_text("{}")
    else:
        result = json.loads((root / "result.json").read_text())
        if failure == "status":
            result["status"] = "capture_failed"
        else:
            result["runtime_binding"]["local_file_graph_verified"] = False
        write(root / "result.json", result)
    with pytest.raises(ValueError, match="not qualified"):
        validate_startup(root, audit)
