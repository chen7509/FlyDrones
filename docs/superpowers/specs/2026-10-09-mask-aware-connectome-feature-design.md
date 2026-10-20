# Mask-aware connectome input profile (2026-10-09)

## Purpose and boundary

The checked EGO recorder can write v3 frames with a truthful per-pixel depth-validity mask, but `frame_features()` and the existing 12-input learner refuse those frames. The next required training input is a **separate, version-bound feature profile**, not a silent reinterpretation of the old weights. This work cannot qualify any corpus, trained policy, flight, or fair comparison: there is still no non-truth PX4 EKF2/camera capture producer, and host free RAM is below the full MaleCNS probe gate.

## Research and choice

[Uhrig et al., *Sparsity Invariant CNNs*](https://arxiv.org/abs/1708.06500) identify the missing-data location as material to sparse-depth processing. Two candidate codebases were checked on 2026-10-09:

| Candidate | Version, license, maintenance | Interface / resource / adaptation | Decision |
| --- | --- | --- | --- |
| [Sparse-to-Dense PyTorch](https://github.com/fangchangma/sparse-to-dense.pytorch) | `10efc6d60bddedd6f28f0532c108bb1d7ccdfc49`; GitHub has no detected license; non-archived, last push 2019-04-01 | Legacy PyTorch 0.4 RGB-D completion network; new training, weights, GPU budget, and inferred depths | Reject: uncertain reuse rights and completion would turn missing measurements into unverified distances. |
| [SparseDC](https://github.com/WHU-USI3DV/SparseDC) | `0694bb130d9f6d130d6327f79b514786d6e44956`; Apache-2.0; non-archived, last push 2024-08-20 | Separate learned depth-completion stack and dataset adaptation, likely materially more memory/compute than a 15-number reduction | Reject for this stage: no measured benefit or validated completion model on the target camera. |

Use the repository's existing NumPy/Torch reduction. This is a local interface design informed by sparse-depth literature, not a reproduction of either network or a claim of equivalent accuracy.

## Data and version contract

Keep `FEATURE_NAMES` and `frame_features(frame)` for legacy v1/v2 byte-for-byte behavior. Add an explicit `depth-mask-v3` profile with 15 ordered features: three sector inverse-depth medians, then three sector valid-pixel fractions, then the nine unchanged luminance, velocity, yaw-rate and goal features. Each sector median uses **only** `depth_valid=true` pixels. An empty sector contributes inverse depth 0 and valid fraction 0; a wholly invalid image is retained by the archive as failure evidence but refused by the learner. Fraction is valid pixels divided by that sector's full pixel count. Never interpolate or complete missing depth. Direct v3 extraction requires float32 depth, boolean exact-shape mask equal to `isfinite(depth) & (depth>0)`, uint8 matching RGB, no infinite/zero/negative depth, and finite state.

The profile is selected by an exact ordered feature-name tuple in the parameter artifact. A v3 parameter mapping must assign **all 15** features to at least one neuron; it may contain additional assignments but may not omit a validity channel. The v3 mapping digest binds the ordered names and a version tag before existing mapping arrays. Legacy mapping digests, model identities and checkpoint format remain unchanged. The resulting curriculum model identity, checkpoint validation, inference artifact and controller all use the same selected profile and reject v1/v3 mismatches. Synthetic smoke stays legacy unless separately named and designed. Training and validation sequences within a full curriculum must match the one selected profile before model construction.

## Verification and limitations

RED/GREEN tests must cover one missing sector, partial sector, all-invalid refusal, mismatched masks, non-finite depth/state, unchanged v1/v2 features and identity, v3 mapping coverage, checkpoint/profile mismatch, and tiny-core training/inference parity. Run targeted tests, changed-file Ruff, diff check and the full repository suite. Use only synthetic v3 fixtures; no Docker, PX4/Gazebo, EGO teacher or full 166,700-neuron run. Retain every failure and report the missing real-source corpus, full-model memory gate and safety boundary.
