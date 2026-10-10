# Curriculum corpus selection diagnostic and duplicate-path fix

Date: 2026-10-09. Base 5ac5b94; fix 64c804f. Scope: offline data selection only.

## Outcome

The legacy curriculum loader no longer loads the same resolved sequence directory
twice. It rejects repeated paths, overlapping parent/child directory selections
and resolved aliases before reading sequence samples. Distinct directories retain
the original requested order and the original sorted recursive discovery order.

This closes one real selection defect; it does not bind or qualify the planned
v2 physical corpus. No full model, teacher, training job or simulation was run.
Unit tests exercise synthetic small models where the existing connectome suite
requires them; those are not a new training campaign or full-model measurement.
The separate live-wire scope question remains unanswered and its actual launch
was not attempted.

## Reproduced evidence

`results/curriculum-corpus-binding-audit-dev-1701/audit.json` records an actual
call to the production `_full_components` loader using retained synthetic files.
It stops naturally at the deliberately absent connectome-file check, before
parameter loading, model construction or training. A read-only trace observer
records its local dataset counts at that exception; it does not modify state or
substitute a loader.

- The declared v2 corpus has 54 jobs: six stages, three world seeds per stage
  partitioned as two train/one validation, three rollouts per world.
- All 12 configured v1 stage/split paths are outside the declared v2 output root.
- Eighteen synthetic sequences, one per world, passed the legacy loader's data
  checks and reached the missing-model guard.
- Selecting those same 18 files three times produced 54 loaded entries and also
  reached the missing-model guard. They were not 54 independent physical runs.
- These deliberately unverified teacher/source labels were accepted by the
  legacy checks. `SequenceProvenance` has split, seed, teacher, world hash,
  config hash and source, but no explicit stage or rollout ID.

The initial diagnostic replaced paths in the immutable config dataclass while
retaining its original digest. It explicitly does **not** claim that this is a
new valid configuration identity or a completed CLI training run. After the fix,
`verify_fixed_selection.py` wrote a separate synthetic YAML configuration, loaded
it through the actual config parser with a new digest, and confirmed that the
actual loader rejected duplicate selection before the missing-model guard.
All original fixture bytes remained unchanged. Both diagnostic outcomes are kept.

These findings concern the insufficiency of the legacy route for the planned v2
corpus. The v1 format never promised a 54-job corpus seal. Changing its paths
alone would not supply the missing source, teacher or per-rollout evidence.

## Implementation and verification

The production change is six lines in `curriculum_session._sequence_directories`:
resolve each selected directory strictly, reject a repeated identity, then load
the original ordered paths. Existing dataset loading and hashing are reused;
there is no new algorithm, upstream dependency, calibration or research claim.
The diagnosis uses the existing v1 curriculum, v2 corpus spec/config and current
source implementations. No lookup, deduplication or teacher implementation is
invented from an external project name.

Three behavioral assertion tests first failed for repeated paths, parent/child
overlap and lexical aliases; three other cases passed and one Windows symlink
case skipped. After the fix the complete connectome test directory passed
**220 tests, with 1 skip and 1 existing sparse-checkpoint warning in 104.28 s**.
Changed-file Ruff and `git diff --check` passed. Independent read-only review
found no Critical, Important or Minor findings. No necessary extra test was
identified. The entire repository suite was not repeated for this local loader
change; the previous 3,977-pass result belongs to the preceding wire-entry stage.

Path uniqueness does not prove content uniqueness or independent jobs. Two
different directories with identical content are still accepted; that boundary
is tested explicitly. Symlink rejection was not verified on this Windows host
because creation lacked permission. Ordinary path resolution is not atomic or
hostile-race protection. Cross-stage and complete corpus identity still need
their own binding.

## Next dependency

Keep v1 smoke and its checkpoint/config identities unchanged. A separate v2
consumer must bind the exact six-stage 54-job declaration and each
`(stage, split, world_seed, rollout_seed)` to a sealed successful sequence, teacher
commit/image evidence, observation-source evidence and immutable file hashes.
It must reject missing/repeated/extra jobs and preserve failed capture records;
it must not qualify a dataset because its directory count happens to be 54.
The v2 curriculum needs versioned data paths and a distinct resume identity.
There is no verified physical corpus to use yet. Non-truth state production,
camera calibration and teacher availability remain prerequisites for collection.

The initial host observation this turn found 1,455,837,184 available bytes, below
the unchanged 4,294,967,296-byte full inference gate, no matching test/estimator/
simulator process and no running WSL distribution. Docker service was Stopped;
the fixed teacher image was not inspected. No model retry or service start was
attempted. These are current observations, not permanent hardware infeasibility.

Full learning/division, inference timing, fair physical comparison, five/20-aircraft
and hardware/flight evidence remain incomplete. The five-camera 0.873 RTF result
still fails the 0.95 gate.

## Evidence seal

`evidence/curriculum-corpus-binding-audit-dev-1701.zip` has 57 members and 59,615
bytes; SHA256 `ee9e98f6424d8cfa45bbb388346d0de36577251537f40c4b6d0345168af889ed`.
All member bytes/hashes and ZIP CRC were verified. It keeps the original accepted
duplicate diagnostic, immutable synthetic fixtures, fixed public-config refusal,
RED/GREEN logs, review and source/config/report copies at 64c804f. The old loader
was recovered from Git 5ac5b94 with working-tree newline conversion and matched
the exact pre-fix audit hash; it is not represented as a source copy made before
that run. This seal paragraph and commit identifier were added afterward.

The independent training-module change is absent from the v5 wire binding. All
228 Windows-accessible worktree files selected by that binding still match its
hashes; actual activation outputs remain absent and the selected manifest SHA
remains 419950ff5e5c3a59422acfd473f04cfb171c35a5660969b071a61bcf0f0e9395.
Linux installed identities were not rechecked. Final host filtering found no
matching test/model/simulator process. Changes are local; no publication claimed.
