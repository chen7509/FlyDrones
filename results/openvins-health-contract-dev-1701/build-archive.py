import hashlib
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
output = root / "evidence/openvins-health-contract-dev-1701.zip"
external = root / "evidence/openvins-health-contract-dev-1701.audit.json"

files = set()
for name in (
    "docs/OPENVINS_HEALTH_CONTRACT_REPORT.md",
    "docs/superpowers/specs/2026-10-07-openvins-health-contract-design.md",
    "docs/superpowers/plans/2026-10-07-openvins-health-contract.md",
    "tools/benchmark/openvins_health_contract.py",
    "tools/benchmark/openvins_online_probe.cpp",
    "tools/benchmark/openvins_online_shadow.py",
    "tools/benchmark/audit_openvins_health_cohort.py",
    "tools/benchmark/audit_openvins_health_physical_faults.py",
    "tools/benchmark/openvins_health_physical_faults.py",
    "tools/benchmark/openvins_health_fault_physical_preflight.py",
    "tools/benchmark/execute_openvins_health_physical_fault.py",
    "tests/benchmark/test_openvins_health_contract.py",
    "tests/benchmark/test_openvins_online_shadow.py",
    "tests/benchmark/test_audit_openvins_health_cohort.py",
    "tests/benchmark/test_audit_openvins_health_physical_faults.py",
    "tests/benchmark/test_openvins_health_physical_faults.py",
):
    files.add(root / name)

for path in (root / "results/openvins-health-contract-dev-1701").rglob("*"):
    if path.is_file():
        files.add(path)

normal = root / "results/openvins-health-physical-dev-1701-v2"
for path in normal.glob("*.json"):
    files.add(path)
for study in [normal / "development-seed-27201", *normal.glob("held-out-seed-*")]:
    if not study.is_dir():
        continue
    for name in (
        "study-manifest.json", "physical-dispatch.json", "physical-completion.json",
        "run-evidence.json", "trajectory-audit.json", "capture-v1/result.json",
        "capture-v1/px4-ulog-manifest.json", "capture-v1/simulation-random-seed.json",
        "capture-v1/runtime-binding-pre.json", "capture-v1/runtime-binding-post.json",
        "capture-v1/supervisor.json", "capture-v1/shadow/health-result.json",
        "capture-v1/shadow/health-evidence.jsonl",
    ):
        selected = study / name
        if selected.is_file():
            files.add(selected)
    for ulog in (study / "capture-v1/px4-ulog").rglob("*.ulg"):
        files.add(ulog)

for version in ("", "-v2", "-v3"):
    faults = root / f"results/openvins-health-physical-faults-dev-1701{version}"
    if not faults.exists():
        continue
    for path in faults.glob("*.json"):
        files.add(path)
    for study in [path for path in faults.iterdir() if path.is_dir()]:
        for name in (
            "study-manifest.json", "physical-dispatch.json", "physical-completion.json",
            "physical-output.txt", "capture-v1/result.json", "capture-v1/supervisor.json",
            "capture-v1/px4-ulog-manifest.json", "capture-v1/simulation-random-seed.json",
            "capture-v1/runtime-binding-pre.json", "capture-v1/runtime-binding-post.json",
            "capture-v1/shadow/health-result.json", "capture-v1/shadow/health-evidence.jsonl",
            "capture-v1/shadow/health-fault-result.json", "capture-v1/shadow/health-fault-events.jsonl",
            "capture-v1/estimator-readiness.jsonl",
        ):
            selected = study / name
            if selected.is_file():
                files.add(selected)
        for ulog in (study / "capture-v1/px4-ulog").rglob("*.ulg"):
            files.add(ulog)

files = sorted((path for path in files if path.is_file()), key=lambda path: path.relative_to(root).as_posix())
members = []
for path in files:
    data = path.read_bytes()
    members.append({
        "path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    })
manifest = {
    "schema": "openvins-health-contract-evidence-manifest-v1",
    "members": members,
    "historical_failures_retained": True,
    "covariance_sim_domain_qualified": True,
    "hardware_covariance_calibrated": False,
    "odometry_published": False,
    "fusion_eligible": False,
}
manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in files:
        archive.write(path, path.relative_to(root).as_posix())
    archive.writestr("evidence-manifest.json", manifest_bytes)

with zipfile.ZipFile(output) as archive:
    bad_member = archive.testzip()
    member_count = len(archive.infolist())
audit = {
    "schema": "openvins-health-contract-evidence-archive-audit-v1",
    "archive": str(output.relative_to(root).as_posix()),
    "bytes": output.stat().st_size,
    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    "member_count": member_count,
    "crc_verified": bad_member is None,
    "first_bad_member": bad_member,
}
external.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
print(json.dumps(audit, indent=2, sort_keys=True))
