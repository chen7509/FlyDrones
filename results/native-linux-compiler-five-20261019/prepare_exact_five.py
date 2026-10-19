"""Freeze the human-authorized five paths using saved derived exclusions only."""

import ast
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
PRIOR = OUT.parent / "native-linux-fresh-input-bindings-20261019"
selection = json.loads((PRIOR / "selection.json").read_text(encoding="utf-8"))
files = json.loads((PRIOR / "file-observations.json").read_text(encoding="utf-8"))["files"]
paths = ["/usr/libexec/gcc/x86_64-linux-gnu/13/" + name
         for name in ("cc1plus", "cc1", "collect2", "lto1", "lto-wrapper")]
excluded = dict(selection["excluded"])
excluded_ids = set()
for path, row in files.items():
    if row["state"] not in {
        "native_identity_only_prior_payload_excluded_current_content_unknown",
        "new_saved_content_with_native_descriptor_and_link_observation_not_admitted",
        "unclosed_content_transfer_no_current_pin",
    }:
        continue
    identity = row.get("identity")
    ref = dict(prior_phase=PRIOR.name, state=row["state"],
               saved_pin=row.get("native_current_content_pin"))
    excluded.setdefault(path, ref)
    if identity and identity.get("status") == "observed":
        excluded.setdefault(identity["resolved"], ref)
        excluded_ids.add((identity["stat"]["dev"], identity["stat"]["ino"]))
for path in paths:
    assert files[path]["state"] == "identity_only_content_not_acquired_in_bounded_selection"
    assert path not in excluded
    pin = files[path]["identity"]["stat"]
    assert (pin["dev"], pin["ino"]) not in excluded_ids
frozen = dict(schema="native-linux-compiler-exact-five-selection-v1",
              source_head="b204826f60b92eb570b1c3dc020254b442b75ca3",
              selected=[dict(path=path, roles=["explicit-human-authorized-compiler-component"]) for path in paths],
              allowed_content_endpoints=paths, excluded=excluded,
              excluded_native_identities=[list(key) for key in sorted(excluded_ids)],
              forbidden_prefixes=selection["forbidden_prefixes"], caps=selection["caps"],
              prior_derived_refs=[str((PRIOR / name).relative_to(OUT.parents[1])).replace("\\", "/")
                                  for name in ("selection.json", "file-observations.json")],
              prior_partial_also_excluded=True, directory_search=False,
              old_payload_rehash=False, resource_query=False, compile=False,
              dispatchable=False, all_qualifications=False)
with (OUT / "selection.json").open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(frozen, stream, indent=2)
    stream.write("\n")
reader = (PRIOR / "linux_reader.py").read_text(encoding="utf-8")
old = "identities, excluded_ids, new_ids = {}, set(), set()"
new = "identities, excluded_ids, new_ids = {}, {tuple(key) for key in selection['excluded_native_identities']}, set()"
assert reader.count(old) == 1
reader = reader.replace(old, new)
old = '        fd = os.open(endpoint, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)'
new = ('        if endpoint not in selection["allowed_content_endpoints"]:\n'
       '            raise Stop("endpoint outside exact five; no content read or replacement")\n' + old)
assert reader.count(old) == 1
reader = reader.replace(old, new)
old = '            emit(dict(type="skip", path=path, resolved=endpoint, reason="64MiB file cap", bytes=pin["bytes"]))\n            continue'
new = '            raise Stop("64MiB file cap; stop exact five without refill")'
assert reader.count(old) == 1
reader = reader.replace(old, new)
with (OUT / "linux_reader.py").open("x", encoding="utf-8", newline="\n") as stream:
    stream.write(reader)
parent = (PRIOR / "run_collection.py").read_text(encoding="utf-8")
parent = parent.replace('schema="native-linux-fresh-readonly-parent-v1"',
                        'schema="native-linux-compiler-five-readonly-parent-v1"')
with (OUT / "run_collection.py").open("x", encoding="utf-8", newline="\n") as stream:
    stream.write(parent)
for name in ("prepare_exact_five.py", "linux_reader.py", "run_collection.py"):
    ast.parse((OUT / name).read_text(encoding="utf-8"), filename=name)
print(json.dumps(dict(selected=paths, saved_exclusion_spellings=len(excluded),
                     saved_excluded_inode_pairs=len(excluded_ids), caps=frozen["caps"],
                     helper_ast_only=True, linux_access=False)))
