"""Prospective full-load wire-study declarations; validation never grants launch.

The document API is pure. The file adapter is read-only and preparation-only:
existing output paths refuse. Neither function executes a runtime or network I/O.
"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path

from tools.benchmark.capture_contract import _typed_equal, derive_launch_environment, read_declaration
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, verify_unchanged
from tools.benchmark.runtime_resource_binding import estimator_inputs, validate_binding
from tools.benchmark.trajectory_gauge_contract import validate_trajectory_gauge_policy

FILE_ROLES = {"execution", "binding", "wire_config", "gauge_policy", "python", "capture", "auditor"}
DOC_ROLES = ("execution", "binding", "wire_config", "gauge_policy")
PROFILES = dict(
    motion_profile="supported-ready-v1",
    physics_trace_profile="substep-ready-v1",
    reference_fault_profile=None,
    source_fanout_profile="ready-shadow-heartbeat-estimator-v1",
    motion_intent_profile="native-beginning-zupt-v1",
    health_profile="px4-d6f12ad-gate-floor-v1",
)
LIMITS = dict(
    bootstrap_wall_ns=8_000_000_000,
    accepted_samples=500,
    operational_ns=2_000_000_000,
    source_startup_ns=10_000_000_000,
    readiness_sim_ns=8_000_000_000,
    anchor_ahead_ns=200_000_000,
    cleanup_ns=10_000_000_000,
    max_datagrams=4096,
    max_segments=64,
    segment_events=8192,
    journal_bytes=512 * 1024 * 1024,
)
ENDPOINT = dict(
    local_host="127.0.0.1",
    local_port=14548,
    peer_host="127.0.0.1",
    peer_port=14588,
    sender_system=254,
    sender_component=191,
    target_system=9,
    target_component=1,
    instance=8,
)
WORKLOAD = dict(
    schema="capture-execution-v3",
    wall_budget_s=300,
    supervisor_s=300,
    simulation_duration_ns=25_000_000_000,
    physics_step_ns=1_000_000,
    imu_hz=250,
    rgbd_hz=10,
    rgbd_size=[160, 120],
    estimator_run=True,
    simulation_seed=27601,
)


def _shape(value, keys, label):
    if type(value) is not dict or value.keys() != set(keys):
        raise ValueError("invalid " + label + " schema")


def _equal(value, expected, label):
    if not _typed_equal(value, expected):
        raise ValueError("mismatched " + label)


def _text(value, pattern, label):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise ValueError("invalid " + label)


def _path(value):
    if type(value) is not str or not value or "\0" in value or not Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError("explicit absolute path required")
    return Path(value)


def _identity(value):
    _shape(value, ("device", "inode", "mode", "size", "mtime_ns", "ctime_ns"), "file identity")
    if any(type(v) is not int for v in value.values()) or value["size"] < 0:
        raise ValueError("invalid file identity values")


def _file(value):
    _shape(value, ("requested", "resolved", "links", "identity", "path_identity", "bytes", "sha256"), "file record")
    _path(value["requested"])
    _path(value["resolved"])
    _text(value["sha256"], "[0-9a-f]{64}", "file digest")
    if type(value["bytes"]) is not int or value["bytes"] < 0:
        raise ValueError("invalid file length")
    for key in ("identity", "path_identity"):
        _identity(value[key])
        if value[key]["size"] != value["bytes"]:
            raise ValueError("file size identity mismatch")
    if type(value["links"]) is not list or len(value["links"]) > 40:
        raise ValueError("invalid symlink chain")
    for link in value["links"]:
        _shape(link, ("path", "target", "identity"), "symlink")
        _path(link["path"])
        _identity(link["identity"])
        if type(link["target"]) is not str or not link["target"] or "\0" in link["target"]:
            raise ValueError("invalid symlink target")


def _key(value):
    return os.path.normcase(str(_path(value)))


def _outputs(document, inputs):
    outputs = document["outputs"]
    _shape(outputs, ("capture", "dispatch", "completion", "audit"), "outputs")
    values = [_path(v) for v in outputs.values()]
    for i, path in enumerate(values):
        if any(path == other or path in other.parents or other in path.parents for other in values[i + 1 :]):
            raise ValueError("output paths overlap")
        if any(path == other or path in other.parents for other in map(_path, inputs)):
            raise ValueError("output overlaps an input")


def _baseline(binding):
    rows = binding["baseline"]["files"]
    if type(rows) is not list or not rows:
        raise ValueError("missing baseline records")
    expected = {(role, _key(p)) for role, paths in binding["inventory"].items() for p in paths}
    found, by_path = set(), {}
    for row in rows:
        if type(row) is not dict or type(row.get("role")) is not str:
            raise ValueError("invalid baseline role")
        record = {k: v for k, v in row.items() if k != "role"}
        _file(record)
        key = _key(record["requested"])
        if key in by_path:
            raise ValueError("duplicate baseline path")
        found.add((row["role"], key))
        by_path[key] = record
    if found != expected:
        raise ValueError("baseline inventory coverage differs")
    return by_path


def _expected_command(document, execution):
    files = document["files"]
    command = [files["python"]["requested"], files["capture"]["requested"], "--output", document["outputs"]["capture"]]
    fields = {
        **execution["inputs"],
        **execution["profiles"],
        "simulation_seed": 27601,
        "reference_sha256": execution["reference_sha256"],
        "execution_contract": files["execution"]["resolved"],
        "runtime_binding": files["binding"]["resolved"],
        "trajectory_gauge_policy": files["gauge_policy"]["resolved"],
        "wire_config": files["wire_config"]["resolved"],
    }
    # Same production worker-option order, with paths already explicit; no resolve or filesystem access.
    order = (
        "shadow_binary",
        "shadow_config",
        "reference_module",
        "motion_profile",
        "physics_trace_profile",
        "reference_fault_profile",
        "source_fanout_profile",
        "simulation_seed",
        "motion_intent_profile",
        "health_profile",
        "reference_sha256",
        "execution_contract",
        "runtime_binding",
        "trajectory_gauge_policy",
        "wire_config",
    )
    for key in order:
        if fields[key] is not None:
            command += ["--" + key.replace("_", "-"), str(fields[key])]
    return command


def validate_live_wire_study(document, *, execution, binding, wire_config, gauge_policy):
    """Check documents without touching files; no live authorization or code attestation."""
    _shape(
        document,
        (
            "schema",
            "study_id",
            "producer_commit",
            "role",
            "simulation_seed",
            "expected_status",
            "clock_scope",
            "live_activation_authorized",
            "endpoint",
            "limits",
            "outputs",
            "files",
            "command",
        ),
        "study",
    )
    for key, value in dict(
        schema="live-wire-study-v1",
        role="development",
        simulation_seed=27601,
        expected_status="capture_completed",
        clock_scope="postupdate-simulation-epoch-v1",
        live_activation_authorized=False,
    ).items():
        _equal(document[key], value, key)
    _text(document["study_id"], "[A-Za-z0-9_.:-]{1,120}", "study id")
    _text(document["producer_commit"], "[0-9a-f]{40}", "producer commit")
    _equal(document["limits"], LIMITS, "limits")
    _equal(document["endpoint"], ENDPOINT, "endpoint")
    _shape(document["files"], FILE_ROLES, "study files")
    for record in document["files"].values():
        _file(record)
    for key in ("requested", "resolved"):
        if len({_key(r[key]) for r in document["files"].values()}) != len(FILE_ROLES):
            raise ValueError("duplicate study file identity")
    validate_binding(binding)
    if binding["schema"] != "capture-resource-binding-v3":
        raise ValueError("live study requires v3 binding")
    baseline = _baseline(binding)
    runtime = binding["runtime_maps"]
    if (
        not {"postimports", "postfinalize", "postfirststep"} <= set(runtime["self_phases"])
        or set(runtime["owned_roles"]) != {"px4", "openvins"}
        or any(not {"ready", "prestop"} <= set(phases) for phases in runtime["owned_roles"].values())
    ):
        raise ValueError("full native/PX4 runtime coverage must be declared")
    for role in ("runtime-root:px4", "runtime-root:openvins", "runtime-root:native-reference"):
        if role not in binding["inventory"] or len(binding["inventory"][role]) != 1:
            raise ValueError("explicit runtime root required")
    validate_trajectory_gauge_policy(gauge_policy)
    _equal(
        wire_config,
        dict(schema="capture-wire-v1", session_id=document["study_id"] + ".clock", sim_origin_ns=0, remote_origin_ns=0),
        "wire clock",
    )
    _shape(
        execution,
        set(WORKLOAD) | {"profiles", "inputs", "reference_sha256", "launch_environment", "trajectory_gauge_policy", "wire"},
        "execution",
    )
    for key, value in WORKLOAD.items():
        _equal(execution[key], value, "workload " + key)
    _equal(execution["profiles"], PROFILES, "profiles")
    _equal(execution["launch_environment"], derive_launch_environment(binding), "environment")
    _shape(execution["inputs"], ("shadow_binary", "shadow_config", "reference_module"), "native inputs")
    for value in execution["inputs"].values():
        if _key(value) not in baseline:
            raise ValueError("native input absent from baseline")
    for key, role in (("shadow_binary", "runtime-root:openvins"), ("reference_module", "runtime-root:native-reference")):
        _equal(execution["inputs"][key], binding["inventory"][role][0], "selected native root")
    _equal(execution["reference_sha256"], baseline[_key(execution["inputs"]["reference_module"])]["sha256"], "reference digest")
    for role, key, extra in (
        ("wire_config", "wire", {"configuration": wire_config}),
        ("gauge_policy", "trajectory_gauge_policy", {"schema": "trajectory-gauge-policy-v1"}),
    ):
        record = document["files"][role]
        _equal(
            execution[key],
            dict(path=record["requested"], resolved=record["resolved"], bytes=record["bytes"], sha256=record["sha256"], **extra),
            key,
        )
        _equal(baseline.get(_key(record["requested"])), record, "bound " + role)
    _outputs(document, [r[k] for r in [*document["files"].values(), *baseline.values()] for k in ("requested", "resolved")])
    _equal(document["command"], _expected_command(document, execution), "production command")
    return dict(
        manifest=copy.deepcopy(document),
        document_validated=True,
        files_verified=False,
        producer_commit_verified=False,
        live_qualified=False,
        fusion_qualified=False,
    )


def validate_live_wire_study_files(manifest_path):
    """Preparation-only ordinary drift checks. No atomic/hostile-ABA guarantee."""
    from tools.benchmark.capture_contract import declared_command
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args
    from tools.benchmark.repository_python_sources import audit_source_roots, verify_sources

    path = Path(manifest_path)
    before_manifest = file_record(path)
    document = read_declaration(path)
    _shape(document.get("files") if type(document) is dict else None, FILE_ROLES, "study files")
    docs = {}
    for role, expected in document["files"].items():
        _file(expected)
        _equal(file_record(expected["requested"]), expected, "study file " + role)
        if role in DOC_ROLES:
            docs[role] = read_declaration(expected["requested"])
            _equal(file_record(expected["requested"]), expected, "study file after read " + role)
    result = validate_live_wire_study(document, **docs)
    root = Path(__file__).resolve().parents[2]
    source_freeze = verify_sources(root, audit_source_roots(root), docs['binding']['baseline']['files'])
    result['static_audit_sources_verified'] = True
    result['static_audit_source_count'] = len(source_freeze['files'])
    result['dynamic_source_closure_qualified'] = False
    # Check all declared dependencies, not only the four small JSON documents.
    current = snapshot(docs["binding"]["inventory"])
    verify_unchanged(docs["binding"]["baseline"], current)
    selected = docs["execution"]["inputs"]
    required = estimator_inputs(
        Path(selected["shadow_binary"]), Path(selected["shadow_config"]), Path(selected["reference_module"])
    )
    declared = {_key(row["requested"]) for row in current["files"]}
    if any(_key(str(p)) not in declared for p in required):
        raise ValueError("complete frozen estimator configuration must be declared")
    args = parse_capture_args(document["command"][2:])
    command = declared_command(args, document["command"][0], document["command"][1], docs["execution"]["launch_environment"])
    _equal(document["command"], command, "actual capture declaration")
    # Resolve nonexisting outputs to detect aliases through existing parent links.
    resolved_document = copy.deepcopy(document)
    resolved_document["outputs"] = {k: str(Path(v).resolve()) for k, v in document["outputs"].items()}
    _outputs(
        resolved_document,
        [
            before_manifest["resolved"],
            *(r["resolved"] for r in document["files"].values()),
            *(r["resolved"] for r in current["files"]),
        ],
    )
    for value in document["outputs"].values():
        if os.path.lexists(value):
            raise ValueError("study output already exists")
    verify_unchanged(current, snapshot(docs["binding"]["inventory"]))
    for expected in document["files"].values():
        _equal(file_record(expected["requested"]), expected, "final study file")
    _equal(file_record(path), before_manifest, "manifest changed during validation")
    # Recheck after potentially lengthy dependency reads. This is still only an
    # observation at validation time, not a reservation against later writers.
    for value in document["outputs"].values():
        if os.path.lexists(value):
            raise ValueError("study output already exists")
    result["files_verified"] = True
    return result
