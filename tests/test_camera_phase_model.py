from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest

from flydrones.camera_phase import CameraScheduleMode
from tools.configure_gazebo_camera_phase import configure_camera_model

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MODEL = ROOT / "assets/gazebo/models/OakD-Lite-Fly/model.sdf"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def camera_values(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    sensor = root.find(".//sensor[@name='StereoOV7251']")
    assert sensor is not None
    camera = sensor.find("camera")
    assert camera is not None
    return {
        "sensor_type": sensor.get("type"),
        "pose": sensor.findtext("pose"),
        "update_rate": sensor.findtext("update_rate"),
        "topic": sensor.findtext("topic"),
        "horizontal_fov": camera.findtext("horizontal_fov"),
        "width": camera.findtext("image/width"),
        "height": camera.findtext("image/height"),
        "format": camera.findtext("image/format"),
        "near": camera.findtext("clip/near"),
        "far": camera.findtext("clip/far"),
        "triggered": [element.text for element in camera.findall("triggered")],
        "inertial": ET.tostring(root.find(".//link/inertial"), encoding="unicode"),
    }


def write_source(tmp_path: Path) -> Path:
    source = tmp_path / "source" / "model.sdf"
    source.parent.mkdir()
    source.write_bytes(SOURCE_MODEL.read_bytes())
    return source


def test_phased_adds_one_trigger_without_changing_camera_or_inertial_parameters(tmp_path):
    source = write_source(tmp_path)
    target = tmp_path / "run-copy" / "model.sdf"
    before = camera_values(source)

    evidence = configure_camera_model(source, target, mode=CameraScheduleMode.PHASED)
    after = camera_values(target)

    assert after == {**before, "triggered": ["true"]}
    assert evidence["mode"] == "phased"
    assert evidence["structural_diff"] == [
        "sensor[StereoOV7251]/camera/triggered: <missing> -> true"
    ]
    assert evidence["source_sha256"] == sha256(source)
    assert evidence["target_sha256"] == sha256(target)
    assert evidence["source_sha256"] != evidence["target_sha256"]


def test_simultaneous_keeps_free_running_model_byte_for_byte(tmp_path):
    source = write_source(tmp_path)
    target = tmp_path / "run-copy" / "model.sdf"

    evidence = configure_camera_model(source, target, mode=CameraScheduleMode.SIMULTANEOUS)

    assert target.read_bytes() == source.read_bytes()
    assert camera_values(target)["triggered"] == []
    assert evidence["structural_diff"] == []
    assert evidence["source_sha256"] == evidence["target_sha256"]


def test_transform_does_not_touch_non_target_files(tmp_path):
    source = write_source(tmp_path)
    target = tmp_path / "run-copy" / "model.sdf"
    target.parent.mkdir()
    sibling = target.parent / "model.config"
    sibling.write_text("leave-me-byte-for-byte\n", encoding="utf-8")
    sibling_before = sibling.read_bytes()

    configure_camera_model(source, target, mode=CameraScheduleMode.PHASED)

    assert sibling.read_bytes() == sibling_before


@pytest.mark.parametrize("sensor_count", (0, 2))
def test_transform_rejects_missing_or_multiple_stereo_sensors(tmp_path, sensor_count: int):
    source = write_source(tmp_path)
    tree = ET.parse(source)
    root = tree.getroot()
    sensor = root.find(".//sensor[@name='StereoOV7251']")
    assert sensor is not None
    link = root.find(".//link")
    assert link is not None
    if sensor_count == 0:
        link.remove(sensor)
    else:
        link.append(deepcopy(sensor))
    tree.write(source, encoding="utf-8", xml_declaration=True)

    with pytest.raises(ValueError, match="exactly one StereoOV7251"):
        configure_camera_model(
            source,
            tmp_path / "run-copy/model.sdf",
            mode=CameraScheduleMode.PHASED,
        )


@pytest.mark.parametrize("configured_value", ("true", "false"))
def test_transform_rejects_preexisting_trigger_configuration(tmp_path, configured_value: str):
    source = write_source(tmp_path)
    tree = ET.parse(source)
    camera = tree.getroot().find(".//sensor[@name='StereoOV7251']/camera")
    assert camera is not None
    ET.SubElement(camera, "triggered").text = configured_value
    tree.write(source, encoding="utf-8", xml_declaration=True)

    with pytest.raises(ValueError, match="pre-existing trigger"):
        configure_camera_model(
            source,
            tmp_path / "run-copy/model.sdf",
            mode=CameraScheduleMode.PHASED,
        )


def test_transform_rejects_same_path_and_backup_targets(tmp_path):
    source = write_source(tmp_path)

    with pytest.raises(ValueError, match="different paths"):
        configure_camera_model(source, source, mode=CameraScheduleMode.PHASED)
    with pytest.raises(ValueError, match="backup"):
        configure_camera_model(
            source,
            tmp_path / "run/backups/OakD-Lite-Fly/model.sdf",
            mode=CameraScheduleMode.PHASED,
        )


def test_transform_rejects_camera_parameter_drift_before_writing(tmp_path):
    source = write_source(tmp_path)
    tree = ET.parse(source)
    width = tree.getroot().find(".//sensor[@name='StereoOV7251']/camera/image/width")
    assert width is not None
    width.text = "320"
    tree.write(source, encoding="utf-8", xml_declaration=True)
    target = tmp_path / "run-copy/model.sdf"

    with pytest.raises(ValueError, match="width must be 160"):
        configure_camera_model(source, target, mode=CameraScheduleMode.PHASED)

    assert not target.exists()
