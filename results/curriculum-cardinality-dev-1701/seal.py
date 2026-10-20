from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
members = (
    "docs/superpowers/specs/2026-10-12-curriculum-sequence-cardinality.md",
    "docs/superpowers/plans/2026-10-12-curriculum-sequence-cardinality.md",
    "docs/CURRICULUM_SEQUENCE_CARDINALITY_REPORT.md",
    "src/flydrones/connectome_training/curriculum_session.py",
    "tests/connectome_training/test_curriculum_sequence_selection.py",
    "results/curriculum-cardinality-dev-1701/focused.txt",
    "results/curriculum-cardinality-dev-1701/ruff.txt",
    "results/curriculum-cardinality-dev-1701/diff-check.txt",
)
archive = root / "evidence/curriculum-sequence-cardinality-dev-1701-v2.zip"
if archive.exists():
    raise FileExistsError(archive)
manifest = {}
with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as packed:
    for name in members:
        payload = (root / name).read_bytes()
        manifest[name] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
        packed.writestr(name, payload)
    packed.writestr("member-manifest.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n")
with zipfile.ZipFile(archive) as packed:
    assert packed.testzip() is None
    for name, info in manifest.items():
        payload = packed.read(name)
        assert len(payload) == info["bytes"]
        assert hashlib.sha256(payload).hexdigest() == info["sha256"]
seal = {
    "archive": str(archive),
    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    "members": len(manifest) + 1,
    "member_integrity": True,
}
(Path(__file__).parent / "seal-v2.json").write_text(
    json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(seal, sort_keys=True))
