"""Derive candidates from this new observation only; no Linux reads or old payload hashes."""

import collections
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
result = json.loads((OUT / "collection-result.json").read_text(encoding="utf-8"))
rows = [json.loads(line) for line in (OUT / "metadata.jsonl").read_text(encoding="utf-8").splitlines()]
identities = {row["path"]: row for row in rows if row["type"] == "identity"}
ends = {row["path"]: row for row in result["observed_files"]}
skips = {row["path"]: row for row in rows if row["type"] == "skip"}
begins = {row["path"]: row for row in rows if row["type"] == "begin"}
by_inode = collections.defaultdict(list)
for path, row in identities.items():
    if row.get("status") == "observed":
        by_inode[(row["stat"]["dev"], row["stat"]["ino"])].append(path)


def prior_refs(path, row):
    names = [path]
    if row.get("status") == "observed":
        names += [row["resolved"]]
        names += by_inode[(row["stat"]["dev"], row["stat"]["ino"])]
    return {name: selection["excluded"][name] for name in dict.fromkeys(names) if name in selection["excluded"]}


files, new_pins = {}, {}
for item in selection["selected"]:
    path = item["path"]
    identity = identities.get(path)
    row = dict(path=path, roles=item["roles"], identity=identity, native_current_content_pin=None,
               all_qualifications=False, admitted=False)
    if identity is None or identity.get("status") != "observed":
        row["state"] = "native_identity_unavailable_or_unresolved"
    elif path in ends:
        end = ends[path]
        pin = dict(path=path, resolved=end["resolved"], bytes=end["bytes"], sha256=end["sha256"])
        row.update(state="new_saved_content_with_native_descriptor_and_link_observation_not_admitted",
                   native_current_content_pin=pin, new_blob=end["blob"], before=end["before"], after=end["after"])
        new_pins[path] = pin
    elif prior_refs(path, identity):
        row.update(state="native_identity_only_prior_payload_excluded_current_content_unknown",
                   retained_prior_observations=prior_refs(path, identity))
    elif path in begins:
        row.update(state="unclosed_content_transfer_no_current_pin", begin=begins[path],
                   partial_path=result["active_partial"])
    else:
        row.update(state="identity_only_content_not_acquired_in_bounded_selection", skip=skips.get(path))
    files[path] = row

bindings = {}
for key, path in {
    "pinned_cmake": "/usr/bin/cmake",
    "pinned_gxx": "/usr/bin/x86_64-linux-gnu-g++-13",
    "pinned_make": "/usr/bin/make",
    "pinned_python": "/usr/bin/python3.12",
    "eigen_config_dir": "/usr/share/eigen3/cmake",
    "opencv4_config_dir": "/usr/lib/x86_64-linux-gnu/cmake/opencv4",
    "boost_config_dir": "/usr/lib/x86_64-linux-gnu/cmake/Boost-1.83.0",
    "ceres_config_dir": "/usr/lib/x86_64-linux-gnu/cmake/Ceres",
}.items():
    bindings[key] = dict(candidate_path=path, identity=identities.get(path),
                         current_file_pin=new_pins.get(path), admitted=False,
                         note="Directory identity is not a consumed config closure; old retained SHA is not refreshed.")
for key in ("deployed_repo", "upstream_source_tree", "toolchain_file", "toolchain_receipt",
            "header_package_manifest", "current_linux_source_manifest", "capture_script", "exclusive_build_dir"):
    bindings[key] = dict(candidate_path=None, current_file_pin=None, admitted=False,
                         note="No complete fresh request binding established in this bounded observation; no production template filled.")

def save(name, value):
    with (OUT / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


component_paths = ["/usr/libexec/gcc/x86_64-linux-gnu/13/" + name
                   for name in ("cc1plus", "cc1", "collect2", "lto1", "lto-wrapper")]
unknown = {p: row for p, row in files.items() if row["native_current_content_pin"] is None}
new_roles = collections.Counter()
for path in ends:
    for role in files[path]["roles"]:
        new_roles[role] += 1
partial_rows = [row for row in files.values() if row["state"] == "unclosed_content_transfer_no_current_pin"]
stderr = (OUT / "stderr.bin").read_bytes()
try:
    stderr_text = stderr.decode("utf-16-le")
except UnicodeError:
    stderr_text = stderr.decode("utf-8", errors="replace")

summary = dict(schema="native-linux-fresh-input-summary-v1", selected=len(files),
               native_identity_status=dict(collections.Counter(row.get("status") for row in identities.values())),
               new_complete_file_observations=len(ends), new_distinct_sha_blobs=len({r["sha256"] for r in ends.values()}),
               complete_observed_payload_bytes=sum(row["bytes"] for row in ends.values()),
               actual_payload_bytes_read=result["stream_payload_bytes"], partial_transfers=len(partial_rows),
               observed_payload_roles=dict(new_roles), content_state_counts=dict(collections.Counter(row["state"] for row in files.values())),
               metadata_bytes=result["stream_metadata_bytes"], stderr_bytes=result["stderr_bytes"], stderr_text=stderr_text,
               elapsed_s=result["elapsed_s"], collection_complete=result["collection_complete"],
               stop_reason=result["linux_completion"]["reason"], parent_exit=result.get("exit"),
               readers_closed=result["readers_closed"], linux_completion=result["linux_completion"],
               prior_acquired_content_paths=len(selection["excluded"]), old_build_prefix_accessed=False,
               old_content_rehashed=False, resource_query=False, compile=False, native_target=False,
               new_request_complete=False, production_input_closure_complete=False, abi_verified=False,
               package_origin_authenticated=False, all_qualifications=False, dispatchable=False)
save("file-observations.json", dict(schema="native-linux-identity-content-observations-v1", files=files,
                                    observation_not_authentication=True, compile_time_inputs_proven=False))
save("new-file-pins.json", dict(schema="native-linux-new-read-file-pins-v1", files=new_pins,
                                acquisition_time_only=True, admitted=False))
save("binding-candidates.json", dict(schema="native-offset-fresh-input-candidates-v1", bindings=bindings,
                                     compiler_component_observations={p: files.get(p) for p in component_paths},
                                     request_schema="native-offset-fresh-source-request-v1", request_complete=False,
                                     dispatchable=False, all_qualifications=False))
save("missing-evidence.json", dict(schema="native-linux-fresh-input-missing-v1", unbound_path_count=len(unknown),
                                  unavailable_paths={p: r for p,r in identities.items() if r.get("status") != "observed"},
                                  unclosed_transfers=partial_rows,
                                  compiler_components={p: files.get(p, {}).get("state", "not_selected") for p in component_paths},
                                  missing_request_bindings=[k for k,v in bindings.items() if v["current_file_pin"] is None],
                                  limits=[
                                      "No second batch/reordered selection after the metadata cap.",
                                      "Saved package lists/old depfiles yield candidates, not current consumed compile/loader closure.",
                                      "Known prior paths and observed resolved/inode aliases excluded; unobserved hardlinks not globally established.",
                                      "Old retained content hashes remain historical; metadata identity does not refresh contents.",
                                      "All identities are per-observation, not atomic build-time snapshots or authenticated producer records.",
                                      "Original toolchain/current production/source/config/header/package/implicit/loader/ABI and fresh resource/admission requirements remain.",
                                      "No native target, compile, package signing/origin verification, resource query or production template admission."] ))
save("analysis-summary.json", summary)
print(json.dumps(summary, ensure_ascii=True))
