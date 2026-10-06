# Causal Pair Simulation-Time Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and independently qualify an authoritative prepare-only package that binds the immutable camera-pair refusal and simulation-time correction, then run one startup-only preflight. The rejected `study-v17` is retained and the authoritative package is `study-v18`.

**Architecture:** A narrow builder verifies the prior capture, audit and sealed archive before copying frozen contracts and regenerating only the authorization, runtime binding, execution contract and manifest. A separate auditor recomputes every claim from source files and rejects destination or workload drift. The production capture entry point is used only in startup-preflight mode after the committed package boundary passes.

**Tech Stack:** Python 3.12, pytest, JSON manifests, ZIP/SHA-256 evidence, existing FlyDrones capture and supervisor tools.

**Spec:** `docs/superpowers/specs/2026-10-07-causal-pair-sim-time-retry-design.md`

## Global Constraints

- Preserve 25 s, 1 ms physics, 250 Hz raw IMU and 10 Hz 160×120 RGB-D exactly.
- Preserve all PX4/OpenVINS/native inputs, vehicle, gravity, trajectory, force and safety settings.
- Preserve every high-rate wall watchdog and use the unchanged 250 ms simulation-time threshold only for RGB/CameraInfo dependency age.
- Do not create, overwrite or rerun `study-v16/capture-v1`.
- Keep all physical, runtime, VIO, fusion and flight claims false until corresponding evidence exists.

## Review Focus

- Archive with valid CRC but a changed implementation member must be rejected by byte identity.
- Source audit with the right label but wrong wall/simulation ages must be rejected.
- Existing or renamed `study-v17/capture-v1` must prevent generation or startup dispatch.
- Workload, command, environment, timeout or runtime-baseline drift must fail the independent audit.
- Startup-preflight output containing PX4/OpenVINS/physics/sensor/motion/ULog evidence must fail qualification.

---

### Task 1: Prepare-only builder and independent auditor

**Files:**
- Create: `tools/benchmark/causal_pair_sim_time_retry_preflight.py`
- Create: `tools/benchmark/audit_causal_pair_sim_time_retry_preflight.py`
- Create: `tests/benchmark/test_causal_pair_sim_time_retry_preflight.py`

**Interfaces:**
- Consumes: immutable `study-v16`, physical completion, correction audit/archive and `openvins_causal_input.py`.
- Produces: `prepare(...) -> dict`, `validate_correction(...) -> dict`, `audit(root, after_startup_preflight=False) -> dict`.

- [x] Write tests that reject correction/archive/implementation drift, wrong physical classification or ages, resources, existing output and overclaims.
- [x] Run the focused tests and record the expected RED failures caused by the missing module.
- [x] Implement the minimal builder and auditor with strict archive/member byte verification and unchanged execution recomputation.
- [x] Run the focused tests and changed-file Ruff to GREEN.
- [x] Retain the baseline-drift rejection for `study-v17`; generate and audit authoritative `study-v18`, commit the boundary and rerun the audit from committed code.

### Task 2: Startup-only production preflight

**Files:**
- Create: `results/estimator-physical-refusal-diagnosis-dev-1701/study-v17/startup-preflight-v1/`
- Create: dispatch, completion, supervisor and independent startup-audit evidence.
- Modify: `docs/ESTIMATOR_PHYSICAL_REFUSAL_DIAGNOSIS_REPORT.md`

**Interfaces:**
- Consumes: committed authoritative `study-v18` manifest, execution contract and runtime binding.
- Produces: startup-preflight result with phase exclusion, cleanup and empty-resource evidence.

- [ ] Build a one-shot wrapper that checks the exact head, committed package audit, absent destination and empty resources.
- [ ] Execute exactly one startup-preflight and retain success or failure without retry.
- [ ] Audit allowed phases, absence of PX4/OpenVINS/physics/sensors/motion/ULog, runtime files, supervisor cleanup and resources.
- [ ] Run focused and full regression tests, changed-file Ruff and source diff checks.
- [ ] Update the report, seal evidence, commit and push PR65; advance automation only to the next proven dependency.
