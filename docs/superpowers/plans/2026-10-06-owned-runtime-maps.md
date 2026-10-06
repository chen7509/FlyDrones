# Owned Runtime Mapping Implementation Plan

> **For Codex:** Use `superpowers:executing-plans` to implement each task in order. Apply test-driven development and preserve every failure artifact.

**Goal:** Add bounded, identity-pinned runtime mapping evidence for the capture worker, PX4, and OpenVINS without expanding cleanup scope or claiming complete runtime closure.

**Architecture:** A small `OwnedRuntimeMaps` component reads only registered process identities and file-backed maps. `RuntimeBinding` v3 owns declarations, self phases, owned roles, evidence, and final qualification. Capture hooks register and observe the already-owned PX4 and OpenVINS processes at fixed lifecycle points.

**Tech Stack:** Python 3.12, Linux `/proc`, pytest, existing capture journal, declared runtime snapshot, PX4 SITL/Gazebo/OpenVINS integration.

---

### Task 1: Implement the identity-pinned owned map reader

**Files:**
- Create: `tools/benchmark/owned_runtime_maps.py`
- Create: `tests/benchmark/test_owned_runtime_maps.py`

- [ ] Write failing tests for registration and a valid bounded observation.
- [ ] Add failing cases for PID reuse, exec change, disappearance, malformed stat, unreadable/oversized maps, deleted mappings, unknown files, identity mismatch, duplicate phase, and short evidence writes.
- [ ] Implement the minimum bounded reader using injected proc readers for deterministic tests.
- [ ] Add one real no-Gazebo child-process test that verifies identity and map coverage without scanning or signalling unrelated processes.
- [ ] Run the focused tests and Ruff on changed files.

### Task 2: Add the v3 declaration and final qualification

**Files:**
- Modify: `tools/benchmark/runtime_resource_binding.py`
- Modify: `tests/benchmark/test_runtime_resource_binding.py`

- [ ] Write failing declaration tests for exact schema, allowed roles, ordered phases, bounds, and required executable membership.
- [ ] Add tests for required self/owned phase order, duplicates, missing phases, observation exhaustion, and post-snapshot drift.
- [ ] Implement v3 validation, owned registration/observation, and `runtime_mapping_coverage_verified` while leaving `runtime_closure_qualified=false`.
- [ ] Preserve v1/v2 behavior and run all runtime-binding and graph tests.

### Task 3: Wire fixed lifecycle hooks into the capture

**Files:**
- Modify: `tools/benchmark/capture_disarmed_sensors.py`
- Modify: `tools/benchmark/openvins_online_shadow.py`
- Modify: capture tests under `tests/benchmark/`

- [ ] Write failing tests proving OpenVINS and PX4 are registered before observation and observed at declared `ready`/`prestop` phases.
- [ ] Write a failing test proving `postfirststep` occurs only after a successful first server step.
- [ ] Implement the hooks without changing motion, sensor, watchdog, timeout, or cleanup behavior.
- [ ] Make observation failures enter the existing error path while cleanup remains bounded.
- [ ] Run focused capture, shadow, fan-out, readiness, and supervisor tests.

### Task 4: Produce prospective evidence without starting physics

**Files:**
- Create: `tools/benchmark/audit_owned_runtime_maps.py`
- Create: `tests/benchmark/test_audit_owned_runtime_maps.py`
- Create: `docs/OWNED_RUNTIME_MAPS_REPORT.md`

- [ ] Freeze compiler/interpreter, source, declaration, child executable, and direct dependency identities before the harness runs.
- [ ] Run normal and faulted bounded child-process cases and preserve raw/structured evidence.
- [ ] Audit every declared member, phase, and failure, and explicitly keep runtime closure, physics, VIO, and fusion false.
- [ ] Run the full Python regression and changed-file Ruff; compare whole-repository Ruff with the base without claiming unrelated failures.

### Task 5: Review and publication gate

- [ ] Self-review the diff for PID reuse, ordering, I/O failure, unknown maps, and cleanup-scope errors; record that no independent reviewer was used.
- [ ] Seal the evidence archive with member hashes, CRC verification, and an external SHA-256.
- [ ] Commit implementation, report, and evidence in reviewable commits.
- [ ] Create a draft PR and attach it to the task.
- [ ] Update the next-step record: only after v3 evidence passes may a separately frozen full-load mapping capture run; the trajectory/gauge contract still precedes another online VIO accuracy attempt.
