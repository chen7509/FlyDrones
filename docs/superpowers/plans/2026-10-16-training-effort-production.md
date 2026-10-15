# Training Effort Implementation Plan

> For agentic workers: use superpowers:executing-plans inline. User standing autonomy precludes staged approval and new chats.

Goal: measure actual software training calls/exposure through existing trainer/session/comparison consumers, preserving failure prefixes.

Architecture: trainer TrainingEffort counts at actual call boundaries; session owns one lifetime instance and emits copied snapshots; role comparison persists the snapshot before actual session release on success/error. Checkpoints do not rewind or carry counters.

Tech stack: existing Python/Torch/pytest only.

Spec: docs/superpowers/specs/2026-10-16-training-effort-production-design.md

Global constraints: no change to math, topology, dt, learning freedom, gates, updates epoch semantics, checkpoint identity or defaults. Actual step return does not imply changed parameter; raised step may mutate. Lifetime starts at this session construction, not authenticated total historical effort. No resources/native/consumed rerun; all8/readiness false. Prior retention errata and full history remain binding.

Review focus: partial backward frames omitted explicitly; update-then-raise counts unresolved return separately; checkpoint rollback never erases physical work; fresh resume cannot inherit historical counts; comparison error snapshot persists before session release.

- [x] Implement integrated counters with new tests first: actual six calls/48 frames versus two epochs, actual update-then-raise prefix, unchanged train trajectory, restore lifetime and fresh resume, three-role success and actual step failure persistence. New tests tests/connectome_training/test_training_effort.py; modify trainer.py/curriculum_session.py/role_comparison.py. Run only new tests and necessary affected neighbors with prospective retained fixture recorder; retain every failure.
- [x] One fresh whole source review against exact source/spec/plan snapshots; regrade by user impact, at most one bounded fix pass with true RED/GREEN where applicable. Final format/Ruff/diff and necessary affected suite; honest warnings/limits/report. Independently seal/audit delivery without code/native reapproval.
- [ ] Publish exact software/plan-byte ledger only to personal/PR65; preserve entire prior PR/automation prompt suffix and three full history files. Keep automation ACTIVE/goal blocked read-only. Postseal notes new files, no mappedraw edits; final independent publication integrity audit, quiet software status.
