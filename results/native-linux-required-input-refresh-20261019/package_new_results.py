"""Seal only this turn's new header and authorized refresh observations."""

import ast
import hashlib
import json
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
HEADERS = ROOT / "results/native-linux-build-headers-20261019"
NAME = "native-linux-ordered-build-inputs-20261019"
for folder in (HEADERS, OUT):
    for path in folder.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
hs = json.loads((HEADERS / "analysis-summary.json").read_text(encoding="utf-8"))
rs = json.loads((OUT / "analysis-summary.json").read_text(encoding="utf-8"))
assert hs["exact_selection_complete"] and rs["exact_selection_complete"]
assert hs["complete_files"] == 1457 and rs["complete_files"] == 166
assert rs["prior_field_matches"] == 166 and not rs["differences"]
files = sorted(path for folder in (HEADERS, OUT) for path in folder.rglob("*") if path.is_file())
files.append(ROOT / "docs/NATIVE_LINUX_ORDERED_BUILD_INPUTS_PROGRESS.md")
entries = []
for path in files:
    data = path.read_bytes()
    entries.append(dict(path=path.relative_to(ROOT).as_posix(), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
manifest = dict(schema="new-observation-archive-map-v1", entries=entries,
                mapped_bytes=sum(row["bytes"] for row in entries),
                limits=["Only two newly authorized/current observations, their helpers/proposals/derived records and progress document.",
                        "The166 refreshed old-path contents are newly acquired under explicit user authorization; old saved payloads/archives were not rehashed.",
                        "Prior candidate references remain references, not full environment/runtime/custody/build/ABI/admission proof."])
manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
evidence = ROOT / "evidence"
with (evidence / (NAME + ".map.json")).open("xb") as stream:
    stream.write(manifest_bytes)
archive = evidence / (NAME + ".zip")
with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
    for row in entries:
        bundle.write(ROOT / row["path"], row["path"])
    bundle.writestr("MANIFEST.json", manifest_bytes)
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    assert len(bundle.namelist()) == len(entries) + 1
    for row in entries:
        data = bundle.read(row["path"])
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
    assert bundle.read("MANIFEST.json") == manifest_bytes
data = archive.read_bytes()
receipt = dict(schema="new-observation-archive-receipt-v1", path=archive.relative_to(ROOT).as_posix(),
               bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), members=len(entries)+1,
               mapped_members=len(entries), mapped_bytes=manifest["mapped_bytes"], manifest_bytes=len(manifest_bytes),
               whole_member_bytes=manifest["mapped_bytes"]+len(manifest_bytes),
               new_archive_crc_and_member_hashes_checked=True, helper_ast_only=True,
               tests_run=False, old_archives_or_payloads_checked=False, all_qualifications=False, dispatchable=False)
with (evidence / (NAME + ".receipt.json")).open("x",encoding="utf-8",newline="\n") as stream:
    json.dump(receipt,stream,indent=2); stream.write("\n")
print(json.dumps(receipt))
