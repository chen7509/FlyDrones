# Offline Connectome Inference Adapter Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; TDD each task
> and one independent whole-package review after implementation.

**Goal:** Run the existing learned core through a causal, identity-bound offline
inference boundary without training or flight activation.

**Architecture:** Shared training feature/mapping primitives, a strict CPU artifact
loader, then a stateful controller returning raw and shaped high-level intent.

**Tech Stack:** Existing Python/NumPy/SciPy/PyTorch; no dependency installation.

**Spec:** `docs/superpowers/specs/2026-10-09-connectome-inference-adapter-design.md`.

## Global Constraints

- No physics/network/training/PX4 activation; original formal results unchanged.
- Full = 166,700 neurons / 25,582,837 connections; tiny-fixture <=1,024 neurons.
- CPU only, 50,000,000 ns steps, maximum camera age 100,000,000 ns.
- Defaults: speed 0.8 m/s, acceleration 1.2 m/s2, yaw rate 0.6 rad/s.
- Keep old artifacts; no full construction with <4 GiB available physical RAM.
- Existing user preapproval covers design/implementation; execute inline.

## Task 1: Shared primitives and artifact loader

Files: modify `features.py`, `parameters.py`, `curriculum_session.py` in
`src/flydrones/connectome_training`; add `inference_artifact.py` and
`tests/connectome_training/test_inference_artifact.py`.

Produces: public `frame_features`, `parameter_mapping_digest`, frozen
`CheckpointIdentity(checkpoint_sha256, config_digest, dataset_sha256)`,
`load_inference_core(...) -> LoadedInferenceCore(core, provenance)` per spec.

- [x] Write and run RED cases for public feature parity, file hash/topology/
  mapping/feature-order refusal, tiny/full identity, checkpoint exact keys/dtypes/
  shapes/nonfinite data, metadata mismatch and fixed-buffer injection.
- [x] Reuse parameter/checkpoint loaders; expose unchanged feature/mapping code;
  validate all checkpoint tensors before copying, disable gradients, retain
  ordinary pre/post hashes. No optimizer/global RNG restoration.
- [x] Run `python -m pytest tests/connectome_training/test_inference_artifact.py
  tests/connectome_training/test_parameters.py tests/connectome_training/test_curriculum.py
  tests/connectome_training/test_model.py -q`; expected all pass. Commit.

## Task 2: Causal controller and intent shaping

Files: add `src/flydrones/connectome_training/inference.py` and
`tests/connectome_training/test_inference.py`.

Consumes Task 1 loaded core/features; produces `InferenceLimits` and
`ConnectomeInferenceController` with `step(SequenceFrame)->Decision`, reset/close.

- [x] RED: analytic raw output, parity with direct recurrent core, reset,
  correct ENU shaping, camera reuse and changed content, all time/refusal cases,
  nonfinite state/output, fail latch and terminal close.
- [x] Implement single-owner CPU synchronous state transaction and diagnostic
  evidence. Default envelope uses existing `shape_command`; no live I/O.
- [x] Run `python -m pytest tests/connectome_training -q`; expected all pass.
  Commit implementation and Task 2 result.

## Task 3: Verification, evidence and resource decision

Files: report `docs/CONNECTOME_INFERENCE_ADAPTER_REPORT.md`; evidence directory
`results/connectome-inference-adapter-dev-1701`; preserve this plan's ledger.

- [x] Run full pytest, changed Ruff and diff check; report every failure/skip.
- [x] One independent review of the package against this spec; fix meaningful
  findings with demonstrated RED/GREEN and relevant regression.
- [x] Recheck available RAM before any full-core construction. Below 4 GiB:
  retain resource preflight and do not run full model. Otherwise independently
  predeclare bounded initialization-only CPU probe before executing; no reuse
  of tiny results to declare full inference or learning performance.
- [x] Record verified/implemented/unmeasured/failure boundaries, seal evidence
  with member hashes/CRC, commit. Existing remote upload problem remains
  separate; no blind push retry, merge or history rewrite.

## Review Focus

Checkpoint topology-buffer injection, mislabeled initialization, camera timestamp
reuse with changed pixels, state advancement on refusal, and SI/ENU output
direction all have explicit tests in Tasks 1/2. Full-core timing remains a separate
resource-gated probe, never a tiny-test acceptance claim.
