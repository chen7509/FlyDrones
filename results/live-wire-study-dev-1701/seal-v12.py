"""Seal all v12 offline attempts, including preparation failures, without overwrite."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DESTINATION = ROOT / "evidence/live-wire-agent-v12-preparation-dev-1701.zip"


def main():
    if DESTINATION.exists():
        raise FileExistsError(DESTINATION)
    files = [path for dirname in ("study-v12", "study-v12-retry", "study-v12-retry2")
             for path in (HERE / dirname).rglob("*") if path.is_file()]
    files += [HERE / name for name in (
        "audit-v12.py", "audit-v12-output.json", "prepare-v12.py", "write-committed-source-v12.py",
        "committed-source-v12.json", "committed-source-v12-retry.json",
        "committed-source-v12-retry2.json", "seal-v12.py",
    )]
    files += [ROOT / name for name in (
        "docs/AGENT_LIVE_WIRE_V12_PREPARATION_REPORT.md",
        "docs/superpowers/specs/2026-10-12-agent-live-wire-study-design.md",
        "docs/superpowers/plans/2026-10-12-agent-live-wire-study.md",
    )]
    files.sort()
    if len(files) != len(set(files)) or any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError("duplicate or unsupported evidence input")
    manifest = []
    with zipfile.ZipFile(DESTINATION, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            data = path.read_bytes()
            name = path.relative_to(ROOT).as_posix()
            archive.writestr(name, data)
            manifest.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        archive.writestr("MANIFEST.json", json.dumps(dict(members=manifest), indent=2, sort_keys=True) + "\n")
    with zipfile.ZipFile(DESTINATION) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC mismatch")
        listed = json.loads(archive.read("MANIFEST.json"))["members"]
        if listed != manifest:
            raise ValueError("ZIP member listing mismatch")
        for row in listed:
            raw = archive.read(row["path"])
            if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError("ZIP member digest mismatch")
    print(json.dumps(dict(path=str(DESTINATION), members=len(manifest),
                          sha256=hashlib.sha256(DESTINATION.read_bytes()).hexdigest())))


if __name__ == "__main__":
    main()
