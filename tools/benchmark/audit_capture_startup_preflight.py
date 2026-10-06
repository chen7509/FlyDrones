"""Independently audit one production capture startup-preflight result."""

from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal, read_declaration
from tools.benchmark.declared_runtime_snapshot import write_manifest
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS

FORBIDDEN = (
    "process.json",
    "px4.log",
    "px4-ulog-manifest.json",
    "motion-profile.json",
    "motion-force.jsonl",
    "motion-ground-truth.jsonl",
    "physics-substeps.jsonl",
    "native-reference.jsonl",
    "estimator-readiness.jsonl",
    "source-fanout.jsonl",
    "events.jsonl",
)


def _events(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def audit(destination, dispatch, completion, *, expected_head):
    destination = Path(destination).resolve(strict=True)
    dispatch = read_declaration(dispatch)
    completion = read_declaration(completion)
    result = read_declaration(destination / "result.json")
    supervisor = read_declaration(destination / "supervisor.json")
    cleanup = supervisor.get("cleanup", {})
    binding = result.get("runtime_binding", {})
    failures = []

    def require(condition, label):
        if not condition:
            failures.append(label)

    expected_destination = str(destination)
    require(dispatch.get("schema") == "capture-startup-preflight-dispatch-v1", "dispatch schema")
    require(dispatch.get("destination") == expected_destination, "dispatch destination")
    require(dispatch.get("head") == expected_head, "dispatch head")
    require(dispatch.get("resources_before") == [], "resources before")
    require(dispatch.get("physical_run") is False, "dispatch physical")
    require(completion.get("schema") == "capture-startup-preflight-completion-v1", "completion schema")
    require(completion.get("destination") == expected_destination, "completion destination")
    require(completion.get("returncode") == 0, "completion returncode")
    require(completion.get("resources_after") == [], "resources after")
    require(completion.get("physical_run") is False, "completion physical")
    require(result.get("status") == "capture_completed" and result.get("errors") == [], "capture result")
    require(result.get("startup_preflight_only") is True, "preflight only")
    require(result.get("startup_preflight_completed") is True, "preflight completed")
    require(binding.get("pre_recorded") is True, "binding pre")
    require(binding.get("declared_files_stable") is True, "declared files stable")
    require(binding.get("local_file_graph_verified") is True, "local graph")
    require(binding.get("phases") == ["postgraph", "bootstrap"], "startup phases")
    require(binding.get("owned_phases") == {"px4": [], "openvins": []}, "owned phases")
    require(binding.get("runtime_mapping_coverage_verified") is False, "mapping qualification")
    require(binding.get("runtime_closure_qualified") is False and binding.get("errors") == [], "binding closed")
    require(supervisor.get("worker_exit") == 0, "worker exit")
    require(supervisor.get("capture_status") == "capture_completed" and supervisor.get("errors") == [], "supervisor")
    require(cleanup.get("errors") == [], "cleanup errors")
    require(cleanup.get("no_executing_members") is True, "no executing members")
    require(cleanup.get("group_absent") is True, "group absent")
    require(cleanup.get("sigkill_dispatched") is False, "SIGKILL")
    require(cleanup.get("graceful_group_cleanup_verified") is True, "graceful cleanup")
    require(cleanup.get("all_descendant_cleanup_qualified") is False, "descendant scope")
    journal = destination.with_name(destination.name + ".supervisor-events.jsonl")
    environment = destination.with_name(destination.name + ".supervisor-environment.json")
    require(journal.is_file() and environment.is_file(), "supervisor sidecars")
    if journal.is_file():
        require(_typed_equal(_events(journal), cleanup.get("events")), "supervisor events")
    require(all(not (destination / name).exists() for name in FORBIDDEN), "no physical artifacts")
    require(
        all(
            result.get(key) is False
            for key in (
                "physical_execution_qualified",
                "vio_accuracy_qualified",
                "estimator_health_qualified",
                "fusion_eligible",
                "flight_ready",
                "eligible_for_vio_input",
                "eligible_for_px4_fusion",
            )
        )
        and binding.get("runtime_mapping_coverage_verified") is False
        and binding.get("runtime_closure_qualified") is False,
        "downstream claims false",
    )
    return {
        "schema": "capture-startup-preflight-audit-v3",
        "destination": expected_destination,
        "head": expected_head,
        "checks": {
            "committed_head": "dispatch head" not in failures,
            "preflight_only": "preflight only" not in failures and "preflight completed" not in failures,
            "startup_phases_only": "startup phases" not in failures and "owned phases" not in failures,
            "events_match": "supervisor events" not in failures,
            "clean_group": not any(label in failures for label in ("cleanup errors", "no executing members", "group absent", "SIGKILL")),
            "no_physical_artifacts": "no physical artifacts" not in failures,
            "resources_empty": "resources before" not in failures and "resources after" not in failures,
            "downstream_false": "downstream claims false" not in failures,
        },
        "cleanup_scope": "owned original process group only; escaped descendants not tracked",
        "all_descendant_cleanup_qualified": False,
        "failures": failures,
        "startup_preflight_qualified": not failures,
        **{key: False for key in FALSE_CLAIMS},
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--dispatch", required=True, type=Path)
    parser.add_argument("--completion", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.destination, args.dispatch, args.completion, expected_head=args.expected_head)
    if args.output:
        write_manifest(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["startup_preflight_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
