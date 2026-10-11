"""Seal this code-only stage without altering historical evidence."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "evidence/connectome-corpus-v2-index-dev-1701.zip"
MEMBERS = (
    "src/flydrones/connectome_training/corpus_config.py",
    "src/flydrones/connectome_training/corpus_index.py",
    "tests/connectome_training/test_corpus_index.py",
    "docs/superpowers/specs/2026-10-12-connectome-corpus-v2-index-design.md",
    "docs/superpowers/plans/2026-10-12-connectome-corpus-v2-index.md",
    "docs/CONNECTOME_CORPUS_V2_INDEX_REPORT.md",
    "results/connectome-corpus-v2-index-dev-1701/full-tests.txt",
    "results/connectome-corpus-v2-index-dev-1701/changed-ruff.txt",
    "results/connectome-corpus-v2-index-dev-1701/diff-check.txt",
    "results/connectome-corpus-v2-index-dev-1701/review.md",
    "results/connectome-corpus-v2-index-dev-1701/seal.py",
)


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    payloads = {name: (ROOT / name).read_bytes() for name in MEMBERS}
    manifest = {
        "schema": "flydrones-connectome-corpus-v2-index-evidence-v1",
        "scope": "synthetic structural integrity only; no source authentication",
        "members": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in sorted(payloads.items())
        },
    }
    with zipfile.ZipFile(OUTPUT, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payloads.items()):
            archive.writestr(name, data)
        archive.writestr("members.json", json.dumps(manifest, sort_keys=True, indent=2))
    with zipfile.ZipFile(OUTPUT) as archive:
        if archive.testzip() is not None:
            raise ValueError("evidence ZIP CRC failed")
        for name, expected in manifest["members"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected["sha256"]:
                raise ValueError(f"evidence member mismatch: {name}")
    print(json.dumps({"zip": str(OUTPUT), "sha256": hashlib.sha256(
        OUTPUT.read_bytes()).hexdigest(), "members": len(MEMBERS)}, sort_keys=True))


if __name__ == "__main__":
    main()
