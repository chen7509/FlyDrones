# Managed capture source implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; standing authorization forbids staged approval loops. Preserve evidence workspace.

**Goal:** Connect artifact consumption and actual native-event state ownership to the existing disarmed capture/receiver lifecycle.

**Architecture:** Explicit SHA-bound config → raw-contract calibration → managed native client/state cache → existing sole wire owner. Unsupported native offsets, unavailable resets or missing measured/fusion evidence refuse; they never become synthetic authority.

**Tech Stack:** Existing Python, NumPy/SciPy, YAML, pymavlink and guarded pytest. No native builds/runs.

**Spec:** docs/superpowers/specs/2026-10-17-managed-capture-source-design.md

## Global constraints

Keep original resources/budgets/sensors/safety/RTF and consumed failures; truth only independent score/abort. No resource polling, new socket owner, fake quality/reset/covariance/clock, PARAM_SET/ARM/control or flight qualification. Only personal/PR65 publication. Preserve prior sealed artifacts and original review grades.

## Review focus

- Raw versus interval-mean IMU artifacts cannot cross consumers.
- Actual selected native calibration/config must match artifacts before child construction, including unsupported nonzero offset.
- A native event from a different process/session/sample or failed source cannot refresh snapshots.
- Same socket/reader remains sole owner; parameter correlation/unarmed freshness and source failures must stop sends.
- Missing native reset/covariance/measurement evidence must remain unavailable rather than be manufactured for wire encoding.

### Task1: Calibration and managed source in actual capture

Files: existing kalibr_camera_consumption.py/px4_camera_source.py/capture_disarmed_sensors.py/capture_contract.py; new managed_capture_source.py and test_managed_capture_source.py.

Consumes: SHA-bound rig/artifact/native freeze and LiveEstimateNativeClient camera/fast output after successful send. Produces: concrete source owner with bounded snapshots, constructor checks and capture CLI/execution/worker selection.

- [x] Write failing integration tests for actual artifact parameters/pose, contract mismatch/config drift/nonzero refusal, source latching and actual capture factory/worker routing.
- [x] Implement the consumer/client/cache; exercise new tests plus necessary calibration/capture neighbors with prospective raw retention.

### Task2: Disarmed receiver lifecycle

Files: capture_wire_lifecycle.py/openvins_observed_wire_session.py; new disarmed_estimate_receiver.py and test_disarmed_estimate_receiver.py.

Consumes: same managed source and sole receiver's decoded messages/independent clock/owned PX4 descriptor. Produces: actual production receiver phase/read-only parameter request and explicit refusals for unavailable native wire data. No fake send/fusion success.

- [x] Test actual sole-owner integration and parameter/heartbeat correlation/failure/unknown reset refusal before sends; implement production routing.
- [x] One fresh source review of combined change, one bounded executor fix pass, necessary final verification. Report exact remaining runtime/fusion/offset blockers, publish only personal/PR65.
