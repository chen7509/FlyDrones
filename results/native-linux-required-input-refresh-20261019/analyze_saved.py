"""Bind newly refreshed inputs and report the remaining build frontier without dispatch."""

import ast
import json
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
HEADERS = ROOT / "results/native-linux-build-headers-20261019"
FIVE = ROOT / "results/native-linux-compiler-five-20261019"
selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
result = json.loads((OUT / "collection-result.json").read_text(encoding="utf-8"))
metadata = (OUT / "metadata.jsonl").read_bytes()
rows = [json.loads(line) for line in metadata.splitlines()]
identities = {row["path"]: row for row in rows if row["type"] == "identity"}
ends = {row["path"]: row for row in result["observed_files"]}
selected = {row["path"]: row for row in selection["selected"]}
assert len(selected) == 166 and set(ends) <= set(selected) and set(identities) <= set(selected)
files, pins, differences = {}, {}, []
for path, item in selected.items():
    end, prior = ends.get(path), selection["prior_content_refs"][path]
    row = dict(path=path, roles=item["roles"], identity=identities.get(path), file_pin=None,
               prior_retained_field_reference=prior, state="not_completely_refreshed", admitted=False)
    if end:
        assert end["stable"] and end["before"] == end["after"]
        pin = {key: end[key] for key in ("path", "resolved", "bytes", "sha256")}
        same = pin["sha256"] == prior["sha256"] and pin["bytes"] == prior["bytes"]
        row.update(state="current_content_refreshed_not_admitted", file_pin=pin,
                   before=end["before"], after=end["after"], blob=end["blob"],
                   equals_prior_saved_sha_and_size_fields=same, old_payload_rehashed=False)
        pins[path] = pin
        if not same:
            differences.append(path)
    files[path] = row
fixed = json.loads((ROOT / "results/native-offset-run-plan-20261018/upstream-build-source-manifest.json").read_text(encoding="utf-8"))
upstream_root = "/home/yuchen7509/flydrones-upstream/open_vins/"
source_pins = {path: pin for path, pin in pins.items() if "fixed-upstream-source" in selected[path]["roles"]}
fixed_matches, fixed_differences = [], []
for path, pin in source_pins.items():
    expected = fixed["files"].get(path[len(upstream_root):])
    if expected and pin["sha256"] == expected["sha256"] and pin["bytes"] == expected["bytes"]:
        fixed_matches.append(path)
    else:
        fixed_differences.append(path)
missing_fixed = [upstream_root + name for name in fixed["files"] if upstream_root + name not in source_pins]
source_coverage = dict(schema="fixed-upstream-current-content-coverage-v1", commit=fixed["commit"],
                       required_manifest_files=len(fixed["files"]), actual_current_refreshed=len(source_pins),
                       matches_fixed_manifest_fields=len(fixed_matches), differences=fixed_differences,
                       missing_current_payload_paths=missing_fixed,
                       missing_paths_not_accessed_this_selection=True,
                       atomic_snapshot=False, old_library_history_proven=False, complete=False)
header_pins = json.loads((HEADERS / "new-file-pins.json").read_text(encoding="utf-8"))["files"]
component_pins = json.loads((FIVE / "new-file-pins.json").read_text(encoding="utf-8"))["files"]
candidate_pins = {}
for phase, phase_pins in (("results/native-linux-build-headers-20261019", header_pins),
                           ("results/native-linux-compiler-five-20261019", component_pins),
                           ("results/native-linux-required-input-refresh-20261019", pins)):
    for path, pin in phase_pins.items():
        assert path not in candidate_pins
        candidate_pins[path] = dict(phase=phase, pin=pin, admitted=False)
bindings = {}
for key, path in {"pinned_cmake":"/usr/bin/cmake", "pinned_gxx":"/usr/bin/x86_64-linux-gnu-g++-13",
                  "pinned_make":"/usr/bin/make", "pinned_python":"/usr/bin/python3.12"}.items():
    bindings[key] = dict(candidate_path=path, current_acquisition_pin=pins.get(path), admitted=False)
for key, path in {"eigen_config_dir":"/usr/share/eigen3/cmake", "opencv4_config_dir":"/usr/lib/x86_64-linux-gnu/cmake/opencv4",
                  "boost_config_dir":"/usr/lib/x86_64-linux-gnu/cmake/Boost-1.83.0", "ceres_config_dir":"/usr/lib/x86_64-linux-gnu/cmake/Ceres"}.items():
    bindings[key] = dict(candidate_path=path,
                         refreshed_config_files=[name for name in pins if name.startswith(path + "/")],
                         recursive_or_consumed_config_closure_complete=False, admitted=False)
