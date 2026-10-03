#!/usr/bin/env python3
"""Add deterministic visual texture to a separate VIO development-world copy.

The source world geometry and JSON are never modified. This is an artificial
feature-rich interface fixture, not a realistic VIO accuracy benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw
from PIL import __version__ as pillow_version


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _texture(path: Path, seed: int, *, bark: bool) -> None:
    side = 512 if bark else 1024
    image = Image.new("RGB", (side, side))
    draw = ImageDraw.Draw(image)
    rng = random.Random(seed)
    tile = 4
    for y in range(0, side, tile):
        for x in range(0, side, tile):
            shade = rng.randrange(42, 211)
            if bark:
                stripe = 27 if (x // 24) % 2 else -27
                color = (max(0, min(255, shade + stripe)),
                         max(0, min(255, shade // 2 + stripe)), shade // 3)
            else:
                color = (shade, max(0, shade - 8), max(0, shade - 18))
            draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=color)
    image.save(path, format="PNG", optimize=False)


def make_fixture(source_json: Path, source_sdf: Path, output_dir: Path,
                 *, seed: int) -> dict:
    """Create one non-overwriting visual-only world copy and a hash manifest."""
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite {output_dir}")
    if seed < 0:
        raise ValueError("texture seed must be nonnegative")
    world_info = json.loads(source_json.read_text(encoding="utf-8"))
    if world_info.get("family") != "development_single":
        raise ValueError("texture fixture accepts development_single worlds only")
    tree = ET.parse(source_sdf)
    root = tree.getroot()
    world = root.find("world")
    if root.tag != "sdf" or world is None:
        raise ValueError("SDF world missing")
    ground = world.find("model[@name='ground']")
    if ground is None:
        raise ValueError("ground model missing")
    obstacles = [node for node in world.findall("model")
                 if node.get("name", "").startswith(("tree_", "wall_"))]
    if not obstacles:
        raise ValueError("no static obstacle visuals found")
    for model, filename in [(ground, "ground_albedo.png"),
                            *((item, "obstacle_albedo.png") for item in obstacles)]:
        if model.findtext("static") != "true":
            raise ValueError("refusing to texture a moving model")
        visual = model.find("link/visual")
        if visual is None:
            raise ValueError("model visual missing")
        material = visual.find("material")
        if material is None or material.find("pbr") is not None:
            raise ValueError("unexpected or already textured material")
        metal = ET.SubElement(ET.SubElement(material, "pbr"), "metal")
        ET.SubElement(metal, "albedo_map").text = filename
    output_dir.mkdir(parents=True)
    shutil.copyfile(source_json, output_dir / "world.json")
    _texture(output_dir / "ground_albedo.png", seed, bark=False)
    _texture(output_dir / "obstacle_albedo.png", seed + 1, bark=True)
    ET.indent(tree)
    tree.write(output_dir / "world.sdf", encoding="utf-8", xml_declaration=True)
    manifest = {
        "schema": "flydrones-vio-texture-dev-v1",
        "scope": "visual-only artificial development fixture; no physics or collision edits",
        "texture_seed": seed,
        "source_seed": world_info["seed"],
        "source_world_json_sha256": _sha(source_json),
        "source_world_sha256": _sha(source_sdf),
        "world_json_sha256": _sha(output_dir / "world.json"),
        "world_sdf_sha256": _sha(output_dir / "world.sdf"),
        "ground_albedo_sha256": _sha(output_dir / "ground_albedo.png"),
        "obstacle_albedo_sha256": _sha(output_dir / "obstacle_albedo.png"),
        "textured_model_count": 1 + len(obstacles),
        "pillow_version": pillow_version,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-json", type=Path, required=True)
    parser.add_argument("--world-sdf", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1701)
    args = parser.parse_args()
    print(json.dumps(make_fixture(args.world_json, args.world_sdf,
                                  args.output_dir, seed=args.seed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
