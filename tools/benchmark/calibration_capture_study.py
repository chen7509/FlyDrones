"""File-bound raw study; frozen preparation is not sensor/clock/calibration authority."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.benchmark.capture_contract import (
    _typed_equal,
    derive_launch_environment,
    execution_contract,
    read_declaration,
    worker_options,
)
from tools.benchmark.declared_runtime_snapshot import file_record, snapshot, write_manifest

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "results/target-bearing-runtime-freeze-dev-1701/frozen-study-v1"
SOURCE = ROOT / "results/target-bearing-scene-production-dev-1701/actual-scene-v3"
QUALIFICATION = {
    k: False for k in ("source", "clock", "measured_calibration", "accuracy", "teacher", "fusion", "training", "flight")
}
ROLES = {"binding", "execution", "wire", "agent", "preparation", "collector", "scope", "dispatcher", "study_code", "python"}


def verify_files(records):
    actual = {role: file_record(record["requested"]) for role, record in records.items()}
    if not _typed_equal(actual, records):
        raise ValueError("frozen study input changed")
    return actual


def require_command_baseline(paths, rows):
    known = {identity for row in rows for identity in (row["requested"], row["resolved"])}
    if any(str(path.resolve()) not in known for path in paths):
        raise ValueError("actual raw command absent from declared input bill")


def arguments(folder):
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    folder = Path(folder)
    return parse_capture_args(
        [
            "--output",
            str(folder / "capture-input-v1"),
            "--capture-profile",
            "target-bearing-raw-v1",
            "--calibration-scene",
            str(SOURCE),
            "--prepared-scene",
            "--execution-contract",
            str(folder / "execution-contract.json"),
            "--runtime-binding",
            str(folder / "runtime-binding-v4.json"),
            "--wire-config",
            str(folder / "wire-config.json"),
            "--agent-runtime-config",
            str(folder / "agent-runtime.json"),
            "--logger-diagnostic-profile",
            "source-diagnostic-v1",
            "--record-owned-ulog",
            "--record-depth-payload",
            "--simulation-seed",
            "1701",
            "--motion-profile",
            "target-bearing-multiaxis-v1",
            "--physics-trace-profile",
            "substep-calibration-v1",
        ]
    )


def audit_preparation(binding, preparation):
    return audit_preparation_at(binding, preparation, FOLDER)


def audit_preparation_at(binding, preparation, folder):
    from tools.benchmark.audit_live_wire_resources import audit_resource_graph_records

    expected = {
        "schema",
        "binding_sha256",
        "execution_sha256",
        "pre",
        "after_queries",
        "graph",
        "context",
        "queries",
        "documents_hex",
        "audit",
    }
    if type(preparation) is not dict or set(preparation) != expected or preparation["schema"] != "raw-static-sdk-preparation-v1":
        raise ValueError("actual raw static SDK preparation records required")
    documents = {path: bytes.fromhex(data) for path, data in preparation["documents_hex"].items()}
    audited = audit_resource_graph_records(
        declaration=binding,
        pre=preparation["pre"],
        after_queries=preparation["after_queries"],
        graph=preparation["graph"],
        context=preparation["context"],
        queries=preparation["queries"],
        documents=documents,
    )
    if not _typed_equal(audited, preparation["audit"]) or audited["raw_graph_records_consistent"] is not True:
        raise ValueError("actual preparation graph audit differs")
    # A graph-root record and every declared/generated input must join to this
    # study, not merely to a different historical successful SDK query.
    baseline = {row["requested"]: row for row in binding["baseline"]["files"]}
    pre = {row["requested"]: row for row in preparation["pre"]["files"]}
    for path, row in baseline.items():
        if not _typed_equal(row, pre.get(path)):
            raise ValueError("preparation does not cover current binding baseline")
    expected_generated = {
        str(Path(folder) / "capture-input-v1" / name): sha for name, sha in binding["generated"].items() if name != "gz_env.sh"
    }
    for path, sha in expected_generated.items():
        if (
            pre.get(path, {}).get("sha256") != sha
            or pre[path]["role"] != "generated:" + Path(path).relative_to(Path(folder) / "capture-input-v1").as_posix()
        ):
            raise ValueError("preparation generated scene differs")
    rows = preparation["pre"]["files"]
    if len(pre) != len(rows) or set(pre) != set(baseline) | set(expected_generated):
        raise ValueError("preparation input bill has extra or duplicate selected members")
    return audited


def verify_execution_join(args, execution, binding, require_absent):
    from tools.benchmark.calibration_capture_contract import prepared_scene_members, validate_prepared_scene

    selected = execution.get("raw_measurement", {})
    if require_absent:
        observed = validate_prepared_scene(selected["scene"], args.output)
        if not _typed_equal(observed, selected["prepared_input"]):
            raise ValueError("prepared handoff differs from actual selected scene")
    else:
        prepared_scene_members(selected["scene"], selected["prepared_input"], args.output)
    # After capture starts its output legitimately has journals. Reconstruct
    # the same command and source graph while separately checking all45 inputs.
    args.prepared_scene = False
    expected = execution_contract(args, derive_launch_environment(binding))
    expected["raw_measurement"]["prepared_input"] = selected["prepared_input"]
    args.prepared_scene = True
    if not _typed_equal(expected, execution):
        raise ValueError("raw study execution differs from current producer")


def _verify_profile_study(path, sha, folder, schema, fixed, *, require_absent=True, v2=False, v3=False):
    from tools.benchmark.runtime_resource_binding import validate_binding

    path = Path(path).resolve(strict=True)
    if path != folder / "study.json" or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError("fixed raw study path/digest mismatch")
    doc = read_declaration(path)
    if (
        type(doc) is not dict
        or set(doc) != {"schema", "files", "qualification"}
        or doc["schema"] != schema
        or set(doc["files"]) != set(fixed)
        or not _typed_equal(doc["qualification"], QUALIFICATION)
    ):
        raise ValueError("raw study shape/qualification mismatch")
    actual = verify_files(doc["files"])
    if any(Path(actual[role]["requested"]) != p.absolute() for role, p in fixed.items()):
        raise ValueError("raw study selected command/input path changed")
    binding = validate_binding(read_declaration(fixed["binding"]))
    if binding["schema"] != "capture-resource-binding-v4":
        raise ValueError("raw v4 binding required")
    current = snapshot(binding["inventory"])
    if not _typed_equal(current["files"], binding["baseline"]["files"]):
        raise ValueError("raw study runtime baseline changed")
    execution = read_declaration(fixed["execution"])
    args = arguments(folder)
    verify_execution_join(args, execution, binding, require_absent)
    if (
        execution["wall_budget_s"],
        execution["supervisor_s"],
        execution["simulation_duration_ns"],
        execution["physics_step_ns"],
        execution["imu_hz"],
        execution["rgbd_hz"],
        execution["rgbd_size"],
        execution["estimator_run"],
    ) != (300, 300, 25_000_000_000, 1_000_000, 250, 10, [160, 120], False):
        raise ValueError("raw full workload changed")
    if execution["launch_environment"].get("GZ_SIM_RESOURCE_PATH") != str(args.output / "models"):
        raise ValueError("raw model lookup changed")
    preparation = read_declaration(fixed["preparation"])
    if (
        preparation.get("binding_sha256") != actual["binding"]["sha256"]
        or preparation.get("execution_sha256") != actual["execution"]["sha256"]
    ):
        raise ValueError("preparation does not bind exact execution/binding")
    if v2 and v3:
        raise ValueError('conflicting fixed study profiles')
    if v3:
        from tools.benchmark.calibration_capture_study_v3 import audit_v3_preparation

        audit = audit_v3_preparation(binding, preparation, fixed['entry_bill'], read_declaration(fixed['entry_bill']))
    elif v2:
        from tools.benchmark.calibration_capture_study_v2 import audit_v2_preparation

        audit = audit_v2_preparation(binding, preparation, fixed["entry_bill"], read_declaration(fixed["entry_bill"]))
    else:
        audit = audit_preparation_at(binding, preparation, folder)
    require_command_baseline(
        [
            fixed[role]
            for role in (
                "collector",
                "scope",
                "dispatcher",
                "study_code",
                "python",
                *(("dependency_code", "producer_code") if v2 or v3 else ()),
            )
        ],
        binding["baseline"]["files"],
    )
    return dict(
        study_sha256=sha,
        files=actual,
        baseline_files=current["files"],
        graph_audit=audit,
        command=[str(fixed["python"]), str(fixed["collector"]), "--output", str(args.output), *worker_options(args)],
        cwd=str(ROOT),
        qualification=QUALIFICATION,
    )


def study_paths(folder):
    return {
        "collector": ROOT / "tools/benchmark/capture_disarmed_sensors.py",
        "scope": ROOT / "tools/benchmark/calibration_capture_scope.py",
        "dispatcher": ROOT / "tools/benchmark/run_calibration_capture.py",
        "study_code": Path(__file__),
        "python": Path("/usr/bin/python3"),
        "binding": folder / "runtime-binding-v4.json",
        "execution": folder / "execution-contract.json",
        "wire": folder / "wire-config.json",
        "agent": folder / "agent-runtime.json",
        "preparation": folder / "preparation.json",
    }


def verify_study(path, sha, *, require_absent=True):
    # Explicit fixed registry; v1 keeps every original contract/absence gate.
    from tools.benchmark import calibration_capture_study_v2 as second
    from tools.benchmark import calibration_capture_study_v3 as third

    requested = Path(path).absolute()
    if requested == third.FOLDER / "study.json":
        return third.verify_study_v3(requested, sha, require_absent=require_absent)
    if requested == second.FOLDER / "study.json":
        return second.verify_study_v2(requested, sha, require_absent=require_absent)
    if requested != FOLDER / "study.json":
        raise ValueError("fixed raw study path mismatch")
    return _verify_profile_study(
        requested, sha, FOLDER, "target-bearing-frozen-raw-study-v1", study_paths(FOLDER), require_absent=require_absent
    )


def publish_study(folder):
    folder = Path(folder)
    if folder.resolve() != FOLDER:
        raise ValueError("single frozen study path required")
    paths = {
        "binding": folder / "runtime-binding-v4.json",
        "execution": folder / "execution-contract.json",
        "wire": folder / "wire-config.json",
        "agent": folder / "agent-runtime.json",
        "preparation": folder / "preparation.json",
        "collector": ROOT / "tools/benchmark/capture_disarmed_sensors.py",
        "scope": ROOT / "tools/benchmark/calibration_capture_scope.py",
        "dispatcher": ROOT / "tools/benchmark/run_calibration_capture.py",
        "study_code": Path(__file__),
        "python": Path("/usr/bin/python3"),
    }
    document = dict(
        schema="target-bearing-frozen-raw-study-v1",
        files={role: file_record(path) for role, path in paths.items()},
        qualification=QUALIFICATION,
    )
    target = folder / "study.json"
    write_manifest(target, document)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    checked = verify_study(target, sha)
    write_manifest(folder / "freeze-verification.json", checked)
    return dict(
        study=str(target), sha256=sha, declared_runtime_graph_frozen=True, physical_admitted=False, qualification=QUALIFICATION
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(verify_study(args.study, args.sha256)))


if __name__ == "__main__":
    main()
