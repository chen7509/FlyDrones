# Connectome Corpus v2 Index Implementation Plan

> **For agentic workers:** Use the existing task's TDD and review workflow. This plan needs no new task or approval because the user already authorized continuous execution.

**Goal:** Consume and integrity-check the exact 54 predeclared v2 corpus jobs without promoting self-declared files to trusted physical training data.

**Architecture:** Add a focused `corpus_index.py` verifier that takes a validated `CorpusConfig` and an index JSON path. Reuse `CorpusConfig.jobs`, `build_corpus_world`, and `load_sequence`; return only immutable audit records and a digest. Keep the existing curriculum loader and smoke path unchanged until an independent capture producer can qualify source evidence.

**Tech stack:** Python standard library, existing NumPy sequence loader and corpus world builder; no new packages.

**Spec:** `docs/superpowers/specs/2026-10-12-connectome-corpus-v2-index-design.md`.

## Tasks

1. Write synthetic 54-job tests for the exact job matrix, canonical world and v3 sequence binding. Verify they fail before the module exists.
2. Implement strict index/receipt parsing, normalized confined file identity, file hashes and duplicate detection. Run focused tests green.
3. Add refusal tests for missing/extra/relabelled jobs, duplicate run/path/payload, tampered hashes, symlink/escape, source/teacher mismatch and failed terminal. Run them green.
4. Run adjacent connectome regression, Ruff and diff checks; record the observed host resource and why physical/full training was not launched.
5. Obtain independent read-only review, fix material findings, seal code/tests/evidence, report the integrity-only scope, commit and update draft PR65. The next implementation stage is the true non-truth capture producer and a distinct training-eligibility gate.
