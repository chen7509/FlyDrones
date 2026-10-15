# Connectome Learning Roles Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, one independent whole-source review and one bounded executor fix pass. Preserve raw and source snapshots; no cleanup/deletion.

**Goal:** Implement real parameter learning roles through curriculum, checkpoint and offline inference.

**Architecture:** Fixed supported role profiles configure requires_grad and optimizer object membership. Frozen initialization identities and role membership bind checkpoint/model identity and explicit inference loading; legacy artifacts remain explicitly unspecified.

**Tech Stack:** Existing Python/PyTorch CPU, tiny synthetic fixtures only, no new dependencies.

**Spec:** docs/superpowers/specs/2026-10-15-connectome-learning-roles-design.md

## Global Constraints

No resource polling, target/SDK/fullMaleCNS/physical execution, old CLI/observer rerun or stale receipt rewrite. Topology/signs/loss/window/curriculum safety and all original qualification/resource gates stay unchanged. Default new sessions use shared-dynamics-v1. Legacy artifacts receive no retrospective role authority.

## Review Focus

Actual optimizer objects must match declared active names, not just requires_grad flags. Frozen payload tampering must refuse despite coherent file SHA. Cross-role restore must reject before copying. Explicit inference must rederive source-bound frozen initialization. Legacy no-profile inference must stay compatible without new role claims. CLI invalid choices must reject without invoking training.

### Task 1: Role-bound curriculum and offline producer

Files: create src/flydrones/connectome_training/training_roles.py; modify curriculum_session.py/inference_artifact.py/inference.py and tools/connectome_training/run_curriculum.py; create tests/connectome_training/test_learning_roles.py. Existing model/trainer/data/legacy native modules unchanged.

- [x] Write tiny behavior tests for actual active/frozen updates, checkpoint/inference/CLI role binding and drift. Run and retain genuine missing-interface/behavior failures; no real child or target run to demonstrate RED.
- [x] Implement supported role configuration, frozen tensor identities, actual optimizer checks, new session identity/checkpoint joins, explicit inference/legacy distinction and CLI routing. Run affected tests and required tiny checkpoint/inference/curriculum neighbors, Ruff/diffcheck; no full repository/CLI/native suite.
- [ ] One independent source review, one bounded executor fix pass, honest report/canonical seal/independent delivery audit, onlypersonal commit/push/PR exact readback, automationACTIVE/full history preserved.
