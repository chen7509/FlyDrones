"""Synthetic gate tests do not constitute a live PX4 estimator validation."""

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from flydrones.benchmark.contract import Observation
from flydrones.benchmark.gateway import NativeGazeboPx4Backend
from flydrones.connectome_training.capture_input import (
    CaptureInputEvidence,
    validate_capture_input,
)
from flydrones.connectome_training.teacher_image import inspect_pinned_ego_image

COMMIT = "23a8d5a191711dd65633df689bd00f55d4dea8f9"
IMAGE = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"


def _valid(tmp_path: Path):
    node = "/ego_ws/install/ego_planner/lib/ego_planner/ego_planner_node"
    server = "/ego_ws/install/ego_planner/lib/ego_planner/traj_server"
    outputs = iter([
        IMAGE + "\n", COMMIT + "\n", "",
        "https://github.com/ZJU-FAST-Lab/ego-planner-swarm.git\n",
        "ego_planner ego_planner_node\nego_planner traj_server\n",
        f"{'a' * 64}  {node}\n{'b' * 64}  {server}\n",
    ])

    def read_only_fake(args, **_kwargs):
        return subprocess.CompletedProcess(args, 0, next(outputs), "")

    inspection = tmp_path / "inspection"
    inspect_pinned_ego_image(inspection, run=read_only_fake)
    inspection_path = inspection / "inspection.json"
    backend = SimpleNamespace(odometry_source="px4_ekf2",
                              camera_pose_source="px4_ekf2_calibrated_camera")
    obs = Observation(
        200_000_000, 180_000_000, np.zeros((4, 6, 3), np.uint8),
        np.ones((4, 6), np.float32), (0., 0., 1., 0., 0., 0., 1.),
        (0., 0., 1.), (0., 0., 0.), 0., 0., (5., 0., 1.),
    )
    evidence = CaptureInputEvidence(
        odometry_source="px4_ekf2",
        camera_pose_source="px4_ekf2_calibrated_camera",
        estimator_sim_ns=190_000_000,
        camera_pose_sim_ns=180_000_000,
        xy_valid=True, z_valid=True, heading_valid=True,
        calibration_verified=True, calibration_sha256="a" * 64,
        teacher_commit=COMMIT, teacher_image_id=IMAGE,
        teacher_image_inspected=True,
        teacher_inspection_path=inspection_path,
        teacher_inspection_sha256=hashlib.sha256(inspection_path.read_bytes()).hexdigest(),
    )
    config = SimpleNamespace(teacher_commit=COMMIT, teacher_image_id=IMAGE)
    return backend, obs, evidence, config


def test_well_formed_deployment_visible_evidence_passes_synthetic_gate(tmp_path):
    assert validate_capture_input(*_valid(tmp_path)) is None


