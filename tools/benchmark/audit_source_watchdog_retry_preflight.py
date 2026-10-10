"""Independently audit a source-watchdog-corrected prepare-only package."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.capture_contract import (
    _typed_equal,
    declared_command,
    derive_launch_environment,
    execution_contract,
    read_declaration,
)
from tools.benchmark.declared_runtime_snapshot import snapshot, write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS
from tools.benchmark.runtime_resource_binding import validate_binding
from tools.benchmark.source_watchdog_retry_preflight import (
    COPY_CONTRACTS,
    OUTPUT_NAMES,
    record,
    validate_correction,
    validate_source,
)
from tools.benchmark.supported_heartbeat_gauge_preflight import _study_args

STARTUP_MEMBERS = {
    "startup-preflight-v1",
    "startup-preflight-v1.supervisor-environment.json",
    "startup-preflight-v1.supervisor-events.jsonl",
}


def claims_closed(manifest, authorization):
    return all(manifest.get(key) is False and authorization.get(key) is False for key in FALSE_CLAIMS)


def future_destination_available(root, manifest):
    root = Path(root).resolve()
    destination = root / "capture-v1"
    return manifest.get("future_destination") == str(destination) and not destination.exists()


def audit(root, *, after_startup_preflight=False):
    root = Path(root).resolve(strict=True)
    failures = []

    def require(value, label):
        if not value:
            failures.append(label)

    try:
        expected = set(OUTPUT_NAMES) | (STARTUP_MEMBERS if after_startup_preflight else set())
        require({path.name for path in root.iterdir()} == expected, "output members")
        manifest = read_declaration(root / "study-manifest.json")
        authorization = read_declaration(root / "source-watchdog-startup-cohort-authorization.json")
        binding = read_declaration(root / "runtime-binding-v3.json")
        execution = read_declaration(root / "execution-contract.json")
        source = Path(manifest["source"]).resolve(strict=True)
        source_execution = read_declaration(source / "execution-contract.json")
        require(
            manifest.get("schema") == "source-watchdog-startup-cohort-retry-preflight-v1"
            and manifest.get("prepare_only") is True,
            "manifest schema",
        )
        require(authorization.get("schema") == "source-watchdog-startup-cohort-authorization-v1", "authorization schema")
        require(
            authorization.get("startup_timeout_ns") == 10_000_000_000
            and authorization.get("operational_timeout_ns") == 2_000_000_000
            and authorization.get("timeout_increased") is False
            and authorization.get("old_frame_repeated") is False
            and authorization.get("physical_run") is False,
            "authorization boundary",
        )
        validate_source(
            source,
            authorization["source_audit"]["requested"],
            authorization["completion"]["requested"],
            authorization["boundary_audit"]["requested"],
        )
        validate_correction(
            authorization["source_audit"]["requested"],
            authorization["correction_archive"]["requested"],
            Path(__file__).with_name("openvins_online_shadow.py"),
        )
        require(_typed_equal(manifest.get("source_manifest"), record(source / "study-manifest.json")), "source manifest record")
        for name in COPY_CONTRACTS:
            require((root / name).read_bytes() == (source / name).read_bytes(), "copied contract:" + name)
        require(_typed_equal(binding, validate_binding(binding)), "binding validation")
        require(_typed_equal(binding["baseline"]["files"], snapshot(binding["inventory"])["files"]), "binding baseline")
        environment = derive_launch_environment(binding)
        args = _study_args(
            root / "capture-v1",
            source_execution,
            root / "trajectory-gauge-policy.json",
            root / "runtime-binding-v3.json",
            root / "execution-contract.json",
        )
        expected_execution = execution_contract(args, environment)
        require(_typed_equal(execution, expected_execution), "execution recomputation")
        for key in (
            "wall_budget_s",
            "supervisor_s",
            "simulation_duration_ns",
            "physics_step_ns",
            "imu_hz",
            "rgbd_hz",
            "rgbd_size",
            "estimator_run",
            "profiles",
            "inputs",
            "reference_sha256",
        ):
            require(_typed_equal(execution.get(key), source_execution.get(key)), "execution changed:" + key)
        require(
            _typed_equal(manifest.get("command"), declared_command(args, manifest["command"][0], manifest["command"][1], environment)),
            "command recomputation",
        )
        require(future_destination_available(root, manifest), "future destination")
        require(claims_closed(manifest, authorization), "overclaim")
    except Exception as exc:
        failures.append("audit:" + repr(exc))
    return {
        "schema": "source-watchdog-startup-cohort-retry-audit-v1",
        "failures": failures,
        "prepare_qualified": not failures,
        **{key: False for key in FALSE_CLAIMS},
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--after-startup-preflight", action="store_true")
    args = parser.parse_args(argv)
    result = audit(args.input, after_startup_preflight=args.after_startup_preflight)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["prepare_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
