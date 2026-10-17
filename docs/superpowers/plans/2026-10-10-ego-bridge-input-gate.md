# EGO Bridge Input Gate Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Refuse malformed or stale EGO bridge observations before any ROS publication without changing fixed upstream planning behavior.

**Architecture:** Put bounded, pure JSON/RGB-D validation and monotonic sequence state in `tools/benchmark/ego_wire_observation.py`; call them from the existing ROS bridge. Keep source attestation and causal teacher-reference qualification as separate closed gates.

**Tech Stack:** Python 3.12, NumPy, pytest, ROS 2 Humble runtime only for the existing bridge.

**Spec:** `docs/superpowers/specs/2026-10-10-ego-bridge-input-gate-design.md`

## Global constraints

- Fixed EGO checkout `23a8d5a191711dd65633df689bd00f55d4dea8f9`, GPL-3.0; no upstream modification or new dependency.
- Exact packet schema, RGB 120×160×3 uint8 and depth 120×160 float32; NaN depth means missing, Infinity/nonpositive finite depth is refused.
- No old-frame replay, Gazebo truth promotion, training, PX4/Gazebo/container run, or formal-test-set tuning.
- Old comparison evidence is immutable; new bridge code requires a separate future freeze.

## Review focus

- JSON duplicate keys and nonfinite literals must be refused before coercion.
- Shape and base64 length must be checked before allocating or reshaping image arrays.
- Bool/string numeric values, bad quaternion and time regression must not reach a ROS publisher.
- Repeated camera frame with newer odometry is legitimate; repeated or backwards simulation time is not.
- A valid but delayed upstream command must not be described as causally tied to the latest frame.

## Task 1: Pure wire boundary

**Files:** create `tools/benchmark/ego_wire_observation.py`; create `tests/benchmark/test_ego_wire_observation.py`.

- [x] Write valid and malformed packet/sequence tests, then run targeted pytest to observe behavior RED.
- [x] Implement exact bounded decode plus sequence guard; run targeted tests GREEN.

## Task 2: Bridge binding

**Files:** modify `tools/benchmark/ego_node.py`; add a separate future-only fixture `results/ego-upstream-source-audit-dev-1701/synthetic_client_v2.py` while preserving the historical fixture; test in `tests/benchmark/test_ego_wire_observation.py` and adjacent benchmark tests.

- [x] Add bridge wiring and stale-command timing tests showing failures before the fix; observe RED.
- [x] Use the pure decoder and resettable sequence guard in the bridge; add a future synthetic fixture with RGB encoding; run GREEN.
- [x] Run adjacent benchmark/sensor tests, changed-file Ruff, diff check and a read-only review. Record source/semantic limits and seal results.

## Task 3: Report and integration

**Files:** create `docs/EGO_BRIDGE_INPUT_GATE_REPORT.md` and an evidence ZIP.

- [ ] Distinguish validated format, unresolved Odometry frame convention/teacher causality, and no physical qualification.
- [ ] Commit and push only `personal`; update draft PR65 and heartbeat progress without reclassifying old evidence.
