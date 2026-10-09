"""Synthetic gate tests do not constitute a live PX4 estimator validation."""

import base64
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import flydrones.connectome_training.recorder as recorder_module
from flydrones.benchmark.contract import Command, Decision, Observation
from flydrones.benchmark.gateway import NativeGazeboPx4Backend
from flydrones.benchmark.sensors import encode_observation
from flydrones.connectome_training.capture_input import (
    CaptureInputEvidence,
    validate_capture_input,
)
from flydrones.connectome_training.dataset import SequenceProvenance, load_sequence
from flydrones.connectome_training.recorder import TeacherSequenceRecorder
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


def _ego_decision(obs: Observation) -> Decision:
    return Decision(Command((0.2 + obs.sim_ns / 1e9, 0.0, 0.0), 0.1), 0.01, {
        "controller": "ego",
        "tracking_gain": 1.0,
        "reference": {
            "sim_ns": obs.sim_ns,
            "upstream_stamp_ns": obs.sim_ns + 1,
            "position_ref": [float(obs.sim_ns / 1e9), 0.0, 1.0],
            "velocity_ref": [0.2, 0.0, 0.0],
            "yaw_rate": 0.1,
        },
    })


def _recorder() -> TeacherSequenceRecorder:
    return TeacherSequenceRecorder(SequenceProvenance(
        "train", 1101, "ego@pinned", "a" * 64, "b" * 64, "development-capture",
    ))


def test_well_formed_deployment_visible_evidence_passes_synthetic_gate(tmp_path):
    assert validate_capture_input(*_valid(tmp_path)) is None


