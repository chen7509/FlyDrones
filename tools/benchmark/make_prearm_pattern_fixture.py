"""Change only the two existing prearm boards' albedo in a development copy."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw
from PIL import __version__ as pillow_version

from flydrones.benchmark.worlds import generate_development_world
from tools.benchmark.make_prearm_board_fixture import BOARDS

SCHEMA = "flydrones-openvins-board-pattern-dev-v1"
SOURCE_HASHES = {
    "world.json": "generated_world_json_sha256",
    "world.sdf": "generated_world_sdf_sha256",
    "ground_albedo.png": "ground_albedo_sha256",
    "obstacle_albedo.png": "obstacle_albedo_sha256",
}


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _board_pattern(path: Path) -> None:
    image = Image.new("RGB", (512, 512), (24, 24, 24))
    draw = ImageDraw.Draw(image)
    for row, y in enumerate((112, 280, 424)):
        for column, x in enumerate((128, 384)):
            shade = 232 if (row + column) % 2 == 0 else 208
            draw.rectangle((x - 56, y - 48, x + 55, y + 47), fill=(shade,) * 3)
    image.save(path, format="PNG", optimize=False)


def _board_uris(root: ET.Element) -> list[ET.Element]:
    result = []
    for name in ("wall_0", "wall_1"):
        models = root.findall(f"world/model[@name='{name}']")
        if len(models) != 1 or models[0].findtext("static") != "true":
            raise ValueError("source requires exactly two static prearm boards")
        nodes = models[0].findall("link/visual/material/pbr/metal/albedo_map")
        if len(nodes) != 1:
            raise ValueError("board albedo URI missing or ambiguous")
        result.append(nodes[0])
    return result


def _non_board_albedo_digest(root: ET.Element) -> str:
    normalized = copy.deepcopy(root)
    for node in _board_uris(normalized):
        node.text = "BOARD_ALBEDO_ONLY"
    data = ET.canonicalize(ET.tostring(normalized, encoding="unicode"), strip_text=True)
    return hashlib.sha256(data.encode()).hexdigest()


def make_prearm_pattern_fixture(source: Path, output: Path) -> dict:
    source, output = Path(source), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("pattern fixture output already exists")
    if (not source.is_dir() or source.is_symlink() or (source / "INCOMPLETE.json").exists()
            or (source / "INCOMPLETE.json").is_symlink()):
        raise ValueError("unsafe or incomplete source fixture")
    for name in ("manifest.json", *SOURCE_HASHES):
        if not (source / name).is_file() or (source / name).is_symlink():
            raise ValueError(f"unsafe or missing source file: {name}")
    original_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if original_manifest.get("schema") != "flydrones-openvins-prearm-board-dev-v2":
        raise ValueError("source must be the verified prearm board fixture")
    hashes = {name: _sha(source / name) for name in SOURCE_HASHES}
    if any(hashes[name] != original_manifest.get(key) for name, key in SOURCE_HASHES.items()):
        raise ValueError("source hash mismatch")
    expected_world = generate_development_world(1701)
    expected_world["boxes"] = list(BOARDS)
    if json.loads((source / "world.json").read_text()) != expected_world:
        raise ValueError("source physical world changed")
    tree = ET.parse(source / "world.sdf")
    root = tree.getroot()
    before = _non_board_albedo_digest(root)
    for node in _board_uris(root):
        if node.text != "obstacle_albedo.png":
            raise ValueError("unexpected source board albedo")
        node.text = "board_albedo.png"
    if _non_board_albedo_digest(root) != before:
        raise ValueError("change escaped board albedo URIs")

    output.mkdir(parents=True, exist_ok=False)
    try:
        for name in ("world.json", "ground_albedo.png", "obstacle_albedo.png"):
            shutil.copyfile(source / name, output / name)
        shutil.copyfile(source / "manifest.json", output / "source-manifest.json")
        _board_pattern(output / "board_albedo.png")
        ET.indent(tree)
        tree.write(output / "world.sdf", encoding="utf-8", xml_declaration=True)
        if _non_board_albedo_digest(ET.parse(output / "world.sdf").getroot()) != before:
            raise ValueError("written scene changed outside board albedo")
        manifest = {
            "schema": SCHEMA,
            "scope": "artificial single-aircraft development fixture; board albedo only, not a formal benchmark",
            "source_manifest_sha256": _sha(source / "manifest.json"),
            "source_files_sha256": hashes,
            "non_board_albedo_sdf_sha256": before,
            "files_sha256": {name: _sha(output / name) for name in (*SOURCE_HASHES, "board_albedo.png")},
            "board_albedo_sha256": _sha(output / "board_albedo.png"),
            "pattern": {"image_size": [512, 512], "background": 24, "x_centers": [128, 384],
                        "y_centers": [112, 280, 424], "rectangle_size": [112, 96], "shades": [232, 208]},
            "pillow_version": pillow_version,
        }
        with (output / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
        return manifest
    except BaseException as exc:
        try:
            with (output / "INCOMPLETE.json").open("x", encoding="utf-8") as stream:
                json.dump({"status": "incomplete", "error_type": type(exc).__name__,
                           "retry": "use a new output directory"}, stream, indent=2)
        except OSError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(make_prearm_pattern_fixture(args.source_dir, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
