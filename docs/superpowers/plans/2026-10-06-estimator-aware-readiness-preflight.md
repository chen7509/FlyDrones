# Estimator-Aware Readiness Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a causal, truth-free internal-estimator readiness gate and produce an independently audited prepare-only package for one future supported-motion study.

**Architecture:** Retain native acknowledgement batches in the existing single-worker transport, compose rather than weaken current sensor/heartbeat readiness, add an opt-in fan-out profile, then derive a new launch declaration from PR63 without executing it.

**Tech Stack:** Python 3.12, strict JSON/SHA-256, existing OpenVINS native protocol, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-estimator-aware-readiness-preflight-design.md`

## Constraints

- Do not start OpenVINS, PX4, Gazebo, training, a capture worker, or physics.
- Do not change existing readiness/fan-out profiles or their outputs.
- Do not use truth, elapsed time, public initialization, errors, or later trajectory quality to select the anchor.
- Preserve all workload, force, timeout, runtime-map, trajectory, and safety limits.
- Keep physical execution, whole runtime closure, VIO accuracy/health, fusion, and flight false.

### Task 1: Causal estimator acknowledgement evidence

**Files:**
- Modify: `tools/benchmark/openvins_online_shadow.py`
- Create: `tests/benchmark/test_estimator_aware_readiness.py`

- [x] Write RED tests requiring an exact per-source acknowledgement batch, reset before each source record, and retained partial acknowledgements on failure.
- [x] Implement minimal acknowledgement retention without changing native transport or existing output files.
- [x] Run focused tests to GREEN.

### Task 2: Estimator-aware readiness and fan-out

**Files:**
- Create: `tools/benchmark/estimator_aware_readiness.py`
- Modify: `tools/benchmark/ready_shadow_fanout.py`
- Modify: `tools/benchmark/journaled_heartbeat_lane.py`
- Modify: `tests/benchmark/test_estimator_aware_readiness.py`

- [x] Write RED tests for strict camera acknowledgement semantics, state/sample consistency, monotonicity, two-second freshness, immutable first evidence, journal failure, close failure, and concurrent proof.
- [x] Add a no-op post-shadow hook to the base fan-out and implement the opt-in estimator-aware heartbeat subclass.
- [x] Verify legacy fan-out behavior remains unchanged and run focused tests to GREEN.

### Task 3: Capture integration and declaration

**Files:**
- Modify: `tools/benchmark/capture_disarmed_sensors.py`
- Modify: `tools/benchmark/capture_contract.py`
- Modify: `tests/benchmark/test_disarmed_sensor_provenance.py`
- Modify: `tests/benchmark/test_capture_contract.py`

- [x] Write RED tests for the new CLI profile, exact worker forwarding, estimator-aware readiness construction, cleanup, and old-profile compatibility.
- [x] Implement the opt-in capture route without changing motion, source, native, runtime-map, or safety limits.
- [x] Run focused integration tests to GREEN (125 passed); the generic contract already preserves arbitrary validated profile values, so no contract-code change was needed.

### Task 4: Prepare-only package and independent audit

**Files:**
- Create: `tools/benchmark/estimator_aware_readiness_preflight.py`
- Create: `tools/benchmark/audit_estimator_aware_readiness_preflight.py`
- Create: `tests/benchmark/test_estimator_aware_readiness_preflight.py`
- Create: `tests/benchmark/test_audit_estimator_aware_readiness_preflight.py`

- [x] Write RED tests for exact archived PR63 source/audit validation, fresh source-code closure, new profile as the sole behavioral contract change, exact future destination, absent capture, runtime-map preservation, and false downstream claims.
- [x] Implement the builder and independent auditor; run one fixed prepare-only build without invoking its command. The historical PR63 audit is byte-matched to its evidence archive; its mutable baseline is explicitly reported as no longer current after this code change.
- [x] Run focused tests to GREEN (165 passed across the new route and its legacy dependencies).

### Task 5: Verification and publication

**Files:**
- Create: `docs/ESTIMATOR_AWARE_READINESS_PREFLIGHT_REPORT.md`
- Create: `evidence/estimator-aware-readiness-preflight-dev-1701.zip`

- [x] Run full regression, changed-file Ruff, source-tree Ruff comparison, and `git diff --check`.
- [x] Confirm no competing or leftover runtime/test process.
- [x] Seal sources, retained failures, outputs, tests, report, manifest, ZIP hash, and CRC.
- [ ] Commit, push, and open a stacked draft PR.
