"""Fail-closed configuration for a separate, resumable connectome corpus."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from flydrones.benchmark.provenance import verify_sealed_manifest

STAGE_IDS = ("stability", "looming", "corridor", "forest", "dynamic", "disturbance")
EGO_COMMIT = "23a8d5a191711dd65633df689bd00f55d4dea8f9"
FORMAL_FREEZE = "9d10bb72c1fda4048f0439c9dfb823583d8464a8491349f9e732e9cced87d937"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOP_KEYS = {
    "schema", "formal_freeze_sha256", "development_seeds", "output_root",
    "benchmark_config", "vehicle_model", "teacher", "max_sim_time_s",
    "allowed_terminals", "rollout_seeds", "student_truth_fields", "stages",
}


@dataclass(frozen=True)
class CorpusJob:
    stage_id: str
    split: str
    world_seed: int
    rollout_seed: int
    ordinal: int


@dataclass(frozen=True)
class CorpusStage:
    stage_id: str
    world_family: str
    train_seeds: tuple[int, ...]
    validation_seeds: tuple[int, ...]


@dataclass(frozen=True)
class CorpusConfig:
    stages: tuple[CorpusStage, ...]
    rollout_seeds: tuple[int, ...]
    development_seeds: tuple[int, ...]
    output_root: Path
    benchmark_config: Path
    vehicle_model: Path
    teacher_repository: str
    teacher_commit: str
    teacher_image_id: str
    max_sim_time_s: float
    allowed_terminals: tuple[str, ...]
    formal_manifest_sha256: str
    formal_world_hashes: frozenset[str]
    digest: str

    def jobs(self, split: str | None = None) -> tuple[CorpusJob, ...]:
        if split not in (None, "train", "val"):
            raise ValueError("unknown corpus split")
        jobs: list[CorpusJob] = []
        for stage in self.stages:
            for name, seeds in (("train", stage.train_seeds),
                                ("val", stage.validation_seeds)):
                for world_seed in seeds:
                    for rollout_seed in self.rollout_seeds:
                        jobs.append(CorpusJob(stage.stage_id, name, world_seed,
                                              rollout_seed, len(jobs)))
        return tuple(job for job in jobs if split is None or job.split == split)


def _keys(value: object, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} fields invalid")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


def _seeds(value: object, label: str, *, size: int | None = None) -> tuple[int, ...]:
    if not isinstance(value, list) or not value or (size is not None and len(value) != size):
        raise ValueError(f"{label} seeds invalid")
    if any(type(item) is not int or item <= 0 for item in value) or len(set(value)) != len(value):
        raise ValueError(f"{label} seeds invalid")
    return tuple(value)


def _source(value: object, config_path: Path, label: str) -> Path:
    info = _keys(value, {"path", "sha256"}, label)
    name = info["path"]
    if not isinstance(name, str) or not name:
        raise ValueError(f"{label} path invalid")
    path = (config_path.parent / name).resolve()
    expected = _sha(info["sha256"], label)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"{label} source hash mismatch")
    return path


def load_corpus_config(path: Path, *, formal_manifest: Path) -> CorpusConfig:
    """Bind jobs to source hashes and reject all known formal/development overlap."""
    path, formal_manifest = Path(path).resolve(), Path(formal_manifest).resolve()
    raw = _keys(yaml.safe_load(path.read_text(encoding="utf-8")), _TOP_KEYS, "corpus")
    if raw["schema"] != "flydrones-connectome-corpus-v2":
        raise ValueError("corpus schema invalid")
    if _sha(raw["formal_freeze_sha256"], "formal freeze") != FORMAL_FREEZE:
        raise ValueError("wrong formal freeze")
    formal_bytes = formal_manifest.read_bytes()
    formal = json.loads(formal_bytes)
    formal_digest = verify_sealed_manifest(formal)
    if (formal.get("phase") != "formal_worlds"
            or formal.get("generated_after_freeze_sha256") != FORMAL_FREEZE
            or not isinstance(formal.get("worlds"), list) or not formal["worlds"]):
        raise ValueError("wrong formal seed manifest")
    formal_seeds: set[int] = set()
    formal_hashes: set[str] = set()
    for world in formal["worlds"]:
        if not isinstance(world, dict) or type(world.get("seed")) is not int:
            raise ValueError("formal world seed invalid")
        formal_seeds.add(world["seed"])
        formal_hashes.add(_sha(world.get("world_json_sha256"), "formal world"))
    if len(formal_seeds) != len(formal["worlds"]) or len(formal_hashes) != len(formal["worlds"]):
        raise ValueError("duplicate formal world identity")

    development = _seeds(raw["development_seeds"], "development", size=3)
    if development != (1701, 1702, 1703):
        raise ValueError("development seeds changed")
    rollouts = _seeds(raw["rollout_seeds"], "rollout", size=3)
    if raw["student_truth_fields"] is not False:
        raise ValueError("student truth fields are forbidden")
    stages_raw = raw["stages"]
    if not isinstance(stages_raw, list) or len(stages_raw) != len(STAGE_IDS):
        raise ValueError("six ordered stages required")
    stages: list[CorpusStage] = []
    all_world_seeds = set(development) | formal_seeds
    for expected_id, item in zip(STAGE_IDS, stages_raw, strict=True):
        stage = _keys(item, {"id", "world_family", "train_seeds", "validation_seeds"},
                      "stage")
        if stage["id"] != expected_id or stage["world_family"] != expected_id:
            raise ValueError("stage order or world family invalid")
        train = _seeds(stage["train_seeds"], f"{expected_id} train", size=2)
        val = _seeds(stage["validation_seeds"], f"{expected_id} validation", size=1)
        for seed in (*train, *val):
            if seed in all_world_seeds:
                raise ValueError("formal, development or split world seed overlap")
            all_world_seeds.add(seed)
        stages.append(CorpusStage(expected_id, expected_id, train, val))

    output_name = raw["output_root"]
    if not isinstance(output_name, str) or not output_name:
        raise ValueError("output root invalid")
    output = (path.parent / output_name).resolve()
    formal_root = formal_manifest.parent
    if output.is_relative_to(formal_root) or formal_root.is_relative_to(output):
        raise ValueError("output overlaps formal evidence")
    benchmark = _source(raw["benchmark_config"], path, "benchmark config")
    model = _source(raw["vehicle_model"], path, "vehicle model")
    teacher = _keys(raw["teacher"], {"repository", "commit", "image_id"}, "teacher")
    if (teacher["repository"] != "https://github.com/ZJU-FAST-Lab/ego-planner-swarm.git"
            or teacher["commit"] != EGO_COMMIT
            or not isinstance(teacher["image_id"], str)
            or not teacher["image_id"].startswith("sha256:")
            or _SHA.fullmatch(teacher["image_id"][7:]) is None):
        raise ValueError("teacher identity invalid")
    timeout = raw["max_sim_time_s"]
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or timeout <= 0 or timeout > 3600):
        raise ValueError("simulation time limit invalid")
    terminals = raw["allowed_terminals"]
    if (not isinstance(terminals, list) or not terminals
            or any(not isinstance(item, str) for item in terminals)
            or len(set(terminals)) != len(terminals)
            or not set(terminals) <= {"success", "collision", "out_of_bounds", "timeout"}):
        raise ValueError("terminal status policy invalid")

    digest_bytes = json.dumps({"config": raw, "formal_manifest_sha256": formal_digest},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return CorpusConfig(
        tuple(stages), rollouts, development, output, benchmark, model,
        teacher["repository"], teacher["commit"], teacher["image_id"],
        float(timeout), tuple(terminals), formal_digest, frozenset(formal_hashes),
        hashlib.sha256(digest_bytes).hexdigest(),
    )
