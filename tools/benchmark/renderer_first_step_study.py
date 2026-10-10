"""Launch exactly one declared renderer-first-step probe under the owned-group supervisor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.benchmark.capture_contract import read_declaration, validate_launch_environment
from tools.benchmark.declared_runtime_snapshot import file_record, write_manifest
from tools.benchmark.disarmed_sensor_provenance import supervise_worker


def build_command(*, output, environment, environment_sha256, world, historical,
                  historical_sha256, cache_path, baseline, baseline_sha256, python):
    paths = {
        "environment": Path(environment).resolve(strict=True),
        "world": Path(world).resolve(strict=True),
        "historical": Path(historical).resolve(strict=True),
        "baseline": Path(baseline).resolve(strict=True),
        "python": Path(python).resolve(strict=True),
    }
    if hashlib.sha256(paths["environment"].read_bytes()).hexdigest() != environment_sha256:
        raise ValueError("probe environment hash mismatch")
    if not paths["python"].is_file() or Path(output).exists():
        raise ValueError("invalid probe executable or reused output")
    return [
        str(paths["python"]), "-m", "tools.benchmark.renderer_first_step_probe",
        "--output", str(Path(output).resolve()),
        "--world", str(paths["world"]),
        "--historical", str(paths["historical"]),
        "--historical-sha256", historical_sha256,
        "--cache-path", cache_path,
        "--environment", str(paths["environment"]),
        "--environment-sha256", environment_sha256,
        "--baseline", str(paths["baseline"]),
        "--baseline-sha256", baseline_sha256,
    ], paths


def run_study(*, output, environment, environment_sha256, world, historical,
              historical_sha256, cache_path, baseline, baseline_sha256,
              python="/usr/bin/python3", supervisor=supervise_worker):
    output = Path(output)
    command, paths = build_command(
        output=output, environment=environment, environment_sha256=environment_sha256,
        world=world, historical=historical, historical_sha256=historical_sha256,
        cache_path=cache_path, python=python,
        baseline=baseline, baseline_sha256=baseline_sha256,
    )
    declaration = read_declaration(paths["environment"])
    if declaration.get("schema") != "renderer-probe-environment-v1":
        raise ValueError("invalid renderer probe environment schema")
    launch_environment = validate_launch_environment(declaration.get("materialized"))
    launch = {
        "schema": "renderer-first-step-launch-v1",
        "command": command,
        "inputs": {name: file_record(path) for name, path in paths.items()},
        "timeout_s": 60,
        "px4_started": False,
        "openvins_started": False,
        "training_started": False,
        "force_applied": False,
        "runtime_closure_qualified": False,
        "physical_execution_qualified": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }
    write_manifest(output.with_name(output.name + ".launch.json"), launch)
    summary = supervisor(
        command, output, timeout_s=60, launch_environment=launch_environment,
        execution_contract=paths["environment"],
    )
    return {"launch": launch, "supervisor": summary}


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--world", required=True, type=Path)
    parser.add_argument("--historical", required=True, type=Path)
    parser.add_argument("--historical-sha256", required=True)
    parser.add_argument("--cache-path", required=True)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--python", default="/usr/bin/python3")
    args = parser.parse_args(argv)
    result = run_study(**vars(args))
    print(json.dumps(result, indent=2))
    return 0 if result["supervisor"].get("capture_status") == "probe_completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
