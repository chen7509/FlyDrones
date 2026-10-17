"""Audit retained development PX4 reset history; never create training data."""

from __future__ import annotations

import argparse
import json
import zipfile
from hashlib import sha256
from pathlib import Path

import numpy as np

from flydrones.connectome_training.px4_reset_epoch import audit_reset_epochs

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "results/openvins-health-physical-dev-1701-v2/development-seed-27201/capture-v1"
TOPICS = ROOT / "results/ekf2-sample-time-dev-1701/consumed-topics.npz"
ULOG_SHA256 = "55428c6d37e75d7fa2d53ab67a6527b4350fa020dca4a761a44fa7aec68d1028"
TOPICS_SHA256 = "0527175f368c7b7a74fb43a95fe0f849e076df11448733780ac7aaa36bd86cad"
TOPICS_ARCHIVE = ROOT / "evidence/ekf2-sample-time-dev-1701.zip"
TOPICS_ARCHIVE_SHA256 = "4a34ff156b71dd1b20433a62b7b34aa53bcd6bde1ec5dd28d99a543f62550230"
TOPICS_ARCHIVE_MEMBER = "ekf2-sample-time-dev-1701/consumed-topics.npz"
RGB_MANIFEST_SHA256 = "6d71edb71136d4c0b696f900c46b5913dad586bb71b2b0f8e340a649fb631bdf"
FIELDS = {
    "vehicle_local_position": (
        "timestamp", "timestamp_sample", "xy_reset_counter", "z_reset_counter",
        "vxy_reset_counter", "vz_reset_counter", "heading_reset_counter",
    ),
    "vehicle_attitude": ("timestamp", "timestamp_sample", "quat_reset_counter"),
}


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _within(base: Path, relative: str) -> Path:
    if not isinstance(relative, str):
        raise ValueError("capture member path invalid")
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError("capture member path escapes or is missing")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results/px4-reset-epoch-dev-1701")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if _sha(TOPICS) != TOPICS_SHA256:
        raise ValueError("consumed topic extract hash drifted")
    if _sha(TOPICS_ARCHIVE) != TOPICS_ARCHIVE_SHA256:
        raise ValueError("topic source archive hash drifted")
    with zipfile.ZipFile(TOPICS_ARCHIVE) as source_archive:
        if (source_archive.testzip() is not None
                or sha256(source_archive.read(TOPICS_ARCHIVE_MEMBER)).hexdigest()
                != TOPICS_SHA256):
            raise ValueError("topic extract is not the sealed source member")
    rgb_manifest = CAPTURE / "rgb-capture-manifest.json"
    if _sha(rgb_manifest) != RGB_MANIFEST_SHA256:
        raise ValueError("RGB manifest hash drifted")
    frames = json.loads(rgb_manifest.read_text(encoding="utf-8"))["frames"]
    times = [frame["frame_ns"] for frame in frames]
    for frame in frames:
        if _sha(_within(CAPTURE, frame["path"])) != frame["sha256"]:
            raise ValueError("RGB frame hash drifted")
    ulog_manifest = json.loads((CAPTURE / "px4-ulog-manifest.json").read_text(encoding="utf-8"))
    if len(ulog_manifest["logs"]) != 1:
        raise ValueError("expected one development ULog")
    ulog = _within(CAPTURE, ulog_manifest["logs"][0]["path"])
    if (_sha(ulog) != ULOG_SHA256
            or ulog_manifest["logs"][0]["sha256"] != ULOG_SHA256):
        raise ValueError("development ULog hash drifted")
    with np.load(TOPICS, allow_pickle=False) as source:
        topics = {
            name: {field: source[f"{name}__{field}"].copy() for field in fields}
            for name, fields in FIELDS.items()
        }
    audit = audit_reset_epochs(times, topics)
    if audit["frame_count"] != len(frames) or audit["eligible_for_live_capture"] is not False:
        raise ValueError("reset audit must retain all frames and refuse live qualification")
    summary = {
        "schema": "flydrones-px4-reset-epoch-development-v1",
        "seed": 27201,
        "input_sha256": {
            "ulog": ULOG_SHA256, "topic_extract": TOPICS_SHA256,
            "rgb_manifest": RGB_MANIFEST_SHA256,
        },
        "frame_count": audit["frame_count"],
        "reset_transition_count": len(audit["transitions"]),
        "reset_epoch_unresolved_frames": audit["reset_epoch_unresolved_frames"],
        "missing_topic_frames": sum(any(reason.endswith("_missing") for reason in row["reasons"])
                                    for row in audit["records"]),
        "eligible_for_live_capture": False,
        "training_data_written": False,
        "clock_epoch_qualified": False,
    }
    args.output.mkdir(parents=True)
    (args.output / "reset-audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
