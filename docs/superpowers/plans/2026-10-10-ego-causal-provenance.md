# Fixed EGO teacher causal provenance Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement each task. Steps use checkbox syntax for tracking.

**Goal:** Obtain source-attested, session-bound EGO plan-to-input evidence before any new teacher label is accepted.

**Architecture:** Snapshot the exact upstream data path first; add read-only planner/map instrumentation in a separately versioned build; join its plan record to raw PositionCommand and PX4/camera input journals in a fail-closed bridge verifier. Keep ordinary control references distinct from qualified teacher labels.

**Tech Stack:** pinned ROS 2 Humble EGO checkout, C++ diagnostic patch, Python bridge/verifier, pytest, ROS development capture.

**Spec:** `docs/superpowers/specs/2026-10-10-ego-causal-provenance-design.md`

## Global constraints

- Original EGO `23a8d5a191711dd65633df689bd00f55d4dea8f9` and historical evidence remain unchanged; GPL-3.0 patch provenance and binary identity must be recorded.
- Do not treat bridge receipt-time `sim_ns`, `PositionCommand.header.stamp`, `trajectory_id`, a received depth frame, or socket ordering alone as proof of consumed inputs.
- Do not start ROS/PX4/Gazebo/training when the host lacks the existing resource gate. No truth state may enter teacher or student inputs. Formal held-out worlds remain untouched.
- Preserve old failure logs. Each new development run gets a fresh ID, predeclared hashes, raw logs and explicit source/causality/performance qualification flags.

## Review focus

- Old-plan command after a new observation must remain a control reference only; it cannot become a fresh teacher label.
- Matching trajectory numbers across a reset must not join different sessions.
- `int64 → int → uint32` trajectory IDs must be positive, at most target `INT_MAX`, exactly equal and unique within a session; reject narrowing/alias values.
- A depth/pose callback without a completed occupancy update must not qualify a plan as having used that image.
- Replanning may sample its start state from the previous trajectory; never present merely available odometry as that consumed start state. Record origin and prior trajectory lineage.
- Nonzero yaw must expose the current world-velocity versus ROS `child_frame_id` semantics explicitly.
- Malformed/stale source records, missing calibration or any truth-source input fail closed.

## Task 1: Static pinned-source audit

**Files:** `results/ego-causal-provenance-dev-1701/`, `docs/EGO_CAUSAL_PROVENANCE_AUDIT_REPORT.md`, this spec and plan, a new evidence ZIP.

- [x] Read pinned Git blobs for FSM, map, trajectory server and both messages; verify Git-blob and SHA-256 identity against the previous audit where available, then bind every path/blob to the fixed commit tree.
- [x] Record exact available and missing input/plan/command identity fields, source maintenance/license/resource implications and the selected instrumentation approach. No runtime claim.
- [x] Independently review the source-to-conclusion chain, seal member hashes, run static verification, commit and update PR65.

## Task 2: Diagnostic patch and exact message binding

**Files:** new versioned patch under `tools/benchmark/`, new pure verifier under `src/flydrones/benchmark/`, targeted tests and a separate patched EGO image manifest.

- [ ] Write RED tests for odometry and applied-map identity, trajectory/session matching including `INT_MAX`/alias cases, old-plan/restart/reorder rejection and no change to planner outputs.
- [ ] Make the smallest read-only EGO instrumentation patch; record source/binary/type-support/patch hashes. Do not replace planning logic or invent map inputs.
- [ ] Version the static candidate instead of rewriting sealed evidence; record completed-map and successful-plan node-clock instants and an event steady-clock instant. Add RED/GREEN source-contract and native-writer tests. Do not call node-clock values simulation time until runtime `/clock`/launch evidence proves it.
- [ ] Bind exact serialized bridge-published image/pose/odometry and bridge-received command bytes to planner/server records by hashes, stamps, session and process identity; reject independent sequence aliasing, cloud writes and unbound extrinsics. Preserve the conservative equal-sequence offline join until a separate history-aware contract is proven.
- [x] Add a pure offline, fail-closed candidate reconciler and synthetic multi-plan/fault matrix for the proposed bridge/planner/server journal schema. Keep `runtime_source_verified` and `teacher_qualified` false until a real producer and patched ROS runtime are proven.
- [ ] Build and test in a resource-controlled development environment; compare patched and unpatched plans under identical input before promoting the patched image.

## Task 3: Owned single-drone development capture

**Files:** provenance-bound PX4/camera producer, bridge journal, new run/evidence report.

- [ ] Predeclare identity, input clocks, calibration and thresholds. Check no competing processes and sufficient memory, then perform one bounded development run.
- [ ] Verify actual source and plan-to-input joins plus safety/ULog; retain all failures. Only a passing new-corpus record may train the full MaleCNS path.
- [ ] Keep formal 20 unseen scenes and five-drone threshold sealed until prerequisite single-drone evidence is complete.
