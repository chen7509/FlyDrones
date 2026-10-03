"""The corpus contract must keep training worlds away from formal evidence."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from flydrones.benchmark.provenance import seal_manifest
from flydrones.connectome_training.corpus_config import load_corpus_config

STAGES = ("stability", "looming", "corridor", "forest", "dynamic", "disturbance")
FORMAL_FREEZE = "9d10bb72c1fda4048f0439c9dfb823583d8464a8491349f9e732e9cced87d937"
FORMAL_SOURCE = (Path(__file__).resolve().parents[2] / "evidence" /
                 "fly-ego-formal-seed-manifest-2026-09-22.json")
EGO_IMAGE = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    formal_dir = tmp_path / "formal"
    formal_dir.mkdir()
    formal = formal_dir / "seed_manifest.json"
    formal.write_bytes(FORMAL_SOURCE.read_bytes())
    benchmark = tmp_path / "benchmark.yaml"
    model = tmp_path / "model.sdf"
    benchmark.write_text("control: {dt_s: 0.05}\n", encoding="utf-8")
    model.write_text("<sdf version='1.9'/>\n", encoding="utf-8")
    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()
    config = {
        "schema": "flydrones-connectome-corpus-v2",
        "formal_freeze_sha256": FORMAL_FREEZE,
        "development_seeds": [1701, 1702, 1703],
        "output_root": "corpus/v2",
        "benchmark_config": {"path": "benchmark.yaml", "sha256": sha(benchmark)},
        "vehicle_model": {"path": "model.sdf", "sha256": sha(model)},
        "teacher": {
            "repository": "https://github.com/ZJU-FAST-Lab/ego-planner-swarm.git",
            "commit": "23a8d5a191711dd65633df689bd00f55d4dea8f9",
            "image_id": EGO_IMAGE,
        },
        "max_sim_time_s": 120,
        "allowed_terminals": ["success", "collision", "out_of_bounds", "timeout"],
        "rollout_seeds": [1, 2, 3],
        "student_truth_fields": False,
        "stages": [
            {"id": stage, "world_family": stage,
             "train_seeds": [1101 + i * 100, 1102 + i * 100],
             "validation_seeds": [9101 + i * 100]}
            for i, stage in enumerate(STAGES)
        ],
    }
    path = tmp_path / "corpus.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path, formal, config


def _load(tmp_path: Path, mutate):
    path, formal, config = _fixture(tmp_path)
    mutate(config, formal)
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return load_corpus_config(path, formal_manifest=formal)


def test_six_stages_generate_54_disjoint_jobs_and_identity(tmp_path):
    path, formal, _ = _fixture(tmp_path)
    corpus = load_corpus_config(path, formal_manifest=formal)
    assert len(corpus.jobs()) == 54
    assert len(corpus.jobs("train")) == 36
    assert len(corpus.jobs("val")) == 18
    assert len([j for j in corpus.jobs() if j.stage_id == "forest" and j.split == "train"]) == 6
    assert {j.world_seed for j in corpus.jobs("train")}.isdisjoint(
        j.world_seed for j in corpus.jobs("val"))
    assert corpus.jobs("train")[0].ordinal == 0
    assert len({(j.stage_id, j.split, j.world_seed, j.rollout_seed) for j in corpus.jobs()}) == 54
    assert len(corpus.digest) == 64


@pytest.mark.parametrize("mutate", [
    lambda c, f: c["stages"][0]["train_seeds"].append(1701),
    lambda c, f: c["stages"][0]["validation_seeds"].append(8001),
    lambda c, f: c["stages"][0]["validation_seeds"].append(c["stages"][0]["train_seeds"][0]),
    lambda c, f: c["stages"][1]["train_seeds"].append(c["stages"][0]["train_seeds"][0]),
    lambda c, f: c.update(rollout_seeds=[]),
    lambda c, f: c.update(output_root="formal/training"),
    lambda c, f: c.update(student_truth_fields=True),
    lambda c, f: c["teacher"].update(image_id=""),
    lambda c, f: c["benchmark_config"].update(sha256="0" * 64),
    lambda c, f: c.update(allowed_terminals=[["success"]]),
    lambda c, f: c.update(max_sim_time_s=float("nan")),
    lambda c, f: c.update(unexpected="value"),
])
def test_rejects_invalid_or_leaking_corpus(tmp_path, mutate):
    with pytest.raises(ValueError):
        _load(tmp_path, mutate)


def test_rejects_tampered_formal_seal(tmp_path):
    path, formal, _ = _fixture(tmp_path)
    data = json.loads(formal.read_text(encoding="utf-8"))
    data["worlds"][0]["seed"] = 123
    formal.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="formal seed manifest"):
        load_corpus_config(path, formal_manifest=formal)


def test_rejects_self_sealed_substitute_formal_manifest(tmp_path):
    path, formal, _ = _fixture(tmp_path)
    original = json.loads(formal.read_text(encoding="utf-8"))
    original.pop("manifest_sha256")
    original["worlds"] = original["worlds"][:1]
    formal.write_text(json.dumps(seal_manifest(original)), encoding="utf-8")
    with pytest.raises(ValueError, match="formal seed manifest"):
        load_corpus_config(path, formal_manifest=formal)


def test_rejects_formal_hash_collision_and_changed_teacher(tmp_path):
    path, formal, config = _fixture(tmp_path)
    changed = copy.deepcopy(config)
    changed["teacher"]["image_id"] = "sha256:" + "c" * 64
    path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="teacher identity"):
        load_corpus_config(path, formal_manifest=formal)
    changed["teacher"]["image_id"] = EGO_IMAGE
    formal_seed = json.loads(formal.read_text(encoding="utf-8"))["worlds"][0]["seed"]
    changed["stages"][0]["train_seeds"][0] = formal_seed
    path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(ValueError):
        load_corpus_config(path, formal_manifest=formal)


def test_rejects_seed_assignments_the_world_builder_cannot_use(tmp_path):
    path, formal, config = _fixture(tmp_path)
    config["rollout_seeds"] = [4, 5, 6]
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="rollout seeds changed"):
        load_corpus_config(path, formal_manifest=formal)
    config["rollout_seeds"] = [1, 2, 3]
    config["stages"][0]["train_seeds"] = [1111, 1112]
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="stage seeds changed"):
        load_corpus_config(path, formal_manifest=formal)
