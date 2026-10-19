"""Freeze new header candidates and a separate NOT-authorized refresh proposal."""

import ast
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
PRIOR = ROOT / "results/native-linux-fresh-input-bindings-20261019"
FIVE = ROOT / "results/native-linux-compiler-five-20261019"
prior_selection = json.loads((PRIOR / "selection.json").read_text(encoding="utf-8"))
old_files = json.loads((PRIOR / "file-observations.json").read_text(encoding="utf-8"))["files"]
five_selection = json.loads((FIVE / "selection.json").read_text(encoding="utf-8"))
five_files = json.loads((FIVE / "file-bindings.json").read_text(encoding="utf-8"))["files"]
excluded = dict(five_selection["excluded"])
excluded_ids = {tuple(pair) for pair in five_selection["excluded_native_identities"]}
for path, row in five_files.items():
    excluded[path] = dict(prior_phase=FIVE.name, saved_pin=row["file_pin"])
    excluded[row["file_pin"]["resolved"]] = excluded[path]
    excluded_ids.add((row["before"]["dev"], row["before"]["ino"]))

headers = {}
for path, row in old_files.items():
    if (row["state"] == "identity_only_content_not_acquired_in_bounded_selection"
            and "saved-old-depfile-lexical-candidate-not-new-build-read-proof" in row["roles"]
            and path.startswith(("/usr/include/", "/usr/lib/gcc/x86_64-linux-gnu/13/include/"))):
        headers[path] = ["saved-old-depfile-header-candidate-not-new-build-consumption-proof"]
assert len(headers) == 1452

# Read one saved package-list TEXT solely to choose filesystem header names required by
# the current adapter's <filesystem> include. No Linux read or old payload hash check.
package_path = next(path for path in prior_selection["excluded"]
                    if "libstdc++-13-dev" in path and path.endswith(".list"))
ref = prior_selection["excluded"][package_path]
package_local = ROOT / ref["phase"] / ref["blob"]
allowed_fs_names = {"/usr/include/c++/13/" + name for name in
                    ("filesystem", "bits/fs_fwd.h", "bits/fs_path.h", "bits/fs_dir.h", "bits/fs_ops.h")}
package_added = []
for path in package_local.read_text(encoding="utf-8").splitlines():
    if path in allowed_fs_names and path not in excluded:
        headers.setdefault(path, []).append("saved-package-list-exact-filesystem-candidate-not-consumed-proof")
        package_added.append(path)

def priority(path):
    if path in allowed_fs_names:
        return 0
    if path.startswith(("/usr/include/c++/13/", "/usr/include/x86_64-linux-gnu/c++/13/",
                        "/usr/lib/gcc/x86_64-linux-gnu/13/include/")):
        return 1
    if path.startswith(("/usr/include/eigen3/", "/usr/include/ceres/", "/usr/include/opencv4/")):
        return 2
    if not path.startswith("/usr/include/boost/"):
        return 3
    return 4

paths = sorted(headers, key=lambda path: (priority(path), path))
assert len(paths) <= prior_selection["caps"]["selected_paths"]
assert not set(paths) & set(excluded)
for path in paths:
    identity = old_files.get(path, {}).get("identity")
    if identity and identity.get("status") == "observed":
        assert (identity["stat"]["dev"], identity["stat"]["ino"]) not in excluded_ids
selection = dict(schema="native-linux-new-build-headers-selection-v1",
                 source_head="5faf360249eea4b2ee17878f27a6c3f23f54a61a",
                 authorization="Human requested proceeding in order; current stage is read-only missing input bindings, preserving no-reacquisition/no-build/no-native/no-resource constraints.",
                 selected=[dict(path=path, roles=headers[path]) for path in paths],
                 allowed_content_endpoints=paths, excluded=excluded,
                 excluded_native_identities=[list(pair) for pair in sorted(excluded_ids)],
                 forbidden_prefixes=prior_selection["forbidden_prefixes"], caps=prior_selection["caps"],
                 package_list_planning_ref=dict(path=package_path, retained_reference=ref,
                                                use="exact path planning only, no old rehash"),
                 package_filesystem_candidates=package_added,
                 prior_depfile_header_candidates=1452, cmake_modules_selected=0,
                 directory_search=False, old_payload_rehash=False, resource_query=False,
                 compile=False, all_qualifications=False, dispatchable=False)
with (OUT / "selection.json").open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(selection, stream, indent=2)
    stream.write("\n")
for name in ("linux_reader.py", "run_collection.py"):
    source = (FIVE / name).read_text(encoding="utf-8")
    source = source.replace("exact five", "frozen header selection").replace("exact-five", "headers")
    source = source.replace("native-linux-compiler-five-readonly-parent-v1", "native-linux-build-headers-readonly-parent-v1")
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(source)
    ast.parse(source, filename=name)

# A concrete reviewable proposal only. It is not passed to the collector.
tool_paths = {"/usr/bin/cmake", "/usr/bin/x86_64-linux-gnu-g++-13", "/usr/bin/make", "/usr/bin/python3.12",
              "/usr/bin/env", "/usr/bin/time", "/usr/bin/timeout", "/usr/bin/systemd-run", "/usr/bin/systemctl"}
config_dirs = ("/usr/share/eigen3/cmake/", "/usr/lib/x86_64-linux-gnu/cmake/opencv4/",
               "/usr/lib/x86_64-linux-gnu/cmake/Boost-1.83.0/", "/usr/lib/x86_64-linux-gnu/cmake/Ceres/")
source_prefix = "/home/yuchen7509/flydrones-upstream/open_vins/"
refresh = {}
for path, record in prior_selection["excluded"].items():
    role = ("required-tool" if path in tool_paths else
            "required-package-config" if path.startswith(config_dirs) else
            "fixed-upstream-source" if path.startswith(source_prefix) and "/build/" not in path else None)
    if role:
        refresh[path] = dict(role=role, prior_retained_observation=record,
                             current_content_pin=None, authorization=False)
proposal = dict(schema="native-linux-required-input-refresh-PROPOSAL-v1", authorized=False,
                execution_forbidden_until_human_changes_no_reacquisition_constraint=True,
                reason="Current native identity cannot refresh previously retained content hashes; human's no-reacquisition restriction still applies.",
                paths=refresh, count=len(refresh), saved_size_estimate=sum(r["prior_retained_observation"]["bytes"] for r in refresh.values()),
                scope_tools_without_saved_content_reference=sorted(tool_paths - set(refresh)),
                caps=prior_selection["caps"], no_directory_search=True, no_compile=True,
                no_native_target=True, no_resource_refresh=True, no_linux_writes=True,
                not_in_header_collector_selection=True, no_automatic_second_batch=True,
                missing_LICENSE_ReadMe_not_retried=True, all_qualifications=False, dispatchable=False)
with (OUT / "required-input-refresh-PROPOSAL.json").open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(proposal, stream, indent=2)
    stream.write("\n")
print(json.dumps(dict(header_selection_count=len(paths), prior_depfile_candidates=1452,
                     additional_filesystem_paths=package_added, cmake_modules=0,
                     refresh_proposal_count=len(refresh), refresh_proposal_saved_bytes=proposal["saved_size_estimate"],
                     refresh_proposal_authorized=False, excluded_paths=len(excluded),
                     excluded_inode_pairs=len(excluded_ids), linux_access=False)))
