"""Analyze only the new saved header observation; no Linux or old payload rehash."""

import ast
import json
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
result = json.loads((OUT / "collection-result.json").read_text(encoding="utf-8"))
metadata = (OUT / "metadata.jsonl").read_bytes()
rows = [json.loads(line) for line in metadata.splitlines()]
identities = {row["path"]: row for row in rows if row["type"] == "identity"}
ends = {row["path"]: row for row in result["observed_files"]}
selected = {row["path"]: row for row in selection["selected"]}
assert set(identities) <= set(selected) and set(ends) <= set(selected)
files, pins = {}, {}
for path, item in selected.items():
    identity, end = identities.get(path), ends.get(path)
    row = dict(path=path, candidate_roles=item["roles"], identity=identity,
               state="unknown_or_not_completely_acquired", file_pin=None, admitted=False,
               actual_new_build_consumption_proven=False)
    if end:
        assert end["stable"] and end["before"] == end["after"]
        pin = {key: end[key] for key in ("path", "resolved", "bytes", "sha256")}
        row.update(state="new_complete_header_observation_not_admitted", file_pin=pin,
                   before=end["before"], after=end["after"], blob=end["blob"])
        pins[path] = pin
    files[path] = row

def family(path):
    for prefix, label in (("/usr/include/c++/13/", "libstdc++13"),
                          ("/usr/include/x86_64-linux-gnu/c++/13/", "libstdc++13-platform"),
                          ("/usr/lib/gcc/x86_64-linux-gnu/13/include/", "gcc13-builtin-headers"),
                          ("/usr/include/eigen3/", "eigen"), ("/usr/include/ceres/", "ceres"),
                          ("/usr/include/opencv4/", "opencv4"), ("/usr/include/boost/", "boost")):
        if path.startswith(prefix):
            return label
    return "other-system-headers"

prior_sha_fields = {row.get("sha256") or (row.get("saved_pin") or {}).get("sha256")
                    for row in selection["excluded"].values()}
prior_sha_fields.discard(None)
proposal = json.loads((OUT / "required-input-refresh-PROPOSAL.json").read_text(encoding="utf-8"))
summary = dict(schema="native-linux-new-header-summary-v1", selected=len(selected),
               prior_depfile_header_candidates=selection["prior_depfile_header_candidates"],
               package_filesystem_candidates=selection["package_filesystem_candidates"],
               identity_paths_attempted=len(identities), identity_status=dict(Counter(r.get("status") for r in identities.values())),
               complete_files=len(ends), new_distinct_sha_blobs=len({row["sha256"] for row in ends.values()}),
               complete_payload_bytes=sum(row["bytes"] for row in ends.values()),
               actual_payload_bytes_read=result["stream_payload_bytes"],
               metadata_frame_body_bytes=result["stream_metadata_bytes"], retained_jsonl_bytes=len(metadata),
               metadata_rows=dict(Counter(row["type"] for row in rows)), stderr_bytes=result["stderr_bytes"],
               stderr_text=(OUT / "stderr.bin").read_bytes().decode("utf-16-le"),
               parent_elapsed_s=result["elapsed_s"], parent_exit=result.get("exit"),
               readers_closed=result["readers_closed"], linux_completion=result["linux_completion"],
               active_partial=result["active_partial"], errors=result["errors"],
               collection_complete=result["collection_complete"],
               exact_selection_complete=bool(result["collection_complete"] and set(ends) == set(selected)),
               saved_header_family_counts=dict(Counter(family(path) for path in ends)),
               duplicate_new_content_retention_files=sum("duplicate_new_content_saved_as" in row for row in ends.values()),
               prior_saved_sha_field_intersection=len(prior_sha_fields & {row["sha256"] for row in ends.values()}),
               comparison_is_saved_fields_only_not_old_payload_rehash=True,
               known_exclusion_spellings=len(selection["excluded"]),
               known_excluded_inode_pairs=len(selection["excluded_native_identities"]),
               required_input_refresh_proposal_count=proposal["count"],
               required_input_refresh_proposal_roles=dict(Counter(row["role"] for row in proposal["paths"].values())),
               proposal_authorized=False, proposal_executed=False, cmake_modules_selected=0,
               new_toolchain_closure_complete=False, new_request_complete=False,
               actual_new_build_consumption_proven=False, abi_verified=False,
               old_payload_rehash=False, old_archive_check=False, tests_run=False,
               resource_query=False, compiler_configure_link_or_native_target=False,
               linux_file_writes=False, all_qualifications=False, dispatchable=False)
assert len(metadata) == result["stream_metadata_bytes"] + len(rows)
assert len(metadata) <= selection["caps"]["metadata_bytes"]
assert summary["complete_payload_bytes"] == result["stream_payload_bytes"]
for name, value in {
    "file-bindings.json": dict(schema="native-linux-new-header-bindings-v1", files=files,
                               acquisition_time_only=True, all_qualifications=False, dispatchable=False),
    "new-file-pins.json": dict(schema="native-linux-new-read-file-pins-v1", files=pins,
                               acquisition_time_only=True, admitted=False),
    "analysis-summary.json": summary,
    "missing-evidence.json": dict(schema="native-linux-new-header-missing-v1",
        selected_missing=[path for path in selected if path not in ends],
        actual_new_build_input_closure_unknown=True,
        pending_no_reacquisition_exception_proposal="required-input-refresh-PROPOSAL.json",
        proposal_executed=False,
        limits=["Completed acquisition covers this exact saved candidate selection, not all headers or new compile-time consumed inputs.",
                "No newly read include references followed; no CMake modules or directory enumeration.",
                "Previously acquired tool/config/source content hashes were not refreshed; identity alone cannot establish current content pins.",
                "Proposal for169 old-content refresh paths is not authorized or dispatched by this header collection.",
                "Missing source candidates/LICENSE/ReadMe.md, current deployed source, toolchain recipe/receipt, package origin, implicit/loader/ABI and measured inputs remain unknown or incomplete.",
                "Fresh execution resource/no-competition/cgroup/pidfd and applicable admission remain separate gates; no compile/native/SDK/resource/Linux-write authorization inferred.",
                "No production templates filled, auto build/run, old library provenance claim or second collection."],
        all_qualifications=False, dispatchable=False),
}.items():
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
for path in OUT.glob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
print(json.dumps(summary))
