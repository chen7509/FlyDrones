"""Independently audit a study-v21 one-shot physical boundary."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal, read_declaration
from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS
from tools.benchmark.heartbeat_commit_order_physical_boundary import build_boundary, current_git_head


def audit_boundary(boundary, *, resources, observed_git_head=None):
    failures = []
    try:
        value = read_declaration(boundary)
        if value.get("schema") != "heartbeat-commit-order-physical-boundary-v1":
            failures.append("schema")
        rebuilt = build_boundary(
            study=value["study"],
            package_audit=value["package_audit"]["requested"],
            startup_audit=value["startup_audit"]["requested"],
            startup_dispatch=value["startup_dispatch"]["requested"],
            startup_completion=value["startup_completion"]["requested"],
            evidence_archive=value["evidence_archive"]["requested"],
            expected_head=value["head"],
            head_file=value["head_file"]["requested"],
            observed_git_head=observed_git_head or current_git_head(Path(__file__).resolve().parents[2]),
            dispatch=value["dispatch"],
            completion=value["completion"],
            output=value["output"],
            resources=resources,
        )
        if not _typed_equal(value, rebuilt):
            failures.append("boundary recomputation")
        if any(value.get(key) is not False for key in FALSE_CLAIMS):
            failures.append("overclaim")
    except Exception as exc:
        failures.append("audit:" + repr(exc))
    return {
        "schema": "heartbeat-commit-order-physical-boundary-audit-v1",
        "failures": failures,
        "boundary_qualified": not failures,
        **{key: False for key in FALSE_CLAIMS},
    }


def main(argv=None):
    import argparse

    from tools.benchmark.capture_disarmed_sensors import active_resources

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit_boundary(args.boundary, resources=active_resources())
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["boundary_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