bindings["upstream_source_tree"] = dict(candidate_path=upstream_root.rstrip("/"), coverage=source_coverage, admitted=False)
for key in ("deployed_repo", "toolchain_file", "toolchain_receipt", "header_package_manifest",
            "current_linux_source_manifest", "capture_script", "exclusive_build_dir"):
    bindings[key] = dict(current_binding=None, admitted=False,
                         reason="Not established as a complete current Linux production/request input by these observations.")
authorization = dict(schema="conversation-authorization-receipt-v1", identity_authentication=False,
                     user_reply="允许此清单一次只读复核", reviewed_path_count=169, executed_path_count=166,
                     strict_subset=True, excluded_only=[upstream_root + name for name in (".git/HEAD", ".git/refs/heads/master", ".git/packed-refs")],
                     scope="One readonly current-content refresh; no compile/native/resources/Linux writes or second selection.")
summary = dict(schema="native-linux-required-refresh-summary-v1", selected=len(selected), complete_files=len(ends),
               roles=dict(Counter(role for path in ends for role in selected[path]["roles"])),
               prior_field_matches=len(ends)-len(differences), differences=differences,
               complete_payload_bytes=sum(row["bytes"] for row in ends.values()),
               actual_payload_bytes_read=result["stream_payload_bytes"],
               metadata_frame_body_bytes=result["stream_metadata_bytes"], retained_jsonl_bytes=len(metadata),
               metadata_rows=dict(Counter(row["type"] for row in rows)), stderr_bytes=result["stderr_bytes"],
               stderr_text=(OUT / "stderr.bin").read_bytes().decode("utf-16-le"),
               parent_elapsed_s=result["elapsed_s"], parent_exit=result.get("exit"), readers_closed=result["readers_closed"],
               linux_completion=result["linux_completion"], active_partial=result["active_partial"], errors=result["errors"],
               collection_complete=result["collection_complete"],
               exact_selection_complete=bool(result["collection_complete"] and set(ends)==set(selected)),
               new_header_files=len(header_pins), previously_completed_compiler_files=len(component_pins),
               candidate_input_paths=len(candidate_pins), candidate_union_is_cross_time_not_atomic=True,
               fixed_upstream_coverage=source_coverage,
               old_saved_payload_rehashed=False, tests_run=False, cmake_modules_selected=0,
               resource_query=False, compile_or_native_target=False, linux_file_writes=False,
               stage1_complete=False, new_request_complete=False, abi_verified=False,
               all_qualifications=False, dispatchable=False)
assert len(metadata)==result["stream_metadata_bytes"]+len(rows)
assert len(metadata)<=selection["caps"]["metadata_bytes"]
assert summary["complete_payload_bytes"]==result["stream_payload_bytes"]
missing = dict(schema="native-linux-build-input-frontier-v1", build_stage_blockers=[
    dict(id="fixed-source-143", status="incomplete", actual=source_coverage),
    dict(id="deployed-current-production-source", status="unknown", note="Local software implementation exists, but a complete current Linux deployed source/capture closure is not bound here."),
    dict(id="toolchain-recipe-and-receipt", status="unknown", note="No complete current bound toolchain_file/toolchain_receipt input created or inferred."),
    dict(id="current-full-input-closure", status="incomplete", note="New headers/current16 configs and9 tools are real observations, not all CMake/config/package/implicit tool/header/link/loader consumption or signed origin proof. Earlier CMake-module evidence is not refreshed or newly consumed proof."),
    dict(id="fresh-once-build-admission", status="not_granted", note="No resource refresh, cgroup/pidfd execution or build approval inferred; preserve original budgets and consumed states.")],
    run_stage_requirements_not_build_outputs_preconditions=["Successful actual library+adapter build receipt and owned inside/host release", "New library/adapter identities and ABI/recursive-lazy-loaded closure proof", "Measured calibration/noise and actual signed source/clock/runtime/wire bindings", "Separate applicable run admission; no automatic build-to-run"],
    old_library_history_still_unknown=True, all_qualifications=False, dispatchable=False)
for name, value in {
    "file-bindings.json":dict(schema="native-linux-current-refreshed-bindings-v1", files=files, acquisition_time_only=True, admitted=False),
    "new-file-pins.json":dict(schema="native-linux-new-read-file-pins-v1", files=pins, acquisition_time_only=True, admitted=False),
    "source-coverage.json":source_coverage, "authorization-receipt.json":authorization,
    "input-candidates.json":dict(schema="native-offset-current-build-input-candidates-v1", files=candidate_pins, bindings=bindings,
                                 request_schema="native-offset-fresh-source-request-v1", request_complete=False, all_qualifications=False, dispatchable=False),
    "analysis-summary.json":summary, "missing-evidence.json":missing,
}.items():
    with (OUT / name).open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(value,stream,indent=2); stream.write("\n")
for path in OUT.glob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"),filename=path.name)
print(json.dumps(summary))
