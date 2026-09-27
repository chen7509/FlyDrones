"""Create a trial-only Gazebo camera model for one scheduling mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parents[1]
if TYPE_CHECKING:
    from flydrones.camera_phase import CameraScheduleMode


PROTECTED_ASSET = (ROOT / "assets/gazebo/models/OakD-Lite-Fly/model.sdf").resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(data)
            handle.flush()
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _tree_bytes(tree: ET.ElementTree) -> bytes:
    with tempfile.NamedTemporaryFile("w+b", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        return temporary.read_bytes()
    finally:
        temporary.unlink(missing_ok=True)


def _required_text(parent: ET.Element, path: str, label: str) -> str:
    value = parent.findtext(path)
    if value is None or not value.strip():
        raise ValueError(f"StereoOV7251 {label} is missing")
    return value.strip()


def _validate_source(root: ET.Element) -> tuple[ET.Element, ET.Element]:
    sensors = root.findall(".//sensor[@name='StereoOV7251']")
    if len(sensors) != 1:
        raise ValueError(f"expected exactly one StereoOV7251 sensor, found {len(sensors)}")
    sensor = sensors[0]
    if sensor.get("type") != "depth_camera":
        raise ValueError("StereoOV7251 sensor type must be depth_camera")
    cameras = sensor.findall("camera")
    if len(cameras) != 1:
        raise ValueError(f"expected exactly one StereoOV7251 camera block, found {len(cameras)}")
    camera = cameras[0]
    if camera.findall("triggered") or camera.findall("trigger_topic"):
        raise ValueError("pre-existing trigger configuration is not allowed")

    width = _required_text(camera, "image/width", "width")
    height = _required_text(camera, "image/height", "height")
    update_rate = _required_text(sensor, "update_rate", "update rate")
    image_format = _required_text(camera, "image/format", "image format")
    if width != "160":
        raise ValueError("StereoOV7251 width must be 160")
    if height != "120":
        raise ValueError("StereoOV7251 height must be 120")
    if float(update_rate) != 10.0:
        raise ValueError("StereoOV7251 update rate must be 10")
    if image_format != "R_FLOAT32":
        raise ValueError("StereoOV7251 image format must be R_FLOAT32")
    for path, label in (
        ("horizontal_fov", "horizontal FOV"),
        ("clip/near", "near clip"),
        ("clip/far", "far clip"),
    ):
        _required_text(camera, path, label)
    _required_text(sensor, "pose", "pose")
    link = next(
        (candidate for candidate in root.findall(".//link") if sensor in candidate.findall("sensor")),
        None,
    )
    if link is None or link.find("inertial") is None:
        raise ValueError("StereoOV7251 link inertial is missing")
    return sensor, camera


def configure_camera_model(
    source: Path,
    target: Path,
    *,
    mode: CameraScheduleMode,
) -> dict[str, object]:
    source = source.resolve()
    target = target.resolve()
    mode_value = mode.value if hasattr(mode, "value") else str(mode)
    if mode_value not in {"simultaneous", "phased"}:
        raise ValueError(f"unsupported camera schedule mode: {mode_value}")
    if source == target:
        raise ValueError("source and target must be different paths")
    if target == PROTECTED_ASSET:
        raise ValueError("the repository camera asset is read-only")
    if "backups" in {part.lower() for part in target.parts}:
        raise ValueError("refusing to write a PX4 backup path")
    if not source.is_file():
        raise FileNotFoundError(source)

    tree = ET.parse(source)
    _, camera = _validate_source(tree.getroot())
    structural_diff: list[str] = []
    if mode_value == "phased":
        triggered = ET.Element("triggered")
        triggered.text = "true"
        camera.insert(0, triggered)
        structural_diff.append("sensor[StereoOV7251]/camera/triggered: <missing> -> true")
        target_bytes = _tree_bytes(tree)
    else:
        target_bytes = source.read_bytes()

    _write_atomic(target, target_bytes)
    return {
        "schema": "flydrones-camera-model-phase-v1",
        "mode": mode_value,
        "source": str(source),
        "target": str(target),
        "source_sha256": _sha256(source),
        "target_sha256": _sha256(target),
        "structural_diff": structural_diff,
        "preserved": {
            "width": 160,
            "height": 120,
            "update_rate_hz": 10.0,
            "image_format": "R_FLOAT32",
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _write_atomic(
        path,
        (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Configure one trial-copy OakD-Lite depth camera scheduling mode."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--mode", choices=("simultaneous", "phased"), required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()

    evidence = configure_camera_model(
        args.source,
        args.target,
        mode=args.mode,
    )
    if args.evidence is not None:
        _write_json(args.evidence, evidence)
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
