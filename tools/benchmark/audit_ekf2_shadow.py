"""Read-only EKF2 shadow audit of one pinned development evidence archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.ekf2_shadow import audit_shadow_frames  # noqa: E402

ARCHIVE_SHA256 = "82f9377c1ad11f824064e1cbbc5feb834f77803af3ec83d00bfb0c8355072ddd"
ULOG_SHA256 = "5f7cbc3c11ca53e92a64a6d58aed957f6ecf3034618756bc95f0912fac125e55"
PREFIX = "openvins-texture-dev/"
EPISODE = "episode-v1/"
RGB_MANIFEST = EPISODE + "rgb-capture-manifest.json"
ULOG_MANIFEST = EPISODE + "px4-ulog-manifest.json"
RESULT = EPISODE + "result.json"
TOPICS = ("vehicle_local_position", "vehicle_attitude", "estimator_status",
          "estimator_status_flags")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(name: str) -> bool:
    return (isinstance(name, str) and name.startswith(PREFIX)
            and "\\" not in name and ":" not in name
            and all(part not in ("", ".", "..") for part in name.rstrip("/").split("/"))
            and not PurePosixPath(name).is_absolute())


def _read_index(index_path: Path, archive_hash: str) -> dict[str, dict]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if (index.get("schema") != "flydrones-openvins-texture-dev-evidence-v1"
            or index.get("archive_sha256") != archive_hash
            or type(index.get("file_count")) is not int
            or not isinstance(index.get("files"), list)
            or index["file_count"] != len(index["files"])):
        raise ValueError("evidence index metadata mismatch")
    files = {}
    for entry in index["files"]:
        if not isinstance(entry, dict):
            raise ValueError("evidence index entry invalid")
        name = entry.get("path")
        if (not isinstance(name, str) or not name or name.endswith("/")
                or not _safe_member(PREFIX + name)):
            raise ValueError("evidence index path unsafe")
        if (name in files or not isinstance(entry.get("bytes"), int)
                or entry["bytes"] < 0 or not isinstance(entry.get("sha256"), str)
                or len(entry["sha256"]) != 64):
            raise ValueError("evidence index entry invalid")
        files[name] = entry
    return files


def _verified_members(archive_path: Path, index: dict[str, dict]) -> dict[str, bytes]:
    members = {}
    seen = set()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            name = info.filename
            if not _safe_member(name) or name in seen:
                raise ValueError("unsafe or duplicate archive member")
            seen.add(name)
            if info.is_dir():
                continue
            relative = name.removeprefix(PREFIX)
            expected = index.get(relative)
            if expected is None:
                raise ValueError("archive member absent from index")
            data = archive.read(info)
            if len(data) != expected["bytes"] or _digest(data) != expected["sha256"]:
                raise ValueError("archive member does not match index")
            members[relative] = data
    if set(members) != set(index):
        raise ValueError("archive and index member sets differ")
    return members


def _manifest_json(members: dict[str, bytes], name: str, schema: str) -> dict:
    try:
        value = json.loads(members[name])
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} missing or malformed") from exc
    if not isinstance(value, dict) or value.get("schema") != schema:
        label = "RGB manifest" if name == RGB_MANIFEST else "ULog manifest"
        raise ValueError(f"{label} schema invalid")
    return value


def _verified_frame_times(members: dict[str, bytes]) -> list[int]:
    manifest = _manifest_json(members, RGB_MANIFEST, "flydrones-rgb-capture-v1")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("RGB manifest frames missing")
    times = []
    seen = set()
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("RGB manifest frame malformed")
        ns, name = frame.get("frame_ns"), frame.get("path")
        if (type(ns) is not int or ns < 0 or (times and ns <= times[-1])
                or not isinstance(name, str) or not name.startswith("rgb-frames/")
                or not _safe_member(PREFIX + EPISODE + name)
                or name in seen or type(frame.get("width")) is not int
                or type(frame.get("height")) is not int
                or frame["width"] <= 0 or frame["height"] <= 0):
            raise ValueError("RGB manifest frame invalid")
        seen.add(name)
        raw = members.get(EPISODE + name)
        if raw is None or _digest(raw) != frame.get("sha256"):
            raise ValueError("RGB manifest frame digest mismatch")
        times.append(ns)
    return times


def _verified_ulog(members: dict[str, bytes], expected_sha256: str) -> bytes:
    manifest = _manifest_json(members, ULOG_MANIFEST, "flydrones-px4-ulog-capture-v1")
    try:
        result = json.loads(members[RESULT])
        logs = manifest["logs"]
        log = logs[0]
        relative = log["path"]
        data = members[EPISODE + relative]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ULog manifest or result malformed") from exc
    if (not isinstance(logs, list) or len(logs) != 1
            or not isinstance(result, dict)
            or result.get("px4_ulogs") != logs
            or result.get("status") != "out_of_bounds"
            or result.get("odometry_source") != "gazebo_model_truth"
            or result.get("camera_pose_source") != "gazebo_model_truth"
            or not isinstance(relative, str) or not relative.startswith("px4-ulog/")
            or not _safe_member(PREFIX + EPISODE + relative)
            or log.get("valid_header") is not True
            or log.get("bytes") != len(data)
            or log.get("sha256") != expected_sha256
            or _digest(data) != expected_sha256):
        raise ValueError("ULog identity or historical result mismatch")
    return data


def _read_ulog(path: Path) -> dict:
    from pyulog import ULog

    ulog = ULog(str(path))
    return {name: ulog.get_dataset(name).data for name in TOPICS}


def _audit_verified_archive(
        archive_path: Path, index_path: Path, *, expected_archive_sha256: str,
        expected_ulog_sha256: str, read_ulog=None) -> dict:
    """Private test seam; public entrypoint always passes fixed historical pins."""
    archive_path, index_path = Path(archive_path), Path(index_path)
    archive_hash = _digest_file(archive_path)
    if archive_hash != expected_archive_sha256:
        raise ValueError("archive SHA mismatch")
    index_hash = _digest_file(index_path)
    index = _read_index(index_path, archive_hash)
    members = _verified_members(archive_path, index)
    frames = _verified_frame_times(members)
    ulog_bytes = _verified_ulog(members, expected_ulog_sha256)
    with tempfile.TemporaryDirectory(prefix="flydrones-ekf2-ulog-") as directory:
        path = Path(directory) / "source.ulg"
        path.write_bytes(ulog_bytes)
        topics = (read_ulog or _read_ulog)(path)
        report = audit_shadow_frames(frames, topics)
    report["input_archive_sha256"] = archive_hash
    report["input_index_sha256"] = index_hash
    report["input_ulog_sha256"] = _digest(ulog_bytes)
    report["historical_result_status"] = "out_of_bounds"
    return report


def audit_archive(archive_path: Path, index_path: Path) -> dict:
    """Audit only the exact, fixed historical archive and ULog."""
    return _audit_verified_archive(
        archive_path, index_path, expected_archive_sha256=ARCHIVE_SHA256,
        expected_ulog_sha256=ULOG_SHA256)


def write_report_once(path: Path, report: dict) -> None:
    """Atomically publish a complete report without replacing an existing one."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                         prefix=".ekf2-shadow-", dir=path.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    report = audit_archive(args.archive, args.index)
    write_report_once(args.output, report)
    print(json.dumps({"output": str(args.output), "frame_count": report["frame_count"],
                      "counts": report["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