def test_boolean_alone_does_not_prove_teacher_inspection(tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    with pytest.raises(ValueError, match="teacher inspection record"):
        validate_capture_input(backend, obs, replace(evidence, teacher_inspection_path=None), config)


def test_tampered_or_relabelled_inspection_is_rejected(tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    path = evidence.teacher_inspection_path
    record = json.loads(path.read_text(encoding="utf8"))
    record["commands"][1]["stdout"] = "0" * 40 + "\n"
    path.write_text(json.dumps(record), encoding="utf8")
    with pytest.raises(ValueError, match="teacher inspection record"):
        validate_capture_input(backend, obs, evidence, config)
    changed = replace(evidence, teacher_inspection_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="teacher inspection record"):
        validate_capture_input(backend, obs, changed, config)


def test_rehashed_unsafe_inspection_transcripts_are_rejected(tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    path = evidence.teacher_inspection_path
    original = json.loads(path.read_text(encoding="utf8"))
    for change in ("network", "name_without_value", "returncode", "failed", "duplicate"):
        record = json.loads(json.dumps(original))
        if change == "network":
            args = record["commands"][1]["argv"]
            args[args.index("--network") + 1] = "host"
        elif change == "name_without_value":
            args = record["commands"][1]["argv"]
            position = args.index("--name")
            del args[position:position + 2]
            args.append("--name")
        elif change == "returncode":
            record["commands"][0]["returncode"] = 0.0
        elif change == "failed":
            record["failure"] = "inspection was interrupted"
        if change == "duplicate":
            raw = json.dumps(record).replace('"inspected": true',
                                             '"inspected": false, "inspected": true', 1).encode()
        else:
            raw = json.dumps(record).encode()
        path.write_bytes(raw)
        changed = replace(evidence, teacher_inspection_sha256=hashlib.sha256(raw).hexdigest())
        with pytest.raises(ValueError, match="teacher inspection record"):
            validate_capture_input(backend, obs, changed, config)


@pytest.mark.parametrize("change", [
    {"odometry_source": "gazebo_model_truth"},
    {"camera_pose_source": "gazebo_model_truth"},
    {"estimator_sim_ns": 50_000_000},
    {"estimator_sim_ns": 210_000_000},
    {"camera_pose_sim_ns": 100_000_000},
    {"camera_pose_sim_ns": 210_000_000},
    {"xy_valid": False},
    {"z_valid": False},
    {"heading_valid": False},
    {"calibration_verified": False},
    {"calibration_sha256": "unknown"},
    {"teacher_image_id": "sha256:" + "b" * 64},
    {"teacher_image_inspected": False},
])
def test_rejects_invalid_capture_evidence(change, tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    with pytest.raises(ValueError):
        validate_capture_input(backend, obs, replace(evidence, **change), config)


def test_rejects_stale_or_invalid_observation(tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    with pytest.raises(ValueError, match="frame"):
        validate_capture_input(backend, replace(obs, frame_ns=0), evidence, config)
    early_obs = replace(obs, sim_ns=20_000_000, frame_ns=-10_000_000)
    early_evidence = replace(evidence, estimator_sim_ns=10_000_000,
                             camera_pose_sim_ns=0)
    with pytest.raises(ValueError, match="frame"):
        validate_capture_input(backend, early_obs, early_evidence, config)
    with pytest.raises(ValueError, match="depth"):
        validate_capture_input(backend, replace(obs, depth_m=np.full((4, 6), np.nan)),
                               evidence, config)
    with pytest.raises(ValueError, match="depth"):
        validate_capture_input(backend, replace(obs, depth_m=np.ones((4, 6), np.uint16)),
                               evidence, config)
    with pytest.raises(ValueError, match="depth"):
        validate_capture_input(backend, replace(obs, rgb=np.zeros((0, 6, 3), np.uint8),
                                                depth_m=np.zeros((0, 6), np.float32)),
                               evidence, config)
    with pytest.raises(ValueError, match="observation"):
        validate_capture_input(backend, replace(obs, goal=(np.nan, 0., 1.)),
                               evidence, config)
    with pytest.raises(ValueError, match="observation"):
        validate_capture_input(backend, replace(obs, position=("1", 0., 1.)),
                               evidence, config)


def test_existing_native_backend_rejects_synthetic_valid_evidence(tmp_path: Path):
    backend = NativeGazeboPx4Backend(tmp_path, tmp_path / "run", {"goal": [5., 0., 1.]})
    _, obs, evidence, config = _valid(tmp_path)
    assert backend.odometry_source == backend.camera_pose_source == "gazebo_model_truth"
    with pytest.raises(ValueError, match="backend source"):
        validate_capture_input(backend, obs, evidence, config)
    matching_truth = replace(evidence, odometry_source="gazebo_model_truth",
                             camera_pose_source="gazebo_model_truth")
    with pytest.raises(ValueError, match="deployment-visible"):
        validate_capture_input(backend, obs, matching_truth, config)
    backend.odometry_source = "px4_ekf2"
    backend.camera_pose_source = "px4_ekf2_calibrated_camera"
    with pytest.raises(ValueError, match="truth backend"):
        validate_capture_input(backend, obs, evidence, config)
