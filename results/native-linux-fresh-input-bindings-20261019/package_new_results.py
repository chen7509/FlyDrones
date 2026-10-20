"""Package only this new observation and its progress document; never access Linux."""

import ast
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
NAME = "native-linux-fresh-input-bindings-20261019"
EVIDENCE = ROOT / "evidence"
result = json.loads((OUT / "collection-result.json").read_text(encoding="utf-8"))
selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
metadata = (OUT / "metadata.jsonl").read_bytes()
rows = [json.loads(line) for line in metadata.splitlines()]
new_ends = result["observed_files"]
duplicates = [row for row in new_ends if "duplicate_new_content_saved_as" in row]
prior_sha_fields = {ref["sha256"] for ref in selection["excluded"].values() if ref.get("sha256")}
new_sha_fields = {row["sha256"] for row in new_ends}
ast_checked = []
for source in sorted(OUT.glob("*.py")):
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    ast_checked.append(source.name)
observations = {
    "schema": "native-linux-fresh-input-executor-observations-v1",
    "scope": "Only new saved metadata, helper syntax and new archive integrity; no old payload or archive reads.",
    "prior_distinct_acquired_paths": selection["prior_distinct_acquired_paths"],
    "conservative_exclusion_spellings": len(selection["excluded"]),
    "summary_prior_acquired_content_paths_means": "1148 conservative exclusion spellings, not 1148 distinct acquired files",
    "metadata_row_types": dict(Counter(row["type"] for row in rows)),
    "metadata_frame_body_bytes": result["stream_metadata_bytes"],
    "retained_jsonl_bytes": len(metadata),
    "jsonl_separator_bytes": len(rows),
    "jsonl_form": "Unmodified JSON frame bodies plus one LF per frame, written in binary mode",
    "complete_end_receipts": len(new_ends),
    "duplicate_new_contents_retained_with_partial_suffix": len(duplicates),
    "genuinely_unclosed_transfers": 1,
    "genuinely_unclosed_bytes": (OUT / result["active_partial"]).stat().st_size,
    "saved_sha_field_intersection": len(prior_sha_fields & new_sha_fields),
    "sha_field_comparison_not_old_payload_rehash": True,
    "helper_ast_only": ast_checked,
    "tests_run": False,
    "old_evidence_reverified": False,
    "native_or_compiler_run": False,
    "all_qualifications": False,
    "dispatchable": False,
}
assert len(metadata) == result["stream_metadata_bytes"] + len(rows)
assert len(metadata) <= 2097152
assert len(new_ends) == 749
assert len(duplicates) == 15
assert observations["genuinely_unclosed_bytes"] == 215
with (OUT / "executor-observations.json").open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(observations, stream, indent=2)
    stream.write("\n")

files = sorted(path for path in OUT.rglob("*") if path.is_file())
files.append(ROOT / "docs" / "NATIVE_LINUX_FRESH_INPUT_BINDINGS_PROGRESS.md")
entries = []
for path in files:
    data = path.read_bytes()
    entries.append({"path": path.relative_to(ROOT).as_posix(), "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()})
manifest = {"schema": "new-observation-archive-map-v1", "entries": entries,
            "mapped_bytes": sum(row["bytes"] for row in entries),
            "limitations": ["Only this new bounded observation and declared helpers/docs.",
                            "Not a complete environment, authenticated custody, consumed build/loader closure, ABI or native admission.",
                            "One unclosed payload is retained as partial; prior payloads and archives are not included or rehashed."]}
manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
EVIDENCE.mkdir(exist_ok=True)
with (EVIDENCE / (NAME + ".map.json")).open("xb") as stream:
    stream.write(manifest_bytes)
archive = EVIDENCE / (NAME + ".zip")
with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
    for row in entries:
        bundle.write(ROOT / row["path"], row["path"])
    bundle.writestr("MANIFEST.json", manifest_bytes)
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    assert len(bundle.namelist()) == len(entries) + 1
    for row in entries:
        data = bundle.read(row["path"])
        assert len(data) == row["bytes"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
    assert bundle.read("MANIFEST.json") == manifest_bytes
archive_bytes = archive.read_bytes()
receipt = {"schema": "new-observation-archive-receipt-v1", "path": archive.relative_to(ROOT).as_posix(),
           "bytes": len(archive_bytes), "sha256": hashlib.sha256(archive_bytes).hexdigest(),
           "members": len(entries) + 1, "mapped_members": len(entries),
           "mapped_bytes": manifest["mapped_bytes"], "manifest_bytes": len(manifest_bytes),
           "whole_member_bytes": manifest["mapped_bytes"] + len(manifest_bytes),
           "new_archive_crc_and_member_hashes_checked": True,
           "old_archives_or_payloads_checked": False, "all_qualifications": False, "dispatchable": False}
with (EVIDENCE / (NAME + ".receipt.json")).open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(receipt, stream, indent=2)
    stream.write("\n")
print(json.dumps(receipt))
