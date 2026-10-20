# Connectome depth validity design (2026-10-09)

## Intent and observed gap

The future MaleCNS training corpus must retain camera-visible depth without inventing a distance for missing returns. The current benchmark gateway converts samples below 0.2 m, above 19.1 m, and non-finite samples to `NaN` in `src/flydrones/benchmark/gateway.py`. Existing sequence v1/v2 files require every `depth_m` value to be finite; `frame_features()` also requires every value to be positive and finite. A normal normalized frame containing a missing pixel therefore cannot enter the corpus. This is a contract mismatch, not evidence that a real training rollout has failed; no deployment-visible student capture producer exists yet.

ROS [REP 118](https://reps.openrobotics.org/rep-0118/) specifies floating-point depth in meters and refers non-finite meanings to [REP 117](https://reps.openrobotics.org/rep-0117/). REP 117 distinguishes invalid (`NaN`), out of range (`+Inf`), and too close (`-Inf`). Our gateway currently collapses several conditions to `NaN`, so the corpus must call them **invalid after normalization** and cannot reconstruct their original cause. Neither a fake maximum range nor a Gazebo truth label is an acceptable replacement.

## Chosen contract

Introduce `flydrones-connectome-sequence-v3` as an opt-in extension of v2. Each frame stores the existing normalized `depth_m` float32 array and a same-shape boolean `depth_valid` mask. `depth_valid` is true exactly where normalized depth is finite and greater than zero. This rule verifies the persisted pair without needing hidden simulator state; a future source with a different range must normalize against its own declared sensor range before recording. A wholly invalid frame remains recordable evidence but cannot silently become a trainable all-clear observation. The v3 archive retains `teacher_horizon_valid` from v2 and includes the new mask in the hashed NPZ. Mixed masked/unmasked frames, a mismatching mask, malformed geometry, or a v3 target lacking horizon validity fail before writing.

Legacy v1/v2 byte formats, load behavior, 12-feature adapter and parameter artifacts remain unchanged. The v3 loader can restore the raw normalized depth and mask, but existing `frame_features()` and training entry points must explicitly reject v3 pending a separately versioned mask-aware feature adapter and parameter mapping. A later adapter should expose both depth and per-sector coverage so an unknown sector cannot be interpreted as verified clear space. Its feature count, full-connectome input-neuron mapping, safety gate, and training artifacts require separate tests and new identities; no old checkpoint gains v3 authority by loading a new sequence.

The teacher bridge still consumes the original 32FC1 observation. V3 affects only student-corpus storage; it does not authorize EGO synthetic smoke output, truth-derived benchmark odometry, PX4 injection, model training, or 5/20-drone promotion. Real capture must separately prove PX4 EKF2 state, calibrated camera pose, pinned teacher output, time alignment, source health, and failure retention through the existing capture gate.

## Alternatives considered

Replacing `NaN` with the far clip distance was rejected because it would present an invalid measurement as observed free space. Allowing non-finite depth in v2 without a mask was rejected because old readers and 12-feature models would silently inherit new semantics. A single generic validity flag was rejected because it cannot locate missing pixels. Rebuilding the entire sensor pipeline to preserve REP 117 categories is valuable later, but current gateway has already collapsed categories; this stage must not claim that information exists.

## Verification and limits

The storage stage needs v1/v2 round-trip regression, v3 NaN round-trip with exact mask, mutation rejection for mask shape/dtype/content, mixed frame modes, missing v2 horizon mask, hash tampering, all-invalid frame retention, and explicit refusal by the old feature extractor. The subsequent capture stage must prove the mask comes from the same normalized frame and is not filled with truth. Mask-aware feature/training behavior requires its own design, failure tests, artifact identity, and physical sensor cohort; until then v3 is archival, not trainable.
