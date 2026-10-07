import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/openvins-motion-intent-native-dev-1701"
ARCHIVE = ROOT / "evidence/openvins-motion-intent-native-dev-1701.zip"
SEAL = RESULTS / "evidence-seal.json"
PREFIX = "openvins-motion-intent-native-dev-1701/"
FIXED_MEMBERS = [
    "evidence/openvins-motion-intent-visual-diagnosis-dev-1701.zip",
    "docs/ESTIMATOR_PHYSICAL_REFUSAL_DIAGNOSIS_REPORT.md",
    "docs/superpowers/specs/2026-10-07-openvins-native-motion-intent-design.md",
    "docs/superpowers/plans/2026-10-07-openvins-native-motion-intent.md",
    "tools/benchmark/motion_intent_gate.py",
    "tools/benchmark/openvins_online_shadow.py",
    "tools/benchmark/openvins_online_probe.cpp",
    "tools/benchmark/replay_openvins_motion_intent.py",
    "tools/benchmark/audit_openvins_motion_intent_replay.py",
    "tests/benchmark/test_motion_intent_gate.py",
    "tests/benchmark/test_openvins_motion_intent_native.py",
    "tests/benchmark/test_source_watchdog_retry_preflight.py",
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


members = [ROOT / relative for relative in FIXED_MEMBERS]
members.extend(
    path
    for path in sorted(RESULTS.rglob("*"))
    if path.is_file() and path != SEAL
)
seen = set()
records = []
for path in members:
    relative = path.relative_to(ROOT).as_posix()
    if relative in seen:
        continue
    seen.add(relative)
    data = path.read_bytes()
    records.append({"path": relative, "bytes": len(data), "sha256": digest(data)})

manifest = {
    "schema": "openvins-motion-intent-native-evidence-v1",
    "physical_capture_rerun": False,
    "px4_or_gazebo_started": False,
    "sealed_input_replayed": True,
    "fusion_eligible": False,
    "prior_archive": records[0],
    "members": records,
}
encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
if ARCHIVE.exists():
    raise FileExistsError(ARCHIVE)
with zipfile.ZipFile(ARCHIVE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
    for record in records:
        package.write(ROOT / record["path"], PREFIX + record["path"])
    package.writestr(PREFIX + "manifest.json", encoded)

with zipfile.ZipFile(ARCHIVE) as package:
    if package.testzip() is not None:
        raise RuntimeError("ZIP CRC failure")
    names = package.namelist()
    if len(names) != len(set(names)) or len(names) != len(records) + 1:
        raise RuntimeError("ZIP member identity failure")
    loaded = json.loads(package.read(PREFIX + "manifest.json"))
    for record in loaded["members"]:
        data = package.read(PREFIX + record["path"])
        if len(data) != record["bytes"] or digest(data) != record["sha256"]:
            raise RuntimeError("manifest member verification failure")

seal = {
    "path": ARCHIVE.relative_to(ROOT).as_posix(),
    "members": len(records) + 1,
    "bytes": ARCHIVE.stat().st_size,
    "sha256": digest(ARCHIVE.read_bytes()),
    "crc_verified": True,
    "manifest_members_verified": len(records),
}
SEAL.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
print(json.dumps(seal, indent=2))
