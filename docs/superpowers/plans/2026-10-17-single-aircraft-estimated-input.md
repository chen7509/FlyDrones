# Single-aircraft estimated input implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement inline. No staged user approvals; the user explicitly authorized continuation.

**Goal:** Route the actual simulation backend's opt-in controller observations through a supplied estimated-state source while leaving truth in the independent scorer.

**Architecture:** Extend the existing backend/contract. The source is a dependency interface, not a measurement or flight-authority factory. No native launch is needed to verify the routing.

**Tech Stack:** Existing Python/NumPy/pytest, existing Gateway and stop/LAND behavior.

**Spec:** docs/superpowers/specs/2026-10-17-single-aircraft-estimated-input-design.md

## Global constraints

- Physical gate remains dual4GiB; this host was below it. No new native/physical execution or resource polling in this software task.
- Truth never enters the opt-in controller path; historical default truth mode remains explicitly labelled.
- Source readiness callback and typed values do not authenticate source, calibration or fusion. All existing qualification flags remain false.
- Preserve old failures, archives and consumed versions. Only personal/PR65 publication. Do not rerun whole historical suites.

## Review Focus

- Estimated body state with camera pose from a different image: refuse exact frame mismatch.
- Same source reset/session change while no new RGB arrives: still reject before sending control.
- Readiness expires during telemetry/heartbeat calls: check again at the raw send boundary.
- Goal accidentally copied from simulator: require separately supplied estimator-frame goal.
- Legacy truth branch or source exception falls through into motion: no fallback; existing stop/LAND failure latch wins.

### Task 1: Actual backend estimated-input integration

**Files:** src/flydrones/benchmark/contract.py and gateway.py; src/flydrones/drones/mavlink.py; tools/benchmark/run_episode.py; tests/benchmark/test_estimated_controller_input.py.

**Consumes:** Existing RGB-D frame cache, Command/Observation and backend stop/send paths.
**Produces:** EstimatedControllerState; optional estimated_state_source and goal_in_estimator_frame constructor arguments. Source require_ready(sim_ns) raises on failure; snapshot(sim_ns,frame_ns) returns one typed state. No source factory or CLI launch grant.

- [x] Write tests first for no truth access, exact estimated values, absent explicit goal, stale/future/mismatched-frame/session/reset refusal, prearm and final-send failure, independent truth score and legacy behavior.
- [x] Run new tests with owned basetemp and raw/source retention. Missing-interface failures are not behavior/native RED.
- [x] Implement the opt-in routing/checks in the existing backend, source labels in the existing result writer, and immutable state contract. Keep default legacy math unchanged.
- [x] Verify new tests plus necessary gateway publication/stationary/RGB neighbors, Ruff and dedicated diff checks. Record actual failures without rewriting logs.
- [x] One independent source review C0/I3/M0, one bounded repair pass; final114passed2.00s/Ruff0/diff0. All13 exclusions ruled individually; no second review/native grant.
- [x] Publish only actual scope/results to personal PR65; do not claim flight completion.

### Downstream, still pending

Bind a real owned OpenVINS/EKF2 source to this interface; validate measured calibration/clock/reset/health and actual disarmed reception/fusion; replace auto-takeoff legacy orchestration with explicit qualification phases, wire actual upstream planner, then execute development and held-out missions. These are not completed by Task1's synthetic inputs. Hardware/HITL/real flight and full MaleCNS learning remain separate.
