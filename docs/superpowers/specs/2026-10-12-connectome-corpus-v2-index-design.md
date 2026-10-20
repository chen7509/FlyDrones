# Connectome corpus v2 index design

## Purpose and boundary

The declared six-stage corpus has exactly 54 jobs. The v1 curriculum's seed
counts cannot express three independent rollouts per world. Add an offline v2
index consumer that binds each declared `(stage_id, split, world_seed,
rollout_seed, ordinal)` to one immutable world and one v3 sequence, plus a
run-specific evidence receipt. This is necessary for complete MaleCNS learning
but does not certify that the files were produced by real PX4, a calibrated
camera or the pinned EGO process. The consumer must never grant training or
flight eligibility by itself.

## Input contract

The top-level JSON has exact keys `schema`, `corpus_digest`, and `records`.
`schema` is `flydrones-connectome-corpus-index-v1`; `corpus_digest` equals the
already validated `CorpusConfig.digest`. The 54 records appear in the exact
order of `CorpusConfig.jobs()`. Each record has exact fields `job` (all five
`CorpusJob` fields), `run_id`, `terminal`, `sequence_dir`,
`sequence_manifest_sha256`, `world_json`, `world_sha256`, `receipt_path`, and
`receipt_sha256`. `run_id` is a nonempty unique lowercase UUID-hex identity;
`terminal` must be `success`. Relative paths must be normalized, confined to
`CorpusConfig.output_root`, regular files/directories with no symlink in any
existing path component. Distinct records may not reuse resolved sequence,
world or receipt files, nor a sequence samples hash.

The world JSON bytes must match the canonical output of
`build_corpus_world(job)` and the recorded SHA. The sequence manifest must be
v3, match its recorded SHA, pass `load_sequence` including sample hash and
shape checks, and contain provenance with this job's split, world seed, world
hash, benchmark-config hash, exact `ego@<pinned commit>` teacher, and
`px4-ekf2-calibrated-camera-v1` source label. The receipt is an exact JSON
mapping with schema `flydrones-connectome-capture-receipt-v1`, run/job
identity, the sequence/world hashes, pinned EGO commit/image, exact source
labels, and SHA-256 identities of a separate ULog, source journal, teacher
inspection and calibration file. The consumer checks those referenced file
bytes and confines them to the same run directory. It does not interpret their
contents as source authentication. No missing, repeated, extra, failed or
stale entry is silently skipped.

## Output and safety

Return an immutable integrity audit containing the 54 job keys, per-job
sequence path and hashes, and a digest over all verified identities. Mark
`source_authenticated=false`, `training_eligible=false` and
`eligible_for_fair_comparison=false` regardless of structural success. Do not
expose a trainable dataset from this API. A future independently verified
producer must bind actual PX4 sample/publication/receipt and reset health,
camera calibration/time, EGO process/reference, ULog and failed-run ledger
before training can consume sequences. Preserve existing v1 smoke/curriculum
and formal held-out evidence unchanged.

## Verification

Synthetic fixtures may exercise complete 54-job indexing, order, content
hashes and refusal of missing/extra/duplicate/relabelled/tampered/failed
records and path escapes. Such fixtures are labelled synthetic and never
qualify capture. Run focused tests, connectome regression, Ruff and diff check;
archive failures and reviewed source. Do not launch PX4, Gazebo, Docker EGO,
full MaleCNS or a benchmark.
