"""Read the sealed v12 ZIP independently and emit publication checks."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ARCHIVE = ROOT / "evidence/live-wire-agent-v12-preparation-dev-1701.zip"
OUTPUT = HERE / "publication-v12.json"


def main():
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    with zipfile.ZipFile(ARCHIVE) as archive:
        if archive.testzip() is not None:
            raise ValueError("archive CRC")
        declared = json.loads(archive.read("MANIFEST.json"))["members"]
        actual_names = set(archive.namelist()) - {"MANIFEST.json"}
        if len(declared) != 193 or {row["path"] for row in declared} != actual_names:
            raise ValueError("archive member set")
        for row in declared:
            data = archive.read(row["path"])
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("archive member digest: " + row["path"])
        prefixes = ["results/live-wire-study-dev-1701/" + name + "/prepare-failed.json"
                    for name in ("study-v12", "study-v12-retry")]
        if any(name not in actual_names for name in prefixes):
            raise ValueError("failed preparation evidence absent")
        if any(json.loads(archive.read(name))["physical_run"] is not False for name in prefixes):
            raise ValueError("failed preparation mislabeled")
    result = dict(schema="live-wire-agent-v12-publication-v1", archive_sha256=digest,
                  members=len(declared), all_member_hashes_verified=True, crc_verified=True,
                  failed_preparations_retained=2, physical_run=False, live_qualified=False)
    with OUTPUT.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
