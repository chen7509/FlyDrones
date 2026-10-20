"""Integrity-only consumption of the declared 54-job connectome corpus.

This cannot authenticate the PX4, camera or EGO producer and does not make a
sequence eligible for full-model training. A separate source audit is required.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .corpus_config import CorpusConfig, CorpusJob
from .corpus_worlds import build_corpus_world
from .dataset import SCHEMA_V3, load_sequence

_INDEX_SCHEMA = "flydrones-connectome-corpus-index-v1"
_RECEIPT_SCHEMA = "flydrones-connectome-capture-receipt-v1"
_SOURCE = "px4-ekf2-calibrated-camera-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[0-9a-f]{32}\Z")
_RECORD_KEYS = {
    "job", "run_id", "terminal", "sequence_dir", "sequence_manifest_sha256",
    "world_json", "world_sha256", "receipt_path", "receipt_sha256",
}
_RECEIPT_KEYS = {
    "schema", "run_id", "job", "sequence_manifest_sha256", "world_sha256",
    "teacher_commit", "teacher_image_id", "odometry_source",
    "camera_pose_source", "files",
}
_FILE_KEYS = {"ulog", "source_journal", "teacher_inspection", "calibration"}


@dataclass(frozen=True)
class CorpusIndexJob:
    stage_id: str
    split: str
    world_seed: int
    rollout_seed: int
    ordinal: int
    run_id: str
    sequence_dir: Path
    sequence_manifest_sha256: str
    sequence_samples_sha256: str
    world_sha256: str
    receipt_sha256: str


@dataclass(frozen=True)
class CorpusIndexAudit:
    jobs: tuple[CorpusIndexJob, ...]
    digest: str
    source_authenticated: bool = False
    training_eligible: bool = False
    eligible_for_fair_comparison: bool = False


def _mapping(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} fields invalid")
    return value


def _sha(value: object, label: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"{label} SHA-256 invalid")
    return value


def _pairs(rows: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for name, value in rows:
        if name in result:
            raise ValueError("duplicate JSON key")
        result[name] = value
    return result


def _json_file(path: Path, *, maximum: int) -> tuple[dict, bytes]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError(f"JSON file invalid: {path}")
    before = path.stat()
    payload = path.read_bytes()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ) or len(payload) != after.st_size:
        raise ValueError(f"JSON file changed during read: {path}")
    try:
        value = json.loads(payload, object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON file invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root invalid: {path}")
    return value, payload


def _safe_path(root: Path, name: object, *, directory: bool) -> Path:
    if type(name) is not str or not name or "\\" in name or ":" in name:
        raise ValueError("corpus path invalid")
    pure = PurePosixPath(name)
    if (pure.is_absolute() or any(part in (".", "..", "") for part in name.split("/"))
            or pure.as_posix() != name):
        raise ValueError("corpus path invalid")
    path = root.joinpath(*pure.parts)
    probe = root
    for part in pure.parts:
        probe = probe / part
        if probe.is_symlink():
            raise ValueError("corpus path symlink forbidden")
    try:
        contained = path.resolve(strict=True).is_relative_to(root.resolve(strict=True))
    except OSError as exc:
        raise ValueError("corpus path missing or unreadable") from exc
    if not contained:
        raise ValueError("corpus path escapes output root")
    if directory and not path.is_dir() or not directory and not path.is_file():
        raise ValueError("corpus path kind invalid")
    if not directory and not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("corpus file is not regular")
    return path


def _file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("corpus evidence file invalid")
    before = path.stat()
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            count += len(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ) or count != after.st_size:
        raise ValueError("corpus evidence changed during read")
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[int, int]:
    details = path.stat()
    if details.st_ino == 0:
        raise ValueError("corpus file identity unavailable")
    return details.st_dev, details.st_ino


def _job(value: object, expected: CorpusJob) -> None:
    job = _mapping(value, set(CorpusJob.__dataclass_fields__), "corpus job")
    for name in ("stage_id", "split"):
        if type(job[name]) is not str or job[name] != getattr(expected, name):
            raise ValueError("corpus job identity mismatch")
    for name in ("world_seed", "rollout_seed", "ordinal"):
        if type(job[name]) is not int or job[name] != getattr(expected, name):
            raise ValueError("corpus job identity mismatch")


def _receipt(config: CorpusConfig, record: dict, receipt_path: Path,
             run_dir: Path, receipt: dict, reserved: set[Path]) -> None:
    _mapping(receipt, _RECEIPT_KEYS, "capture receipt")
    if (receipt["schema"] != _RECEIPT_SCHEMA
            or receipt["run_id"] != record["run_id"]
            or receipt["job"] != record["job"]
            or receipt["sequence_manifest_sha256"] != record["sequence_manifest_sha256"]
            or receipt["world_sha256"] != record["world_sha256"]
            or receipt["teacher_commit"] != config.teacher_commit
            or receipt["teacher_image_id"] != config.teacher_image_id
            or receipt["odometry_source"] != "px4_ekf2"
            or receipt["camera_pose_source"] != "px4_ekf2_calibrated_camera"):
        raise ValueError("capture receipt identity mismatch")
    files = _mapping(receipt["files"], _FILE_KEYS, "capture receipt files")
    selected: set[tuple[int, int]] = set()
    reserved_identities = {_file_identity(path) for path in reserved}
    for name, value in files.items():
        info = _mapping(value, {"path", "sha256"}, f"receipt {name}")
        path = _safe_path(run_dir, info["path"], directory=False)
        identity = _file_identity(path)
        if identity in selected or identity in reserved_identities:
            raise ValueError("capture receipt file reused")
        selected.add(identity)
        if _file_sha(path) != _sha(info["sha256"], f"receipt {name}"):
            raise ValueError("capture receipt file hash mismatch")


def load_corpus_index(config: CorpusConfig, path: Path) -> CorpusIndexAudit:
    """Verify byte and job integrity only; never qualify training sources."""
    if not isinstance(config, CorpusConfig) or len(config.jobs()) != 54:
        raise ValueError("validated 54-job corpus configuration required")
    index, payload = _json_file(Path(path), maximum=1024 * 1024)
    _mapping(index, {"schema", "corpus_digest", "records"}, "corpus index")
    if index["schema"] != _INDEX_SCHEMA or index["corpus_digest"] != config.digest:
        raise ValueError("corpus index identity mismatch")
    rows = index["records"]
    if not isinstance(rows, list) or len(rows) != 54:
        raise ValueError("corpus index must have exactly 54 jobs")

    run_ids: set[str] = set()
    sequence_dirs: set[Path] = set()
    world_paths: set[Path] = set()
    receipt_paths: set[Path] = set()
    sample_hashes: set[str] = set()
    selected: list[CorpusIndexJob] = []
    root = config.output_root.resolve(strict=True)
    benchmark_hash = _file_sha(config.benchmark_config)
    if benchmark_hash != config.benchmark_sha256:
        raise ValueError("benchmark config changed after corpus configuration load")
    if _file_sha(config.vehicle_model) != config.vehicle_model_sha256:
        raise ValueError("vehicle model changed after corpus configuration load")
    for expected, value in zip(config.jobs(), rows, strict=True):
        record = _mapping(value, _RECORD_KEYS, "corpus record")
        _job(record["job"], expected)
        run_id = record["run_id"]
        if type(run_id) is not str or _RUN.fullmatch(run_id) is None or run_id in run_ids:
            raise ValueError("corpus run ID invalid or repeated")
        run_ids.add(run_id)
        if record["terminal"] != "success":
            raise ValueError("failed corpus run cannot become a training sequence")
        sequence_dir = _safe_path(root, record["sequence_dir"], directory=True)
        world_path = _safe_path(root, record["world_json"], directory=False)
        receipt_path = _safe_path(root, record["receipt_path"], directory=False)
        if (sequence_dir in sequence_dirs or world_path in world_paths
                or receipt_path in receipt_paths):
            raise ValueError("corpus evidence path repeated")
        sequence_dirs.add(sequence_dir)
        world_paths.add(world_path)
        receipt_paths.add(receipt_path)
        if len({sequence_dir.parent, world_path.parent, receipt_path.parent}) != 1:
            raise ValueError("corpus run files have different parents")

        world_sha = _sha(record["world_sha256"], "world")
        expected_world = (json.dumps(build_corpus_world(expected), sort_keys=True,
                                     indent=2, allow_nan=False) + "\n").encode()
        if _file_sha(world_path) != world_sha or hashlib.sha256(expected_world).hexdigest() != world_sha:
            raise ValueError("corpus world bytes do not match declared job")

        manifest_path = _safe_path(sequence_dir, "manifest.json", directory=False)
        samples_path = _safe_path(sequence_dir, "samples.npz", directory=False)
        manifest_sha = _sha(record["sequence_manifest_sha256"], "sequence manifest")
        manifest, manifest_payload = _json_file(manifest_path, maximum=64 * 1024)
        if hashlib.sha256(manifest_payload).hexdigest() != manifest_sha:
            raise ValueError("corpus sequence manifest hash mismatch")
        if manifest.get("schema") != SCHEMA_V3:
            raise ValueError("corpus sequence must use depth-mask v3")
        sample_sha = _sha(manifest.get("samples_sha256"), "sequence samples")
        if sample_sha in sample_hashes:
            raise ValueError("corpus sequence samples repeated")
        sample_hashes.add(sample_sha)
        if _file_sha(samples_path) != sample_sha:
            raise ValueError("corpus sequence samples hash mismatch")
        try:
            sequence = load_sequence(sequence_dir)
        except (OSError, TypeError, KeyError, ValueError) as exc:
            raise ValueError("corpus sequence invalid") from exc
        if (_file_sha(manifest_path) != manifest_sha
                or _file_sha(samples_path) != sample_sha):
            raise ValueError("corpus sequence changed during load")
        provenance = sequence.provenance
        if (type(provenance.seed) is not int or provenance.seed != expected.world_seed
                or provenance.split != expected.split
                or provenance.world_sha256 != world_sha
                or provenance.config_sha256 != benchmark_hash
                or provenance.teacher != f"ego@{config.teacher_commit}"
                or provenance.source != _SOURCE):
            raise ValueError("corpus sequence provenance mismatch")

        receipt_sha = _sha(record["receipt_sha256"], "capture receipt")
        receipt, receipt_payload = _json_file(receipt_path, maximum=64 * 1024)
        if hashlib.sha256(receipt_payload).hexdigest() != receipt_sha:
            raise ValueError("capture receipt hash mismatch")
        _receipt(config, record, receipt_path, receipt_path.parent, receipt,
                 {world_path, manifest_path, samples_path, receipt_path})
        if _file_sha(receipt_path) != receipt_sha:
            raise ValueError("capture receipt changed during validation")
        selected.append(CorpusIndexJob(
            expected.stage_id, expected.split, expected.world_seed,
            expected.rollout_seed, expected.ordinal, run_id, sequence_dir,
            manifest_sha, sample_sha, world_sha, receipt_sha,
        ))
    return CorpusIndexAudit(tuple(selected), hashlib.sha256(payload).hexdigest())
