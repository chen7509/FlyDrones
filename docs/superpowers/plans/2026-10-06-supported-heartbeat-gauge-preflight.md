# Supported Heartbeat Gauge Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and independently audit the prepare-only package for one future supported-motion, journaled-heartbeat, OpenVINS trajectory study.

**Architecture:** Add a truth-independent prospective gauge policy, bind it into a backwards-compatible v3 capture execution declaration and runtime inventory, then compose a new study builder and dry auditor from the frozen full-load runtime-mapping package. No simulator or estimator is started in this plan.

**Tech Stack:** Python 3.12, pathlib, strict JSON, SHA-256, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-supported-heartbeat-gauge-preflight-design.md`

## Global Constraints

- Preserve capture-execution-v1/v2 values when no trajectory policy is supplied.
- The prospective policy has no numeric anchor and never consumes truth.
- Keep 25 s, 1 ms, 250 Hz, 10 Hz 160x120, 300/300 s, and existing watchdogs unchanged.
- Do not start PX4, Gazebo, OpenVINS, training, ODOMETRY, arming, or EKF2.
- All physical, accuracy, health, runtime-closure, fusion, and flight claims remain false.

## Review Focus

- A policy containing a numeric anchor or changed screen must be refused by Task 1 tests.
- A policy changed between identity reads must be refused by Task 2 tests.
- v1/v2 callers must remain unchanged under Task 2 regression tests.
- The prepared command must not omit the policy or substitute another path under Task 3 tests.
- A complete-looking package with a lowered workload or true qualification flag must be refused by Task 4 tests.

---

### Task 1: Prospective gauge policy

**Files:**
- Modify: `tools/benchmark/trajectory_gauge_contract.py`
- Modify: `tests/benchmark/test_trajectory_gauge_contract.py`

**Interfaces:**
- Produces: `trajectory_gauge_policy() -> dict` and `validate_trajectory_gauge_policy(value) -> dict`.

- [x] Write tests for the canonical truth-independent policy, dynamic anchor source, and rejection of numeric anchors, changed screens, extra keys, and wrong scalar types.
- [x] Run the focused tests and confirm RED for the missing API.
- [x] Implement the minimal policy builder and exact validator.
- [x] Run the focused tests and confirm GREEN.

### Task 2: Execution declaration v3

**Files:**
- Modify: `tools/benchmark/capture_contract.py`
- Modify: `tools/benchmark/capture_disarmed_sensors.py`
- Modify: `tests/benchmark/test_capture_contract.py`
- Modify: `tests/benchmark/test_disarmed_sensor_provenance.py`

**Interfaces:**
- Consumes: Task 1 policy validator.
- Produces: v3 execution contract with `trajectory_gauge_policy`, worker CLI forwarding, and pre-resource worker policy evidence.

- [x] Write tests that v3 binds path/resolved identity/size/hash/schema, refuses mutation and malformed policy, forwards the CLI, and records worker evidence before resources.
- [x] Run the focused tests and confirm RED for absent CLI/schema handling.
- [x] Implement v3 while preserving v1/v2 outputs and behavior.
- [x] Run the focused tests and confirm GREEN.

### Task 3: Prepare-only integrated study

**Files:**
- Create: `tools/benchmark/supported_heartbeat_gauge_preflight.py`
- Create: `tests/benchmark/test_supported_heartbeat_gauge_preflight.py`

**Interfaces:**
- Consumes: frozen `full_load_runtime_mapping.prepare_study` inputs and Tasks 1-2 contracts.
- Produces: `prepare_study(...) -> dict` with schema `supported-heartbeat-gauge-preflight-v1`.

- [x] Write tests for policy creation, runtime inventory binding, exact declared command, immutable workloads/profiles/budgets, inactive-resource/reused-output refusal, and false claims.
- [x] Run the focused tests and confirm RED for the missing module.
- [x] Implement the minimal prepare-only composition without launching the command.
- [x] Run the focused tests and confirm GREEN.

### Task 4: Independent dry audit and publication

**Files:**
- Create: `tools/benchmark/audit_supported_heartbeat_gauge_preflight.py`
- Create: `tests/benchmark/test_audit_supported_heartbeat_gauge_preflight.py`
- Create: `docs/SUPPORTED_HEARTBEAT_GAUGE_PREFLIGHT_REPORT.md`

**Interfaces:**
- Consumes: Task 3 package.
- Produces: strict audit JSON with `preflight_qualified` and all physical/downstream qualification flags false.

- [x] Write tests for complete package acceptance and hash, command, profile, workload, inventory, policy, destination, and overclaim rejection.
- [x] Run the focused tests and confirm RED for the missing auditor.
- [x] Implement the auditor and create one fixed prepare-only package from frozen inputs without launching it.
- [x] Run focused tests, full regression, changed-file Ruff, whole-tree Ruff comparison, and diff check.
- [x] Seal inputs, outputs, tests, hashes, failures, report, and review notes in a new evidence ZIP; commit and create a stacked draft PR.
