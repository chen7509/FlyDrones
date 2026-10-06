# OpenVINS Lazy Runtime Mapping Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explain, reproduce, and prospectively bind the single lazy oneTBB allocator mapping that stopped the first `dry-v5` physical attempt, without launching another physical simulation.

**Architecture:** Build a strict source/package provenance contract, a bounded single-input owned-process mapping probe, and an independent auditor. Produce one immutable evidence package whose only positive claim is that this exact OpenVINS binary/config predictably adds this exact allocator mapping after its first acknowledged IMU packet.

**Tech Stack:** Python 3.12, `/proc`, ELF/package command adapters, SHA-256, pytest, existing `NativeClient` and runtime-map parser.

**Spec:** `docs/superpowers/specs/2026-10-06-openvins-lazy-runtime-closure-design.md`

## Global constraints

- Do not start PX4, Gazebo, training, ODOMETRY, arming, EKF2, or a physical study.
- Do not change OpenVINS, its configuration, the workload, or any existing evidence.
- Do not convert the historical unknown path into an unchecked whitelist.
- Keep all downstream qualification fields false, including whole-runtime closure, VIO accuracy/health, fusion, and flight.
- Retain all failures and use a new output directory for each real probe.

### Task 1: Provenance and historical-failure contract

**Files:**
- Create: `tools/benchmark/openvins_lazy_runtime_closure.py`
- Create: `tests/benchmark/test_openvins_lazy_runtime_closure.py`

- [x] Write RED tests for exact historical unknown identity, stable executable identity, no mismatches, exact package/version dependency, canonical library identity, upstream commit/source/license identity, and ordinary-closure exclusion.
- [x] Add rejection tests for malformed JSON, booleans as integers, ambiguous owners, inexact dependencies, symlink/path drift, changed files, incorrect SONAME/load name, and overclaims.
- [x] Implement strict parsers and prospective declaration construction.
- [x] Run focused tests to GREEN.

### Task 2: Bounded single-input mapping probe

**Files:**
- Modify: `tools/benchmark/openvins_lazy_runtime_closure.py`
- Modify: `tests/benchmark/test_openvins_lazy_runtime_closure.py`

- [x] Write RED tests for stable-map polling, process identity, exact one-packet acknowledgement, before/after delta, timeout, removed/extra mapping, client failure, nonzero exit, and evidence-write failures.
- [x] Implement an injectable probe around the production `NativeClient` and `/proc` readers.
- [x] Confirm synthetic tests never spawn an external process.
- [x] Run focused tests to GREEN.

### Task 3: Independent auditor

**Files:**
- Create: `tools/benchmark/audit_openvins_lazy_runtime_closure.py`
- Create: `tests/benchmark/test_audit_openvins_lazy_runtime_closure.py`

- [x] Write RED tests for manifest/hash/provenance/trigger/delta/output/overclaim checks.
- [x] Implement a read-only auditor that recomputes identities and rejects any missing or extra claim.
- [x] Run focused tests to GREEN.

### Task 4: Fixed local run and publication

**Files:**
- Create: `docs/OPENVINS_LAZY_RUNTIME_CLOSURE_REPORT.md`
- Create: `evidence/openvins-lazy-runtime-closure-dev-1701.zip`

- [x] Freeze the exact local package, upstream source, executable, config, historical failure record, and command outputs before the real probe.
- [x] Confirm no competing PX4/Gazebo/OpenVINS/training/test process.
- [x] Run one isolated single-IMU mapping probe and retain every output.
- [x] Run the independent auditor, focused tests, full regression, changed-file Ruff, whole-tree Ruff comparison, and `git diff --check`.
- [x] Seal evidence with a member manifest, verify ZIP hashes/CRC, write the report, commit, and open a stacked draft PR.
- [x] Do not launch a physical study in this plan.
