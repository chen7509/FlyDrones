"""Independent audit of one completed renderer-first-step probe."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.declared_runtime_snapshot import file_record, write_manifest
from tools.benchmark.owned_runtime_maps import parse_maps
from tools.benchmark.renderer_first_step_probe import (
    baseline_mapping_identities,
    expected_renderer_mappings,
    validate_mapping_delta,
)


def _read(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("audit input is not an object")
    return value


def _require(value, message):
    if not value:
        raise ValueError(message)


def audit_documents(result, supervisor, launch, supervisor_environment):
    _require(result.get("schema") == "renderer-first-step-probe-v1", "probe schema")
    _require(result.get("status") == "probe_completed" and "error" not in result, "probe completion")
    _require(result.get("runtime_closure_qualified") is True, "probe runtime closure")
    for key in ("physical_execution_qualified", "fusion_eligible", "flight_ready"):
        _require(result.get(key) is False, "invalid downstream qualification")
    for key in ("px4_started", "openvins_started", "training_started", "force_applied"):
        _require(result.get(key) is False, "forbidden probe activity")
    mapping = result.get("mapping", {})
    historical = result.get("historical", {})
    _require(
        mapping.get("exact_delta") is True
        and mapping.get("cache_absent") is True
        and mapping.get("runtime_closure_qualified") is True,
        "mapping closure",
    )
    added = mapping.get("added")
    historical_added = mapping.get("historical_additions")
    baseline_added = mapping.get("baseline_additions")
    _require(
        type(added) is list and type(historical_added) is list and type(baseline_added) is list
        and len(added) == len(historical_added) + len(baseline_added)
        and len(historical_added) == len(historical.get("libraries", []))
        and {json.dumps(row, sort_keys=True) for row in added}
        == {json.dumps(row, sort_keys=True) for row in historical_added + baseline_added},
        "mapping partition",
    )
    packages = result.get("packages", {})
    libraries = packages.get("libraries")
    package_rows = packages.get("packages")
    _require(type(libraries) is list and len(libraries) == len(added), "library provenance count")
    _require(type(package_rows) is list and package_rows, "package provenance")
    _require(
        {row.get("mapping", {}).get("path") for row in libraries}
        == {row.get("path") for row in added},
        "library provenance mapping",
    )
    _require(
        all(row.get("status") == "install ok installed" and row.get("version") for row in package_rows),
        "installed package provenance",
    )
    subscriptions = result.get("subscriptions")
    _require(type(subscriptions) is dict and len(subscriptions) == 4 and all(v > 0 for v in subscriptions.values()),
             "sensor subscription evidence")
    _require(type(result.get("step_wall_s")) in (int, float) and 0 < result["step_wall_s"] <= 30,
             "bounded first step")
    _require(supervisor.get("status") == "worker_exited" and supervisor.get("worker_exit") == 0,
             "supervisor worker exit")
    _require(supervisor.get("capture_status") == "probe_completed" and supervisor.get("errors") == [],
             "supervisor capture result")
    cleanup = supervisor.get("cleanup", {})
    _require(
        cleanup.get("graceful_group_cleanup_verified") is True
        and cleanup.get("sigkill_dispatched") is False
        and cleanup.get("no_executing_members") is True
        and cleanup.get("group_absent") is True
        and cleanup.get("errors") == []
        and cleanup.get("all_descendant_cleanup_qualified") is False,
        "owned group cleanup",
    )
    _require(launch.get("schema") == "renderer-first-step-launch-v1", "launch schema")
    _require(launch.get("timeout_s") == 60 and launch.get("runtime_closure_qualified") is False,
             "prospective launch claims")
    _require(
        supervisor_environment.get("ambient_inherited") is False
        and supervisor_environment.get("materialized") == result.get("environment", {}).get("materialized"),
        "declared environment transport",
    )
    return True


def _same_record(record):
    current = file_record(record["requested"])
    return current == record


def audit_probe(root):
    root = Path(root)
    result = _read(root / "result.json")
    supervisor = _read(root / "supervisor.json")
    launch = _read(root.with_name(root.name + ".launch.json"))
    supervisor_environment = _read(root.with_name(root.name + ".supervisor-environment.json"))
    audit_documents(result, supervisor, launch, supervisor_environment)

    for record in (
        result["world"], result["environment_declaration"], result["baseline_declaration"],
        *[row["file"] for row in result["packages"]["libraries"]],
        *[row["copyright"] for row in result["packages"]["packages"]],
    ):
        _require(_same_record(record), "declared file changed after probe")
    historical = expected_renderer_mappings(
        result["historical"]["historical_path"], result["historical"]["historical_sha256"],
        result["historical"]["cache_path"],
    )
    baseline = baseline_mapping_identities(
        result["baseline_declaration"]["requested"], result["baseline_declaration"]["sha256"],
    )
    before = parse_maps((root / "maps-before.txt").read_text(encoding="utf-8"))
    after = parse_maps((root / "maps-after.txt").read_text(encoding="utf-8"))
    recomputed = validate_mapping_delta(
        before, after, historical["libraries"], historical["cache_path"], baseline,
    )
    _require(recomputed == result["mapping"], "mapping audit differs from producer")
    return {
        "schema": "renderer-first-step-audit-v1",
        "failures": [],
        "probe_qualified": True,
        "isolated_renderer_mapping_closure_qualified": True,
        "full_capture_runtime_closure_qualified": False,
        "physical_execution_qualified": False,
        "vio_accuracy_qualified": False,
        "estimator_health_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
        "scope": "one isolated 10 ms first-render step; no PX4, OpenVINS, force, training, or flight",
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit_probe(args.root)
    except BaseException as exc:
        result = {
            "schema": "renderer-first-step-audit-v1", "failures": [repr(exc)],
            "probe_qualified": False, "isolated_renderer_mapping_closure_qualified": False,
            "full_capture_runtime_closure_qualified": False, "physical_execution_qualified": False,
            "vio_accuracy_qualified": False, "estimator_health_qualified": False,
            "fusion_eligible": False, "flight_ready": False,
        }
    write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if not result["failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
