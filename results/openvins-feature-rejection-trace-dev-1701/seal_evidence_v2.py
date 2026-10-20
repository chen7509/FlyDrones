from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
stage = root / "results" / "openvins-feature-rejection-trace-dev-1701"
output = root / "evidence" / "openvins-feature-rejection-trace-dev-1701-v2.zip"
fixed = [
    root / "evidence" / "openvins-motion-intent-native-dev-1701.zip",
    root / "docs" / "ESTIMATOR_PHYSICAL_REFUSAL_DIAGNOSIS_REPORT.md",
    root / "docs" / "superpowers" / "specs" / "2026-10-07-openvins-feature-rejection-trace-design.md",
    root / "docs" / "superpowers" / "plans" / "2026-10-07-openvins-feature-rejection-trace.md",
    root / "tools" / "benchmark" / "openvins_feature_trace.py",
    root / "tools" / "benchmark" / "audit_openvins_feature_trace.py",
    root / "tools" / "benchmark" / "gpl" / "README.md",
    root / "tools" / "benchmark" / "gpl" / "openvins_feature_trace.patch",
    root / "tests" / "benchmark" / "test_openvins_feature_trace.py",
]
files = sorted({*stage.rglob("*"), *fixed})
files = [path for path in files if path.is_file()]
entries = []
for path in files:
    data = path.read_bytes()
    entries.append({
        "name": path.relative_to(root).as_posix(),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    })
manifest = {
    "schema": "openvins-feature-rejection-trace-evidence-v1",
    "members": entries,
    "member_count": len(entries),
    "physical_replay": False,
    "fusion_eligible": False,
    "truth_used": False,
    "root_cause_qualified": False,
}
manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    archive.writestr("manifest.json", manifest_bytes)
    for path in files:
        archive.write(path, path.relative_to(root).as_posix())
with zipfile.ZipFile(output, "r") as archive:
    if archive.testzip() is not None:
        raise RuntimeError("zip CRC failure")
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate archive member")
    loaded = json.loads(archive.read("manifest.json"))
    if loaded != manifest:
        raise RuntimeError("manifest bytes mismatch")
    for entry in loaded["members"]:
        data = archive.read(entry["name"])
        if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"member mismatch: {entry['name']}")
archive_bytes = output.read_bytes()
summary = {
    "path": output.relative_to(root).as_posix(),
    "size": len(archive_bytes),
    "sha256": hashlib.sha256(archive_bytes).hexdigest(),
    "zip_member_count": len(files) + 1,
    "manifest_member_count": len(files),
    "verified": True,
}
(stage / "evidence-seal.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
