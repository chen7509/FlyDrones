# Windowed Training Backward Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; implementation is inline, with one independent source review and a bounded executor fix pass.

**Goal:** Release earlier recurrent-window saved activations while preserving the current trainer objective and per-sequence updates.

**Architecture:** Two adjacent prediction windows, detached recurrent boundaries, full-sequence normalization and two-sided boundary partial derivatives. Evaluation shares the accounting under no_grad.

**Tech Stack:** Existing Python/PyTorch CPU software tests; no dependencies or full model execution.

**Spec:** docs/superpowers/specs/2026-10-15-windowed-training-backward-design.md

## Global Constraints

No resource polling, old CLI/observer/SDK run, stale receipt rewrite or native/physical attempt. Preserve all consumed facts and source/readiness qualifications false. Keep public APIs, dt_s=.05, sequence reset, original loss weights, one optimizer step and clip per sequence. Retain every initial failure/raw/source snapshot and exclusive fixture directory.

## Review Focus

Cross-boundary smoothness differentiates through both predictions without cross-boundary recurrence. Unequal last windows use global frame/pair denominators. Singleton sequences have zero smoothness. Earlier saved activation objects are released before a third window. Invalid late inputs or forward failure never step the optimizer. Every case is exercised below.

### Task 1: Windowed production pass and real behavior evidence

Files: modify src/flydrones/connectome_training/trainer.py; create tests/connectome_training/test_windowed_training.py. Consume existing model.forward_sequence/state.detached and sequence_loss. Preserve train_epoch/evaluate_sequences signatures; add private window iteration/accounting helpers only as needed.

- [x] Write and run tests against current production: activation lifetime and maximum forward length fail, independent full-reference gradient/update/metrics controls pass. Add unit/unequal/oversize windows, batching/reset, singleton, late invalid and forward failure tests.
- [x] Implement two-window backward and shared evaluation; run new tests plus required trainer/loss/tiny curriculum neighbors and Ruff/diffcheck. Compare all parameter gradients/updates, not just decreasing loss. Keep synthetic/tiny scope explicit.
- [ ] One independent source review, one executor fix pass if needed, honest report/canonical byte seal/independent delivery audit, onlypersonal commit/push, PR65 exact readback, automation ACTIVE/full history preserved.
