"""Freeze existing-record path candidates; never accesses Linux or rehashes old payloads."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = "results/native-linux-file-receipts-20261018"
PHASES = [BASE, "results/openvins-build-provenance-20261018", "results/openvins-remaining-objects-20261018",
          "results/openvins-eight-objects-20261018", "results/openvins-final-two-objects-20261018"]


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


excluded = {}
for phase in PHASES:
    filename = "file-bindings-v2.json" if phase in (BASE, PHASES[-1]) else "file-bindings.json"
    for name, row in read(phase + "/" + filename)["files"].items():
        if row.get("sha256") and row.get("bytes") is not None:
            blob = row.get("blob") or row.get("saved_blob")
            excluded[name] = dict(phase=phase, bytes=row["bytes"], sha256=row["sha256"], blob=blob)

blocked = "/home/yuchen7509/flydrones-upstream/open_vins/ov_msckf/build"
selected = {}


def add(path, role):
    if not path.startswith("/") or path == blocked or path.startswith(blocked + "/") or "/.git/" in path:
        return
    path = path.replace("\uf03a", ":")
    selected.setdefault(path, []).append(role)


current = read(BASE + "/current-files.json")
# Native identities for old regular inputs precede all new reads: exclude inode aliases too.
for path in excluded:
    add(path, "prior-payload-identity-only")
for path, row in current.items():
    if set(row.get("roles", [])) & {"tool", "compiler-component", "dependency-cmake-config", "elf-candidate"}:
        add(path, "previous-selection-unresolved-or-observed")

package_list_refs = []
for path, row in read(BASE + "/file-bindings-v2.json")["files"].items():
    if "package-inventory" not in row.get("roles", []) or not path.endswith(".list"):
        continue
    # Saved package list text is planning metadata, not a re-verification of its payload.
    lines = (ROOT / BASE / row["blob"]).read_text(encoding="utf-8").splitlines()
    for name in lines:
        if name.endswith(("/cc1", "/cc1plus", "/collect2", "/lto1", "/lto-wrapper")):
            add(name, "saved-package-list-compiler-component")
    if path.endswith("/cmake-data.list"):
        for name in lines:
            if "/Modules/" in name and name.endswith(".cmake"):
                add(name, "saved-cmake-data-package-module-candidate-not-consumed-proof")
    package_list_refs.append(path)

for name in read("results/openvins-build-provenance-20261018/dependency-path-index.json")["paths"]:
    if name.startswith(("/usr/", "/lib/")):
        add(name, "saved-old-depfile-lexical-candidate-not-new-build-read-proof")

for name in ("/usr/bin/gmake", "/usr/share/eigen3/cmake", "/usr/lib/x86_64-linux-gnu/cmake/opencv4",
             "/usr/lib/x86_64-linux-gnu/cmake/Boost-1.83.0", "/usr/lib/x86_64-linux-gnu/cmake/Ceres",
             "/home/yuchen7509/flydrones-upstream/open_vins/LICENSE",
             "/home/yuchen7509/flydrones-upstream/open_vins/ReadMe.md"):
    add(name, "fresh-request-required-path")

aliases = dict(excluded)
for name, row in excluded.items():
    if "\uf03a" in name:
        aliases[name.replace("\uf03a", ":")] = dict(row, conservative_projection_exclusion=True)

value = dict(schema="native-linux-fresh-input-selection-v1", source_head="5cf6c6c2e95fb40d02379fc988470dd25c47dcad",
             selected=[dict(path=p, roles=roles) for p, roles in selected.items()], excluded=aliases,
             prior_distinct_acquired_paths=len(excluded), conservative_exclusion_paths=len(aliases),
             forbidden_prefixes=[blocked], package_list_planning_refs=package_list_refs,
             caps=dict(file_bytes=67108864, total_payload_bytes=201326592, read_seconds=27,
                       parent_wait_seconds=30, terminate_seconds=5, kill_seconds=5, outer_seconds=45,
                       metadata_bytes=2097152, stderr_bytes=2097152, selected_paths=6000, symlink_hops=40),
             directory_search=False, old_payload_rehash=False, resource_query=False, compile=False,
             dispatchable=False, all_qualifications=False)
if len(selected) > 6000:
    raise ValueError("selection exceeds original path bound; no collection")
with (OUT / "selection.json").open("x", encoding="utf-8") as stream:
    json.dump(value, stream, indent=2, ensure_ascii=True)
print(json.dumps(dict(selected=len(selected), prior_excluded=len(excluded), conservative_excluded=len(aliases))))