def test_partial_missing_depth_keeps_original_observation_and_requires_source_gate(tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    depth = obs.depth_m.copy()
    depth[0, 0] = np.nan
    partial = replace(obs, depth_m=depth)
    assert validate_capture_input(backend, partial, evidence, config) is None
    payload = json.loads(encode_observation(partial))
    encoded = np.frombuffer(base64.b64decode(payload["depth_m"]["data"]), dtype="<f4")
    assert np.isnan(encoded[0])
    assert encoded[1] == 1.0
    with pytest.raises(ValueError, match="estimator"):
        validate_capture_input(backend, partial, replace(evidence, xy_valid=False), config)


@pytest.mark.parametrize("invalid", [np.inf, -np.inf, 0.0, -0.1])
def test_non_nan_invalid_depth_value_is_rejected(tmp_path, invalid):
    backend, obs, evidence, config = _valid(tmp_path)
    depth = obs.depth_m.copy()
    depth[0, 0] = invalid
    with pytest.raises(ValueError, match="depth"):
        validate_capture_input(backend, replace(obs, depth_m=depth), evidence, config)


def test_normalized_depth_requires_float32_and_valid_pixel(tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    for depth in (obs.depth_m.astype(np.float64),
                  np.full(obs.depth_m.shape, np.nan, np.float32)):
        with pytest.raises(ValueError, match="depth"):
            validate_capture_input(backend, replace(obs, depth_m=depth), evidence, config)


def test_checked_ego_recorder_preserves_same_frame_mask_and_received_horizon(tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    first_depth = obs.depth_m.copy()
    first_depth[0, 0] = np.nan
    first_position = np.array(obs.position, np.float32)
    first = replace(obs, depth_m=first_depth, position=first_position)
    second = replace(obs, sim_ns=250_000_000, frame_ns=230_000_000,
                     depth_m=obs.depth_m.copy())
    second_evidence = replace(evidence, estimator_sim_ns=240_000_000,
                              camera_pose_sim_ns=230_000_000)
    recorder = _recorder()
    recorder.append_capture_checked(backend, first, evidence, config, _ego_decision(first),
                                    minimum_clearance_m=0.8, terminal=False)
    recorder.append_capture_checked(backend, second, second_evidence, config,
                                    _ego_decision(second), minimum_clearance_m=0.9,
                                    terminal=True)
    first_depth[0, 1] = np.nan
    first_position[0] = 99.0
    out = recorder.finish_with_reference_horizon(tmp_path / "v3", points=3)
    loaded = load_sequence(out)
    assert json.loads((out / "manifest.json").read_text())["schema"] == (
        "flydrones-connectome-sequence-v3"
    )
    assert np.isnan(loaded.frames[0].depth_m[0, 0])
    assert loaded.frames[0].depth_valid[0, 0] == np.bool_(False)
    assert loaded.frames[0].depth_valid[0, 1] == np.bool_(True)
    assert loaded.frames[0].position_enu[0] == 0.0
    assert loaded.frames[1].depth_valid.all()
    assert loaded.targets[0].horizon_valid.tolist() == [True, True, False]
    assert loaded.targets[1].horizon_valid.tolist() == [True, False, False]
    assert loaded.targets[0].horizon_enu[:2, 0].tolist() == pytest.approx([0.2, 0.25])


@pytest.mark.parametrize("failure", ["truth", "old_reference", "wrong_controller",
                                    "no_reference", "invalid_depth", "wrong_command",
                                    "missing_gain", "bad_clearance",
                                    "non_numeric_command"])
def test_checked_ego_recorder_rejects_before_any_mutation(tmp_path, failure):
    backend, obs, evidence, config = _valid(tmp_path)
    decision = _ego_decision(obs)
    if failure == "truth":
        backend.odometry_source = "gazebo_model_truth"
    elif failure == "old_reference":
        decision.evidence["reference"]["sim_ns"] -= 1
    elif failure == "wrong_controller":
        decision.evidence["controller"] = "not-ego"
    elif failure == "no_reference":
        del decision.evidence["reference"]
    elif failure == "invalid_depth":
        obs = replace(obs, depth_m=np.full(obs.depth_m.shape, np.nan, np.float32))
    elif failure == "wrong_command":
        decision = replace(decision, command=Command((0.2, 0.0, 0.0), 0.1))
    elif failure == "non_numeric_command":
        decision = replace(decision, command=Command(("0.4", 0.0, 0.0), 0.1))
    elif failure == "missing_gain":
        del decision.evidence["tracking_gain"]
    recorder = _recorder()
    with pytest.raises(ValueError):
        recorder.append_capture_checked(backend, obs, evidence, config, decision,
                                        minimum_clearance_m=(np.nan if failure == "bad_clearance"
                                                             else 0.8), terminal=False)
    assert not recorder.frames and not recorder.targets and not recorder.references


@pytest.mark.parametrize("field", ["depth_list", "large_goal", "large_clearance",
                                     "large_yaw"])
def test_checked_recorder_rejects_invalid_original_or_float32_overflow(tmp_path, field):
    backend, obs, evidence, config = _valid(tmp_path)
    clearance = 0.8
    if field == "depth_list":
        obs = replace(obs, depth_m=[[np.float32(1.0)] * 6 for _ in range(4)])
        with pytest.raises(ValueError, match="depth"):
            validate_capture_input(backend, obs, evidence, config)
    elif field == "large_goal":
        obs = replace(obs, goal=(1e40, 0.0, 1.0))
    elif field == "large_clearance":
        clearance = 1e40
    else:
        obs = replace(obs, yaw=1e40)
    recorder = _recorder()
    with pytest.raises(ValueError):
        recorder.append_capture_checked(
            backend, obs, evidence, config, _ego_decision(obs),
            minimum_clearance_m=clearance, terminal=False,
        )
    assert not recorder.frames and not recorder.targets and not recorder.references


def test_checked_recorder_validates_the_owned_snapshot_before_append(tmp_path, monkeypatch):
    backend, obs, evidence, config = _valid(tmp_path)
    original_gate = recorder_module.validate_capture_input

    def reuse_camera_buffer(*args):
        original_gate(*args)
        obs.depth_m[0, 0] = np.inf

    monkeypatch.setattr(recorder_module, "validate_capture_input", reuse_camera_buffer)
    recorder = _recorder()
    recorder.append_capture_checked(
        backend, obs, evidence, config, _ego_decision(obs),
        minimum_clearance_m=0.8, terminal=False,
    )
    out = recorder.finish_with_reference_horizon(tmp_path / "owned", points=1)
    stored = load_sequence(out)
    assert np.isinf(obs.depth_m[0, 0])
    assert stored.frames[0].depth_m[0, 0] == 1.0
    assert stored.frames[0].depth_valid[0, 0]


def test_checked_and_legacy_recording_modes_cannot_mix_or_finish_unmasked(tmp_path):
    backend, obs, evidence, config = _valid(tmp_path)
    decision = _ego_decision(obs)
    legacy = _recorder()
    legacy.append(obs, decision, horizon_enu=np.array([[0.2, 0.0, 1.0]], np.float32),
                  minimum_clearance_m=0.8, terminal=False)
    with pytest.raises(ValueError, match="mixed"):
        legacy.append_capture_checked(backend, replace(obs, sim_ns=250_000_000,
                                      frame_ns=230_000_000),
                                      replace(evidence, estimator_sim_ns=240_000_000,
                                              camera_pose_sim_ns=230_000_000),
                                      config, _ego_decision(replace(obs, sim_ns=250_000_000)),
                                      minimum_clearance_m=0.8, terminal=False)
    assert len(legacy.frames) == len(legacy.targets) == len(legacy.references) == 1
    checked = _recorder()
    checked.append_capture_checked(backend, obs, evidence, config, decision,
                                   minimum_clearance_m=0.8, terminal=False)
    second_obs = replace(obs, sim_ns=250_000_000, frame_ns=230_000_000)
    second_evidence = replace(evidence, estimator_sim_ns=240_000_000,
                              camera_pose_sim_ns=230_000_000)
    wrong_command = replace(_ego_decision(second_obs),
                            command=Command((0.0, 0.0, 0.0), 0.1))
    with pytest.raises(ValueError, match="command"):
        checked.append_capture_checked(backend, second_obs, second_evidence, config,
                                       wrong_command, minimum_clearance_m=0.8,
                                       terminal=False)
    assert len(checked.frames) == len(checked.targets) == len(checked.references) == 1
    with pytest.raises(ValueError, match="mixed"):
        checked.append(replace(obs, sim_ns=250_000_000), decision,
                       horizon_enu=np.array([[0.2, 0.0, 1.0]], np.float32),
                       minimum_clearance_m=0.8, terminal=True)
    with pytest.raises(ValueError, match="horizon_valid"):
        checked.finish(tmp_path / "forbidden")
    assert not (tmp_path / "forbidden").exists()


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
