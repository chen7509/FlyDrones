# Declared Launch Environment Implementation Plan

> **For Codex:** Execute task by task with TDD. Preserve every refusal and do not launch a new PX4/Gazebo/OpenVINS study in this plan.

**Goal:** Make the exact supervisor-to-worker environment a prospective, auditable part of v3-bound capture execution while preserving legacy v1 captures.

**Architecture:** Derive a nullable environment map only from the sealed binding and graph. Store it in execution contract v2, materialize only non-null entries for `Popen`, independently record the supervisor declaration and the worker's initial `/proc/self/environ`, and refuse any mismatch before resource or simulator initialization.

**Tech stack:** Python 3.12, pytest, Linux `/proc/self/environ`, existing bounded process-group supervisor and capture contracts.

---

### Task 1: Exact nullable environment contract

**Files:**
- Modify: `tools/benchmark/capture_contract.py`
- Modify: `tests/benchmark/test_capture_contract.py`

- [ ] Write failing tests for deterministic union, absent-versus-empty, conflicting overlap, malformed key/value, oversize, and exact materialization.
- [ ] Add execution contract v2 only when an explicit launch environment is supplied; preserve v1 bytes and behavior otherwise.
- [ ] Keep duplicate-key and nonfinite JSON refusal.

### Task 2: Supervisor transport and evidence

**Files:**
- Modify: `tools/benchmark/disarmed_sensor_provenance.py`
- Modify: `tests/benchmark/test_disarmed_sensor_provenance.py`

- [ ] Write failing tests that the real spawn receives only the declared materialized environment.
- [ ] Write failing tests for exclusive record creation, short write/flush/close failure, malformed environment, spawn failure, timeout, and cleanup preservation.
- [ ] Record the contract path/hash and conservative claims before spawn.

### Task 3: Worker observation and early refusal

**Files:**
- Modify: `tools/benchmark/capture_disarmed_sensors.py`
- Modify: `tests/benchmark/test_capture_contract.py`

- [ ] Write failing tests for `/proc/self/environ` parsing, duplicates, malformed entries, absent/empty mismatch, exact match, and evidence-write failure.
- [ ] Validate and record v2 environment before active-resource inspection, generated copies, TestFixture, PX4, or OpenVINS.
- [ ] For v2, consume the frozen Gazebo lookup path without prepending it again; retain v1 behavior.

### Task 4: Builder integration and fixed-input audit

**Files:**
- Modify: `tools/benchmark/full_load_runtime_mapping.py`
- Modify: `tests/benchmark/test_full_load_runtime_mapping.py`
- Create: `tools/benchmark/audit_declared_launch_environment.py`
- Create: `tests/benchmark/test_audit_declared_launch_environment.py`

- [ ] Derive the environment only from the validated v3 binding and graph before writing execution contract v2.
- [ ] Require the declared study command to validate the same environment.
- [ ] Add an auditor that checks declaration/hash, supervisor materialization, worker observation, terminal lifecycle, and conservative false claims.
- [ ] Project the retained PR58 failure into the auditor as a refusal case; do not edit or rerun it.

### Task 5: Real bounded Linux harness

- [ ] Verify no competing PX4/Gazebo/OpenVINS/training process exists.
- [ ] Freeze a minimal absolute-path Python child and a hostile parent environment before execution.
- [ ] Run once through the real process-group supervisor; prove exact declared child environment, hostile-variable absence, worker exit, no executing members, group absence, and no SIGKILL.
- [ ] Retain any failure and do not add variables from runtime observation.

### Task 6: Regression, report, evidence, and handoff

**Files:**
- Create: `docs/DECLARED_LAUNCH_ENVIRONMENT_REPORT.md`
- Create: `evidence/declared-launch-environment-dev-1701.zip`

- [ ] Run focused tests, full regression, changed-file Ruff, whole-repository Ruff comparison, and `git diff --check`.
- [ ] Self-review environment leakage, absent/empty semantics, worker timing, cleanup, backwards compatibility, and overclaiming; record the single-agent review limit.
- [ ] Seal source, tests, harness, failures, hashes, and report with member SHA-256 and ZIP CRC verification.
- [ ] Create and attach a stacked draft PR.
- [ ] Update the active automation to the trajectory/gauge contract; do not claim physical environment, VIO, or flight qualification.
