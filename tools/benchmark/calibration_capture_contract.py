"""Select the already frozen raw source scene; no measurement qualification."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

PROFILE = "target-bearing-raw-v1"
SCENE_MANIFEST_SHA = "0a66c427e1d9d7d9de1557d46bfb12a04398e27b467e4acc246240f5d06c6da4"


def file_sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            value.update(block)
    return value.hexdigest()


def scene_record(path):
    root = Path(path).resolve(strict=True)
    manifest = root / "manifest.json"
    if manifest.is_symlink() or file_sha(manifest) != SCENE_MANIFEST_SHA:
        raise ValueError("sealed calibration scene manifest changed")
    records = json.loads(manifest.read_text(encoding="utf8"))["files"]
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(records) | {"manifest.json"}:
        raise ValueError("calibration scene member set changed")
    for name, row in records.items():
        selected = root / name
        if selected.is_symlink() or selected.stat().st_size != row["bytes"] or file_sha(selected) != row["sha256"]:
            raise ValueError("calibration scene member changed: " + name)
    records = dict(records, **{"manifest.json": dict(bytes=manifest.stat().st_size, sha256=SCENE_MANIFEST_SHA)})
    frozen = json.loads((root / "scene-load.json").read_text(encoding="utf8"))
    return dict(
        schema="target-bearing-scene-selection-v1",
        path=str(root),
        manifest_sha256=SCENE_MANIFEST_SHA,
        files=records,
        geometry=frozen["geometry"],
        design=frozen["design"],
        qualification=copy.deepcopy(frozen["qualification"]),
    )


def validate_raw_args(args):
    required = (
        "calibration_scene",
        "execution_contract",
        "runtime_binding",
        "wire_config",
        "agent_runtime_config",
        "logger_diagnostic_profile",
        "record_owned_ulog",
        "simulation_seed",
    )
    if any(not getattr(args, name, None) for name in required):
        raise ValueError("raw capture requires complete scene/owned source/seed declaration")
    forbidden = (
        "shadow_binary",
        "shadow_config",
        "reference_module",
        "reference_sha256",
        "source_fanout_profile",
        "reference_fault_profile",
        "health_profile",
        "health_fault_profile",
        "motion_intent_profile",
        "trajectory_gauge_policy",
    )
    if any(getattr(args, name, None) for name in forbidden):
        raise ValueError("raw capture cannot masquerade as native/reference/flight profile")
    if (
        args.motion_profile != "target-bearing-multiaxis-v1"
        or args.physics_trace_profile != "substep-calibration-v1"
        or args.logger_diagnostic_profile != "source-diagnostic-v1"
    ):
        raise ValueError("raw capture motion/trace/logger graph mismatch")
    return PROFILE


def raw_graph(args):
    validate_raw_args(args)
    result = dict(
        schema="target-bearing-raw-graph-v1",
        name=PROFILE,
        readiness=[
            "journaled-rgb",
            "journaled-camera-info",
            "journaled-imu",
            "disarmed-heartbeat",
            "owned-wire-health",
            "owned-Agent",
            "owned-ULog-witness",
        ],
        estimator_required=False,
        measured_calibration_qualified=False,
        scene=scene_record(args.calibration_scene),
    )
    if getattr(args,'prepared_scene',False):
        result['prepared_input']=validate_prepared_scene(result['scene'],args.output)
    return result


def validate_prepared_scene(source,output):
    if scene_record(source['path']) != source:
        raise ValueError('prepared source selection changed')
    actual=scene_record(output)
    if {k:v for k,v in actual.items() if k!='path'} != {k:v for k,v in source.items() if k!='path'}:
        raise ValueError('prepared input differs from sealed source scene')
    return actual


def prepared_scene_members(source,prepared,output):
    if Path(prepared['path']).resolve()!=Path(output).resolve() or scene_record(source['path'])!=source:
        raise ValueError('prepared capture input path/source changed')
    if {k:v for k,v in prepared.items() if k!='path'} != {k:v for k,v in source.items() if k!='path'}:
        raise ValueError('prepared input declaration changed')
    # The worker has already exclusively written its environment record. The
    # exact directory/member check happened in parent and worker declarations.
    for name,row in prepared['files'].items():
        p=Path(output)/name
        if p.is_symlink() or p.stat().st_size!=row['bytes'] or file_sha(p)!=row['sha256']:
            raise ValueError('prepared capture input bytes changed')
    return {name:row['sha256'] for name,row in prepared['files'].items()}


def copy_scene(record, output):
    actual = scene_record(record["path"])
    if actual != record:
        raise ValueError("calibration scene changed before selection")
    output = Path(output)
    copied = {}
    for name, row in record["files"].items():
        source, dest = Path(record["path"]) / name, output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as read, dest.open("xb") as write:
            for block in iter(lambda: read.read(1024**2), b""):
                if write.write(block) != len(block):
                    raise OSError("short raw scene copy")
        if file_sha(dest) != row["sha256"] or file_sha(source) != row["sha256"]:
            raise ValueError("calibration scene changed during copy")
        copied[name] = row["sha256"]
    return copied
