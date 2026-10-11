# Curriculum sequence cardinality guard

Date: 2026-10-12. Scope: legacy v1 full MaleCNS curriculum data preflight.

The full curriculum now requires exactly one loaded sequence for every
configured stage/split world seed. Previously it compared seed *sets*; a
second directory labelled `stability/train/1101` alongside valid `1101` and
`1102` entries passed that check. The new count check rejects the duplicate
before loading the large parameter artifact or connectome. A valid selection
still reaches the deliberately absent connectome-file guard. The smoke path and
the order of valid sequence selection are unchanged.

The behavior was reproduced with a separate, parser-loaded synthetic curriculum
configuration and sequence files. Before the fix, the duplicate selection
reached `FileNotFoundError: connectome source does not exist`; after the fix it
raises `ValueError: stage stability requires exactly one sequence per training
seed`. The valid control reaches the missing-connectome error in both versions.
An initial test invocation omitted `PYTHONPATH` and could not import the package;
that invocation is not counted as a behavioral RED result.

Focused validation: 8 passed, 1 Windows symlink-permission skip. With
`PYTHONPATH=src;.` the connected `tests/connectome_training` suite passed:
**514 passed, 1 skipped, 2 existing PyTorch warnings**. An earlier run with
`PYTHONPATH=src` alone had 512 passed, 1 skipped and two unrelated inference
subprocess failures because those subprocesses could not import the repository
root `tools` package. Both failed cases passed when the root was included, and
the complete suite then passed. Changed-file Ruff and `git diff --check` passed.
The complete-suite count is from the interactive command output and was not
captured as a file in the nine-member archive; the focused result, Ruff and
diff-check logs are archived. Independent read-only review found no Critical or
Important findings and identified the original spec/plan wording error, now
corrected in this live report's companion documents.

This is a v1 cardinality fix only. It does not prove that different directories
contain different samples or independent physical rollouts, nor does it bind
the v2 declaration's 54 `(stage, split, world_seed, rollout_seed)` jobs to
capture, teacher, PX4 or calibrated-camera evidence. There is still no
qualified physical corpus, full MaleCNS training, full-model inference timing
or fair physical baseline result. The separate v2 consumer/provenance binder
remains the next training dependency. Existing failed physical and five-camera
capacity evidence is unchanged.

The frozen local archive
`evidence/curriculum-sequence-cardinality-dev-1701.zip` has 9 members and
SHA-256 `13906575f1cf78ece88e0bd1c369c955f6eca087d8721cf909f8021b7365b9e9`.
Its member hashes and ZIP CRC were checked. The archived report is the version
before this seal paragraph; `results/curriculum-cardinality-dev-1701/seal.json`
records the outer archive digest. No old evidence was overwritten.

After independent review, the corrected spec/plan and report were sealed in
`evidence/curriculum-sequence-cardinality-dev-1701-v2.zip` (9 members,
SHA-256 `a367107fc6226e94fb7259e17000740c5610deb820407aa1140292843c9a62b5`).
Member hashes and CRC passed; `seal-v2.json` records the digest. The v2 archive
contains the report before this final paragraph. The v1 archive remains intact.
