#!/usr/bin/env python3
"""Audit the frozen Fly/EGO result archive without rerunning the test set."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.benchmark.provenance import verify_sealed_manifest  # noqa: E402

PREFIX = "results/fly-ego-comparison/"
CONTROLLERS = ("fly_raw", "fly_guided", "ego")


def _json(archive: zipfile.ZipFile, name: str) -> dict | list:
    return json.loads(archive.read(name))


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and name == path.as_posix()


def _runtime_world_sdf(original: bytes, start: list[float]) -> bytes:
    """Reproduce the benchmark backend's sole allowed world transformation."""
    tree = ET.ElementTree(ET.fromstring(original))
    world = tree.getroot().find("world")
    include = ET.SubElement(world, "include")
    ET.SubElement(include, "uri").text = "model://x500_benchmark"
    ET.SubElement(include, "name").text = "x500_benchmark_8"
    ET.SubElement(include, "pose").text = f"{start[0]} {start[1]} .24 0 0 0"
    ET.indent(tree.getroot())
    output = io.BytesIO()
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return output.getvalue()


def audit_archive(archive_path: Path, index_path: Path, root: Path = ROOT) -> dict:
    """Verify byte provenance, pairing and result totals; report rerun gaps."""
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or not index:
        raise ValueError("empty archive index")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(index):
            raise ValueError("archive/index entries differ or are duplicated")
        if any(not name.startswith(PREFIX) or not _safe_name(name) for name in names):
            raise ValueError("archive contains an unsafe path")
        for name, expected in index.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError(f"changed archived file: {name}")

        freeze = _json(archive, PREFIX + "freeze/manifest.json")
        seeds = _json(archive, PREFIX + "formal/seed_manifest.json")
        verify_sealed_manifest(freeze)
        verify_sealed_manifest(seeds)
        if seeds["generated_after_freeze_sha256"] != freeze["manifest_sha256"]:
            raise ValueError("formal worlds do not reference the frozen inputs")
        if len(seeds["worlds"]) != 20:
            raise ValueError("expected 20 formal worlds")

        missing_sources = []
        changed_sources = []
        for relative, expected in freeze["files"].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError(f"frozen path escapes repository: {relative}")
            if not path.is_file():
                missing_sources.append(relative)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                changed_sources.append(relative)

        world_by_seed = {}
        for item in seeds["worlds"]:
            seed = item["seed"]
            if seed in world_by_seed:
                raise ValueError(f"duplicate world seed: {seed}")
            world_by_seed[seed] = item
            for key, digest_key in (("world_json", "world_json_sha256"),
                                    ("world_sdf", "world_sdf_sha256")):
                if hashlib.sha256(archive.read(item[key])).hexdigest() != item[digest_key]:
                    raise ValueError(f"changed world: {item[key]}")

        jobs = _json(archive, PREFIX + "formal/jobs.json")
        state = _json(archive, PREFIX + "formal/batch_state.json")
        expected_pairs = {(seed, controller) for seed in world_by_seed for controller in CONTROLLERS}
        job_pairs = [(job["seed"], job["controller"]) for job in jobs]
        record_pairs = [(record["job"]["seed"], record["job"]["controller"])
                        for record in state["records"]]
        if (len(jobs) != 60 or set(job_pairs) != expected_pairs or len(set(job_pairs)) != 60
                or len(record_pairs) != 60 or set(record_pairs) != expected_pairs
                or len(set(record_pairs)) != 60 or state["completed"] != 60
                or state["total"] != 60):
            raise ValueError("job or terminal-record pairing is incomplete")

        counts: dict[str, Counter] = {controller: Counter() for controller in CONTROLLERS}
        result_paths = set()
        for seed, controller in expected_pairs:
            base = f"{PREFIX}formal/episodes/{seed}/{controller}/"
            result_name = base + "result.json"
            result_paths.add(result_name)
            result = _json(archive, result_name)
            world = world_by_seed[seed]
            if (result["seed"] != seed or result["controller"] != controller
                    or result["family"] != world["family"]
                    or result["freeze_manifest_sha256"] != freeze["manifest_sha256"]
                    or not result.get("status") or not result.get("path")):
                raise ValueError(f"invalid formal result: {result_name}")
            inputs = _json(archive, base + "input_manifest.json")
            episode_json = archive.read(base + "world.json")
            if hashlib.sha256(episode_json).hexdigest() != inputs["world_json_sha256"] \
                    or inputs["world_json_sha256"] != world["world_json_sha256"]:
                raise ValueError(f"episode world differs: {base}world.json")
            if inputs["world_sdf_sha256"] != world["world_sdf_sha256"]:
                raise ValueError(f"episode world input differs: {base}world.sdf")
            original_sdf = archive.read(world["world_sdf"])
            start = _json(archive, world["world_json"])["start"]
            if archive.read(base + "world.sdf") != _runtime_world_sdf(original_sdf, start):
                raise ValueError(f"episode runtime world differs: {base}world.sdf")
            counts[controller][result["status"]] += 1
        if {name for name in names if name.endswith("/result.json") and
            name.startswith(PREFIX + "formal/episodes/")} != result_paths:
            raise ValueError("unexpected or missing formal result")
        records = {(r["job"]["seed"], r["job"]["controller"]): r for r in state["records"]}
        for pair, record in records.items():
            result = _json(archive, f"{PREFIX}formal/episodes/{pair[0]}/{pair[1]}/result.json")
            if record["status"] != result["status"] or record["returncode"] != 0:
                raise ValueError(f"terminal record differs: {pair}")
        summary = _json(archive, PREFIX + "formal/summary.json")
        for controller in CONTROLLERS:
            if summary["controllers"][controller]["status_counts"] != dict(counts[controller]):
                raise ValueError(f"summary differs: {controller}")
        ulog_count = sum(name.lower().endswith(".ulg") for name in names
                         if name.startswith(PREFIX + "formal/"))
        return {
            "freeze_sha256": freeze["manifest_sha256"],
            "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "archived_files": len(names),
            "worlds": len(world_by_seed),
            "episodes": len(result_paths),
            "status_counts": {name: dict(counts[name]) for name in CONTROLLERS},
            "missing_frozen_sources": missing_sources,
            "changed_frozen_sources": changed_sources,
            "formal_ulog_count": ulog_count,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path,
                        default=ROOT / "evidence/fly-ego-comparison-2026-09-22.zip")
    parser.add_argument("--index", type=Path,
                        default=ROOT / "evidence/fly-ego-comparison-2026-09-22.sha256.json")
    args = parser.parse_args()
    print(json.dumps(audit_archive(args.archive, args.index), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
