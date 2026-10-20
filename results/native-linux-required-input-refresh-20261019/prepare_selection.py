"""Freeze the authorized strict subset of the reviewed169-path refresh proposal."""

import ast
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
HEADERS = ROOT / "results/native-linux-build-headers-20261019"
OLD = ROOT / "results/native-linux-fresh-input-bindings-20261019"
proposal = json.loads((HEADERS / "required-input-refresh-PROPOSAL-v2.json").read_text(encoding="utf-8"))
reviewed = json.loads((HEADERS / "required-input-refresh-PROPOSAL.json").read_text(encoding="utf-8"))
headers = json.loads((HEADERS / "selection.json").read_text(encoding="utf-8"))
old_files = json.loads((OLD / "file-observations.json").read_text(encoding="utf-8"))["files"]
new_headers = json.loads((HEADERS / "file-bindings.json").read_text(encoding="utf-8"))["files"]
paths = list(proposal["paths"])
assert len(paths) == 166 and set(paths) < set(reviewed["paths"])
assert not any("/.git/" in path for path in paths)
excluded = dict(headers["excluded"])
excluded_ids = {tuple(pair) for pair in headers["excluded_native_identities"]}
allowed_endpoints, prior_content_refs, allowed_ids = set(paths), {}, set()
for path in paths:
    identity = old_files.get(path, {}).get("identity")
    assert identity and identity.get("status") == "observed"
    allowed_endpoints.add(identity["resolved"])
    allowed_ids.add((identity["stat"]["dev"], identity["stat"]["ino"]))
    prior_content_refs[path] = proposal["paths"][path]["prior_retained_observation"]
for path in allowed_endpoints:
    excluded.pop(path, None)
excluded_ids -= allowed_ids
for path, row in new_headers.items():
    assert row["file_pin"] is not None
    excluded[path] = dict(prior_phase=HEADERS.name, saved_pin=row["file_pin"])
    excluded[row["file_pin"]["resolved"]] = excluded[path]
    excluded_ids.add((row["before"]["dev"], row["before"]["ino"]))
assert not set(paths) & set(excluded)
selection = dict(schema="native-linux-authorized-required-refresh-selection-v1",
                 source_head="5faf360249eea4b2ee17878f27a6c3f23f54a61a",
                 human_authorization="Allows the reviewed169-path list once for readonly current-content refresh, without compile/native/resource/Linux writes; this166-path selection is a strict subset excluding3 Git metadata files.",
                 reviewed_proposal="results/native-linux-build-headers-20261019/required-input-refresh-PROPOSAL.json",
                 narrowed_proposal="results/native-linux-build-headers-20261019/required-input-refresh-PROPOSAL-v2.json",
                 selected=[dict(path=path, roles=[proposal["paths"][path]["role"]]) for path in paths],
                 allowed_content_endpoints=sorted(allowed_endpoints), excluded=excluded,
                 excluded_native_identities=[list(pair) for pair in sorted(excluded_ids)],
                 prior_content_refs=prior_content_refs, forbidden_prefixes=headers["forbidden_prefixes"],
                 caps=headers["caps"], stop_after_first_observed_content_difference=True,
                 cmake_modules_selected=0, directory_search=False, old_payload_rehash=False,
                 resource_query=False, compile=False, linux_file_writes=False,
                 all_qualifications=False, dispatchable=False)
with (OUT / "selection.json").open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(selection, stream, indent=2)
    stream.write("\n")
reader = (HEADERS / "linux_reader.py").read_text(encoding="utf-8")
old = '                      sha256=digest.hexdigest(), stable=True))'
new = old + ('\n            expected = selection["prior_content_refs"][path]\n'
             '            if digest.hexdigest() != expected["sha256"] or size != expected["bytes"]:\n'
             '                raise Stop("current content differs from saved fields: " + path + "; stop without replacement")')
assert reader.count(old) == 1
reader = reader.replace(old, new).replace("frozen header selection", "authorized frozen refresh selection")
with (OUT / "linux_reader.py").open("x", encoding="utf-8", newline="\n") as stream:
    stream.write(reader)
parent = (HEADERS / "run_collection.py").read_text(encoding="utf-8")
parent = parent.replace("native-linux-build-headers-readonly-parent-v1", "native-linux-required-refresh-readonly-parent-v1")
with (OUT / "run_collection.py").open("x", encoding="utf-8", newline="\n") as stream:
    stream.write(parent)
for name in ("prepare_selection.py", "linux_reader.py", "run_collection.py"):
    ast.parse((OUT / name).read_text(encoding="utf-8"), filename=name)
print(json.dumps(dict(selected=len(paths), known_resolved_endpoints=len(allowed_endpoints),
                     roles={role:sum(role in item["roles"] for item in selection["selected"])
                            for role in sorted({role for item in selection["selected"] for role in item["roles"]})},
                     saved_size_estimate=proposal["saved_size_estimate"], excluded_paths=len(excluded),
                     excluded_inode_pairs=len(excluded_ids), linux_access=False)))
