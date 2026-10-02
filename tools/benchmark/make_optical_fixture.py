#!/usr/bin/env python3
"""Build a separate, static colored-target world for camera-axis validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

TARGETS = (
    ("negative_y_red", -1.0, 0.482, (1.0, 0.0, 0.0)),
    ("center_green", 0.0, 0.482, (0.0, 1.0, 0.0)),
    ("positive_y_blue", 1.0, 0.482, (0.0, 0.0, 1.0)),
    ("high_yellow", 0.0, 1.482, (1.0, 1.0, 0.0)),
)


def make_fixture(source: Path, destination: Path, manifest: Path) -> dict:
    if destination.exists() or manifest.exists():
        raise FileExistsError("refusing to overwrite optical fixture evidence")
    tree = ET.parse(source)
    world = tree.getroot().find("world")
    if world is None:
        raise ValueError("SDF world missing")
    vehicle = [item for item in world.findall("include")
               if item.findtext("name") == "x500_benchmark_8"]
    if len(vehicle) != 1:
        raise ValueError("expected exactly one benchmark vehicle")
    for model in list(world.findall("model")):
        if model.get("name") != "ground":
            world.remove(model)
    for include in list(world.findall("include")):
        if include is not vehicle[0]:
            world.remove(include)
    targets = []
    for name, y, z, color in TARGETS:
        model = ET.SubElement(world, "model", name=name)
        ET.SubElement(model, "static").text = "true"
        position = [-3.88, y, z]
        ET.SubElement(model, "pose").text = f"{position[0]} {position[1]} {position[2]} 0 0 0"
        link = ET.SubElement(model, "link", name="body")
        visual = ET.SubElement(link, "visual", name="visual")
        sphere = ET.SubElement(ET.SubElement(visual, "geometry"), "sphere")
        ET.SubElement(sphere, "radius").text = "0.25"
        material = ET.SubElement(visual, "material")
        rgba = f"{color[0]} {color[1]} {color[2]} 1"
        ET.SubElement(material, "ambient").text = rgba
        ET.SubElement(material, "diffuse").text = rgba
        targets.append({"name": name, "world_xyz_m": position, "rgb": list(color), "radius_m": 0.25})
    ET.indent(tree.getroot())
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    result = {
        "schema": "flydrones-optical-fixture-v1",
        "source_world_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "fixture_world_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "targets": targets,
    }
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(make_fixture(args.source, args.world, args.manifest), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
