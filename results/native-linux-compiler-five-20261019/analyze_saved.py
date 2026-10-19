"""Report only the newly saved five-file observation, without Linux or old payload reads."""

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
selected = [row["path"] for row in selection["selected"]]
assert len(selected) == 5 and set(identities) <= set(selected) and set(ends) <= set(selected)
files, pins = {}, {}
for path in selected:
    end = ends.get(path)
    item = dict(path=path, identity=identities.get(path),
                state="unknown_or_not_fully_acquired", file_pin=None,
                actual_compiler_invocation_proven=False, abi_verified=False, admitted=False)
    if end:
        assert end["stable"] and end["before"] == end["after"]
        pin = {key: end[key] for key in ("path", "resolved", "bytes", "sha256")}
        item.update(state="new_complete_acquisition_time_observation_not_admitted",
                    file_pin=pin, before=end["before"], after=end["after"], blob=end["blob"])
        pins[path] = pin
    files[path] = item
prior_sha_fields = {r.get("sha256") or (r.get("saved_pin") or {}).get("sha256")
                    for r in selection["excluded"].values()}
prior_sha_fields.discard(None)
summary = dict(schema="native-linux-compiler-five-summary-v1", selected=selected,
               identity_paths_attempted=len(identities), complete_files=len(ends),
               new_distinct_sha_blobs=len({row["sha256"] for row in ends.values()}),
               complete_payload_bytes=sum(row["bytes"] for row in ends.values()),
               actual_payload_bytes_read=result["stream_payload_bytes"],
               metadata_frame_body_bytes=result["stream_metadata_bytes"],
               retained_jsonl_bytes=len(metadata), metadata_rows=dict(Counter(row["type"] for row in rows)),
               stderr_bytes=result["stderr_bytes"],
               stderr_text=(OUT / "stderr.bin").read_bytes().decode("utf-16-le"),
               parent_elapsed_s=result["elapsed_s"], parent_exit=result.get("exit"),
               readers_closed=result["readers_closed"], linux_completion=result["linux_completion"],
               active_partial=result["active_partial"], errors=result["errors"],
               collection_complete=result["collection_complete"],
               exact_five_complete=bool(result["collection_complete"] and set(ends) == set(selected)),
               prior_saved_sha_field_intersection=len(prior_sha_fields & {row["sha256"] for row in ends.values()}),
               old_payload_rehash=False, saved_exclusion_spellings=len(selection["excluded"]),
               saved_excluded_native_inode_pairs=len(selection["excluded_native_identities"]),
               cmake_modules_selected=0, directory_search=False, resource_query=False,
               compiler_configure_link_or_native_target=False, linux_file_writes=False,
               bootstrap_interpreter_authenticated=False, toolchain_closure_complete=False,
               new_request_complete=False, abi_verified=False, all_qualifications=False, dispatchable=False)
assert len(metadata) <= selection["caps"]["metadata_bytes"]
assert summary["complete_payload_bytes"] == result["stream_payload_bytes"]
for name, value in {
    "file-bindings.json": dict(schema="native-linux-compiler-five-bindings-v1", files=files,
                               acquisition_time_only=True, all_qualifications=False, dispatchable=False),
    "new-file-pins.json": dict(schema="native-linux-new-read-file-pins-v1", files=pins,
                               acquisition_time_only=True, admitted=False),
    "analysis-summary.json": summary,
    "missing-evidence.json": dict(schema="native-linux-compiler-five-missing-v1",
        selected_missing=[path for path in selected if path not in ends],
        limits=["Completeness applies only to these five explicit paths at observation time.",
                "Content/native identity is not actual compiler invocation, signed package origin or ABI proof.",
                "Earlier retained tool/config/source hashes were not refreshed; saved fields and observed inode exclusions are conservative, not a current global hardlink inventory.",
                "Full current source/toolchain/header/config/package/implicit input/recursive-lazy-loader and new request bindings remain incomplete.",
                "The observer runtime and its implicit dependencies are not authenticated or fully inventoried.",
                "Fresh execution resource/no-competition/cgroup/pidfd, measured calibration/noise and applicable admission remain separate requirements.",
                "No production templates filled, build/run dispatch, old library provenance claim or second collection."],
        all_qualifications=False, dispatchable=False),
}.items():
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
for path in OUT.glob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
print(json.dumps(summary))
