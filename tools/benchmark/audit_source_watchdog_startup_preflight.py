"""Audit the non-physical startup preflight for the source-watchdog retry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal, read_declaration
from tools.benchmark.estimator_aware_readiness_preflight import FALSE_CLAIMS

FORBIDDEN_OUTPUTS = {
    "process.log",
    "ulog-manifest.json",
    "events.jsonl",
    "source-fanout.jsonl",
    "native-status.jsonl",
    "motion-profile.jsonl",
    "physics-trace.jsonl",
}


def _path_key(value):
    text = str(value).replace("\\", "/")
    if len(text) > 7 and text.startswith("/mnt/") and text[5].isalpha() and text[6] == "/":
        text = f"{text[5]}:/{text[7:]}"
    return text.casefold()


def _json_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def audit_startup(study, dispatch, completion):
    failures = []

    def require(value, label):
        if not value:
            failures.append(label)

    try:
        study = Path(study).resolve(strict=True)
        destination = study / "startup-preflight-v1"
        result_path = destination / "result.json"
        supervisor_path = destination / "supervisor.json"
        journal_path = study / "startup-preflight-v1.supervisor-events.jsonl"
        result = read_declaration(result_path)
        supervisor = read_declaration(supervisor_path)
        dispatch_value = read_declaration(dispatch)
        completion_value = read_declaration(completion)
        cleanup = supervisor.get("cleanup", {})
        binding = result.get("runtime_binding", {})
        files = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
        require(dispatch_value.get("schema") == "source-watchdog-retry-startup-preflight-dispatch-v1", "dispatch schema")
        require(dispatch_value.get("physical_run") is False, "dispatch physical")
        require(_path_key(dispatch_value.get("destination", "")) == _path_key(destination), "dispatch destination")
        require(completion_value.get("schema") == "source-watchdog-retry-startup-preflight-completion-v1", "completion schema")
        require(completion_value.get("returncode") == 0 and completion_value.get("physical_run") is False, "completion result")
        require(completion_value.get("resources_after") == [], "completion resources")
        require(_path_key(completion_value.get("destination", "")) == _path_key(destination), "completion destination")
        require(result.get("status") == "capture_completed" and result.get("errors") == [], "capture result")
        require(result.get("startup_preflight_only") is True and result.get("startup_preflight_completed") is True, "startup flags")
        require(binding.get("phases") == ["postgraph", "bootstrap"], "runtime phases")
        require(binding.get("owned_phases") == {"px4": [], "openvins": []}, "owned phases")
        require(binding.get("runtime_mapping_coverage_verified") is False, "runtime mapping claim")
        require(binding.get("runtime_closure_qualified") is False, "runtime closure claim")
        require(result.get("eligible_for_vio_input") is False and result.get("eligible_for_px4_fusion") is False, "input/fusion claims")
        require(
            all(
                result.get(key) is False
                for key in FALSE_CLAIMS
                if key not in {"runtime_mapping_coverage_verified", "runtime_closure_qualified"}
            ),
            "result claims",
        )
        require(supervisor.get("status") == "worker_exited" and supervisor.get("worker_exit") == 0, "supervisor exit")
        require(supervisor.get("errors") == [] and supervisor.get("capture_status") == "capture_completed", "supervisor status")
        require(cleanup.get("errors") == [] and cleanup.get("no_executing_members") is True, "cleanup executing")
        require(cleanup.get("group_absent") is True and cleanup.get("sigkill_dispatched") is False, "cleanup group")
        require(cleanup.get("graceful_group_cleanup_verified") is True, "cleanup qualification")
        require(cleanup.get("all_descendant_cleanup_qualified") is False, "cleanup scope")
        require(_typed_equal(cleanup.get("events"), _json_lines(journal_path)), "supervisor journal")
        require(not (files & FORBIDDEN_OUTPUTS), "physical artifacts absent")
    except Exception as exc:
        failures.append("audit:" + repr(exc))
        result_path = Path()
        supervisor_path = Path()
        files = set()
        binding = {}
    return {
        "schema": "source-watchdog-retry-startup-preflight-audit-v1",
        "failures": failures,
        "startup_preflight_qualified": not failures,
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest() if result_path.is_file() else None,
        "supervisor_sha256": hashlib.sha256(supervisor_path.read_bytes()).hexdigest() if supervisor_path.is_file() else None,
        "file_count": len(files),
        "runtime_phases": binding.get("phases"),
        "owned_phases": binding.get("owned_phases"),
        "all_descendant_cleanup_qualified": False,
        **{key: False for key in FALSE_CLAIMS},
    }

