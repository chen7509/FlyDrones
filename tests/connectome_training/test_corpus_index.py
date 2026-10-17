"""Synthetic v2 index fixtures prove integrity rules, not PX4 capture."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest
import yaml

from flydrones.connectome_training import corpus_index
from flydrones.connectome_training.corpus_config import load_corpus_config
from flydrones.connectome_training.corpus_index import _safe_path, load_corpus_index
from flydrones.connectome_training.corpus_worlds import build_corpus_world
from flydrones.connectome_training.dataset import (
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    write_sequence,
)

REPO = Path(__file__).resolve().parents[2]
FORMAL = REPO / "evidence/fly-ego-formal-seed-manifest-2026-09-22.json"
SOURCE_CONFIG = REPO / "configs/connectome_corpus_v2.yaml"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict) -> None:
    path.write_bytes((json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def _config(tmp_path: Path):
    raw = yaml.safe_load(SOURCE_CONFIG.read_text(encoding="utf-8"))
    raw["output_root"] = str(tmp_path / "corpus")
    for name in ("benchmark_config", "vehicle_model"):
        raw[name]["path"] = str((SOURCE_CONFIG.parent / raw[name]["path"]).resolve())
    path = tmp_path / "corpus.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_corpus_config(path, formal_manifest=FORMAL)


def _sequence(config, job, run_dir: Path, world_hash: str) -> Path:
    frame = SequenceFrame(
        sim_ns=100_000_000 + job.ordinal * 100_000,
        frame_ns=90_000_000 + job.ordinal * 100_000,
        rgb=np.full((2, 3, 3), job.ordinal, np.uint8),
        depth_m=np.ones((2, 3), np.float32),
        position_enu=np.zeros(3, np.float32),
        velocity_enu=np.zeros(3, np.float32),
        yaw=0.0,
        yaw_rate=0.0,
        goal_enu=np.array((1., 0., 0.), np.float32),
        depth_valid=np.ones((2, 3), np.bool_),
    )
    target = TeacherTarget(
        velocity_enu=np.zeros(3, np.float32),
        yaw_rate=0.0,
        horizon_enu=np.array(((1., 0., 0.),), np.float32),
        minimum_clearance_m=1.0,
        terminal=True,
        horizon_valid=np.ones(1, np.bool_),
    )
    provenance = SequenceProvenance(
        split=job.split,
        seed=job.world_seed,
        teacher=f"ego@{config.teacher_commit}",
        world_sha256=world_hash,
        config_sha256=_sha(config.benchmark_config),
        source="px4-ekf2-calibrated-camera-v1",
    )
    return write_sequence(run_dir / "sequence", TrainingSequence(provenance, [frame], [target]))


def _fixture(tmp_path: Path):
    config = _config(tmp_path)
    config.output_root.mkdir()
    records = []
    for job in config.jobs():
        run_dir = config.output_root / f"run-{job.ordinal:02d}"
        run_dir.mkdir()
        world = run_dir / "world.json"
        _json(world, build_corpus_world(job))
        world_hash = _sha(world)
        sequence = _sequence(config, job, run_dir, world_hash)
        sequence_hash = _sha(sequence / "manifest.json")
        files = {}
        for name in ("ulog", "source_journal", "teacher_inspection", "calibration"):
            path = run_dir / f"{name}.txt"
            path.write_text(f"synthetic {name} {job.ordinal}\n", encoding="utf-8")
            files[name] = {"path": path.name, "sha256": _sha(path)}
        run_id = f"{job.ordinal + 1:032x}"
        receipt = run_dir / "receipt.json"
        _json(receipt, {
            "schema": "flydrones-connectome-capture-receipt-v1",
            "run_id": run_id,
            "job": asdict(job),
            "sequence_manifest_sha256": sequence_hash,
            "world_sha256": world_hash,
            "teacher_commit": config.teacher_commit,
            "teacher_image_id": config.teacher_image_id,
            "odometry_source": "px4_ekf2",
            "camera_pose_source": "px4_ekf2_calibrated_camera",
            "files": files,
        })
        records.append({
            "job": asdict(job),
            "run_id": run_id,
            "terminal": "success",
            "sequence_dir": f"{run_dir.name}/sequence",
            "sequence_manifest_sha256": sequence_hash,
            "world_json": f"{run_dir.name}/world.json",
            "world_sha256": world_hash,
            "receipt_path": f"{run_dir.name}/receipt.json",
            "receipt_sha256": _sha(receipt),
        })
    index = {"schema": "flydrones-connectome-corpus-index-v1",
             "corpus_digest": config.digest, "records": records}
    path = tmp_path / "index.json"
    _json(path, index)
    return config, path, index


@pytest.fixture(scope="module")
def corpus_fixture(tmp_path_factory):
    return _fixture(tmp_path_factory.mktemp("corpus-index"))


def test_exact_54_job_index_is_integrity_only(corpus_fixture):
    config, path, _ = corpus_fixture
    audit = load_corpus_index(config, path)
    assert len(audit.jobs) == 54
    assert audit.jobs[0].stage_id == "stability"
    assert audit.jobs[-1].stage_id == "disturbance"
    assert len({row.run_id for row in audit.jobs}) == 54
    assert len(audit.digest) == 64
    assert audit.source_authenticated is False
    assert audit.training_eligible is False
    assert audit.eligible_for_fair_comparison is False


@pytest.mark.parametrize("mutation", [
    lambda index: index["records"].pop(),
    lambda index: index["records"].append(index["records"][0]),
    lambda index: index["records"].reverse(),
    lambda index: index["records"][1].update(run_id=index["records"][0]["run_id"]),
    lambda index: index["records"][1].update(sequence_dir=index["records"][0]["sequence_dir"]),
    lambda index: index["records"][0].update(terminal="collision"),
    lambda index: index["records"][0].update(world_sha256="0" * 64),
    lambda index: index["records"][0].update(sequence_manifest_sha256="0" * 64),
    lambda index: index["records"][0].update(receipt_sha256="0" * 64),
    lambda index: index.update(corpus_digest="0" * 64),
])
def test_invalid_index_refuses(tmp_path, corpus_fixture, mutation):
    config, _, original = corpus_fixture
    index = deepcopy(original)
    mutation(index)
    path = tmp_path / "index.json"
    _json(path, index)
    with pytest.raises(ValueError):
        load_corpus_index(config, path)


def test_path_escape_and_receipt_claim_refuse(tmp_path, corpus_fixture):
    config, _, original = corpus_fixture
    index = deepcopy(original)
    path = tmp_path / "index.json"
    index["records"][0]["world_json"] = "../outside.json"
    _json(path, index)
    with pytest.raises(ValueError, match="path"):
        load_corpus_index(config, path)

    index["records"][0]["world_json"] = "run-00/world.json"
    receipt = config.output_root / "run-00/receipt.json"
    original_receipt = receipt.read_bytes()
    row = json.loads(receipt.read_text(encoding="utf-8"))
    row["teacher_commit"] = "0" * 40
    try:
        _json(receipt, row)
        index["records"][0]["receipt_sha256"] = _sha(receipt)
        _json(path, index)
        with pytest.raises(ValueError, match="receipt"):
            load_corpus_index(config, path)
    finally:
        receipt.write_bytes(original_receipt)


def test_missing_world_path_refuses_with_index_error(tmp_path, corpus_fixture):
    config, _, original = corpus_fixture
    index = deepcopy(original)
    index["records"][0]["world_json"] = "run-00/missing.json"
    path = tmp_path / "index.json"
    _json(path, index)
    with pytest.raises(ValueError, match="path"):
        load_corpus_index(config, path)


def test_missing_relative_file_is_a_bounded_path_refusal(tmp_path):
    with pytest.raises(ValueError, match="path"):
        _safe_path(tmp_path, "missing.json", directory=False)


def test_relabelled_duplicate_sample_payload_refuses(tmp_path, corpus_fixture):
    config, _, original = corpus_fixture
    index = deepcopy(original)
    first = config.output_root / "run-00/sequence/samples.npz"
    second = config.output_root / "run-01/sequence/samples.npz"
    manifest_path = second.parent / "manifest.json"
    receipt_path = second.parent.parent / "receipt.json"
    old_samples = second.read_bytes()
    old_manifest = manifest_path.read_bytes()
    old_receipt = receipt_path.read_bytes()
    try:
        second.write_bytes(first.read_bytes())
        manifest = json.loads(old_manifest)
        manifest["samples_sha256"] = _sha(second)
        _json(manifest_path, manifest)
        index["records"][1]["sequence_manifest_sha256"] = _sha(manifest_path)
        receipt = json.loads(old_receipt)
        receipt["sequence_manifest_sha256"] = _sha(manifest_path)
        _json(receipt_path, receipt)
        index["records"][1]["receipt_sha256"] = _sha(receipt_path)
        path = tmp_path / "index.json"
        _json(path, index)
        with pytest.raises(ValueError, match="samples repeated"):
            load_corpus_index(config, path)
    finally:
        second.write_bytes(old_samples)
        manifest_path.write_bytes(old_manifest)
        receipt_path.write_bytes(old_receipt)


@pytest.mark.parametrize("field,value", [
    ("teacher", "ego@" + "0" * 40),
    ("source", "gazebo-truth"),
])
def test_sequence_provenance_relabel_refuses(tmp_path, corpus_fixture, field, value):
    config, _, original = corpus_fixture
    index = deepcopy(original)
    manifest_path = config.output_root / "run-00/sequence/manifest.json"
    receipt_path = config.output_root / "run-00/receipt.json"
    old_manifest, old_receipt = manifest_path.read_bytes(), receipt_path.read_bytes()
    try:
        manifest = json.loads(old_manifest)
        manifest["provenance"][field] = value
        _json(manifest_path, manifest)
        index["records"][0]["sequence_manifest_sha256"] = _sha(manifest_path)
        receipt = json.loads(old_receipt)
        receipt["sequence_manifest_sha256"] = _sha(manifest_path)
        _json(receipt_path, receipt)
        index["records"][0]["receipt_sha256"] = _sha(receipt_path)
        path = tmp_path / "index.json"
        _json(path, index)
        with pytest.raises(ValueError, match="provenance"):
            load_corpus_index(config, path)
    finally:
        manifest_path.write_bytes(old_manifest)
        receipt_path.write_bytes(old_receipt)


def test_symlink_escape_refuses(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    link = root / "linked.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="symlink"):
        _safe_path(root, "linked.json", directory=False)


def test_manifest_changed_between_hash_and_load_refuses(tmp_path, corpus_fixture, monkeypatch):
    config, _, original = corpus_fixture
    path = tmp_path / "index.json"
    _json(path, original)
    manifest_path = config.output_root / "run-00/sequence/manifest.json"
    old = manifest_path.read_bytes()
    real_load = corpus_index.load_sequence

    def changed_load(sequence_dir):
        if sequence_dir == manifest_path.parent:
            manifest_path.write_bytes(old + b" ")
        return real_load(sequence_dir)

    monkeypatch.setattr(corpus_index, "load_sequence", changed_load)
    try:
        with pytest.raises(ValueError, match="changed|hash"):
            load_corpus_index(config, path)
    finally:
        manifest_path.write_bytes(old)


def test_receipt_changed_between_hash_and_parse_refuses(tmp_path, corpus_fixture, monkeypatch):
    config, _, original = corpus_fixture
    path = tmp_path / "index.json"
    _json(path, original)
    receipt_path = config.output_root / "run-00/receipt.json"
    old = receipt_path.read_bytes()
    real_json = corpus_index._json_file

    def changed_json(selected_path, *, maximum):
        if selected_path == receipt_path:
            receipt_path.write_bytes(old + b" ")
        return real_json(selected_path, maximum=maximum)

    monkeypatch.setattr(corpus_index, "_json_file", changed_json)
    try:
        with pytest.raises(ValueError, match="receipt.*hash|changed"):
            load_corpus_index(config, path)
    finally:
        receipt_path.write_bytes(old)


@pytest.mark.parametrize("source", ["benchmark_config", "vehicle_model"])
def test_loaded_config_refuses_source_byte_drift(tmp_path, corpus_fixture, source):
    config, _, original = corpus_fixture
    copied = tmp_path / f"{source}.copy"
    copied.write_bytes(getattr(config, source).read_bytes() + b" ")
    changed = replace(config, **{source: copied})
    path = tmp_path / "index.json"
    _json(path, original)
    with pytest.raises(ValueError, match="changed"):
        load_corpus_index(changed, path)


def test_receipt_evidence_cannot_reuse_world(tmp_path, corpus_fixture):
    config, _, original = corpus_fixture
    index = deepcopy(original)
    receipt_path = config.output_root / "run-00/receipt.json"
    old_receipt = receipt_path.read_bytes()
    try:
        receipt = json.loads(old_receipt)
        receipt["files"]["ulog"] = {
            "path": "world.json", "sha256": _sha(receipt_path.parent / "world.json"),
        }
        _json(receipt_path, receipt)
        index["records"][0]["receipt_sha256"] = _sha(receipt_path)
        path = tmp_path / "index.json"
        _json(path, index)
        with pytest.raises(ValueError, match="reused"):
            load_corpus_index(config, path)
    finally:
        receipt_path.write_bytes(old_receipt)


@pytest.mark.parametrize("target,field", [
    ("world.json", "ulog"),
    ("ulog.txt", "source_journal"),
])
def test_receipt_evidence_cannot_reuse_hardlinked_file(
        tmp_path, corpus_fixture, target, field):
    config, _, original = corpus_fixture
    index = deepcopy(original)
    receipt_path = config.output_root / "run-00/receipt.json"
    target_path = receipt_path.parent / target
    link_path = receipt_path.parent / f"{field}-hardlink.txt"
    old_receipt = receipt_path.read_bytes()
    try:
        link_path.hardlink_to(target_path)
    except (OSError, NotImplementedError):
        pytest.skip("hardlink creation unavailable")
    try:
        receipt = json.loads(old_receipt)
        receipt["files"][field] = {"path": link_path.name, "sha256": _sha(link_path)}
        _json(receipt_path, receipt)
        index["records"][0]["receipt_sha256"] = _sha(receipt_path)
        path = tmp_path / "index.json"
        _json(path, index)
        with pytest.raises(ValueError, match="reused"):
            load_corpus_index(config, path)
    finally:
        receipt_path.write_bytes(old_receipt)
        link_path.unlink()
