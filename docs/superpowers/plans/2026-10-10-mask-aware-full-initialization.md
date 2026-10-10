# Mask-aware full MaleCNS initialization plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Produce a separately identified, untrained 15-channel full MaleCNS parameter artifact without loading the full graph.

**Architecture:** A pure derivation function validates an untrained 12-channel parameter set and remaps the same sensory neuron indices to the 15-channel profile. A small command verifies frozen source-file identities, invokes the derivation, saves without overwriting, then reloads to verify the result.

**Tech Stack:** Python, NumPy, existing connectome parameter serializer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-mask-aware-full-initialization-design.md`

## Global constraints

- Do not load the 25,582,837-edge graph or train the full model on this host.
- Preserve the old initialization and all historical failures; use a new destination.
- The new artifact is an untrained engineering mapping, not a safety or flight result.

## Review focus

Check source hashes, exact profile order, hidden trained values, mapping coverage, destination overwrite refusal, and provenance/claim wording.

## Task 1: Derivation

- [x] Add failing tests for deterministic v3 mapping and refusal of wrong/trained sources.
- [x] Implement the minimal derivation using existing `initial_parameter_set`.
- [x] Run focused tests.

## Task 2: Frozen-source command

- [x] Add failing tests for frozen source/model hash, no overwrite and reload verification.
- [x] Implement a memory-light command with explicit source/destination arguments.
- [x] Run focused and adjacent regression tests.

## Task 3: Artifact and evidence

- [x] Check current resource availability and absence of competing runs.
- [x] Generate the new artifact once, verify hashes and old artifact invariance.
- [x] Run appropriate regression, changed Ruff and diff check; retain logs and failures.
- [x] Record verified/implemented/untested/failed boundaries, seal evidence, obtain read-only review, commit and update draft PR65 using `personal`.
