# Trajectory and Gauge Contract Implementation Plan

> Execute inline with TDD under the standing authorization. Do not start a new physical run in this plan.

**Goal:** Freeze and verify an honest post-initialization trajectory gauge before any new supported-motion VIO study.

**Architecture:** A strict offline module validates ordered native states, exact-time physical reference, session/reset evidence, and the prospective motion profile. It selects the first internal state without truth, applies yaw-plus-translation only, reports startup unavailable and diagnostic errors, and keeps physical/fusion/flight claims false. A fixed-archive adapter projects sealed PR48 evidence without rerunning it.

**Tech stack:** Python 3.12, NumPy, SciPy Rotation, pytest, ZIP/JSONL.

### Task 1: Contract and analytic gauge

- [x] Write failing tests for immutable contract fields, first-internal selection independent of truth, noncommuting yaw/tilt, fixed scale/time, degenerate headings, and invalid numeric/quaternion inputs.
- [x] Implement strict 4DoF yaw/translation origin gauge with explicit JPL/Hamilton and FRD/FLU semantics.

### Task 2: State, time, session, and coverage audit

- [x] Write failing tests for exact integer-ns conversion, missing exact truth, duplicate/regressed samples, clock order, internal/public transitions, regular-update time, ZUPT labeling, reset/session changes, unknown quality, and incomplete duration.
- [x] Implement a conservative audit that separates diagnostic availability, accuracy screens, lifecycle/health qualification, and fusion/flight qualification.

### Task 3: Sealed PR48 projection

- [x] Verify archive SHA and all consumed member hashes before parsing.
- [x] Assert that origin selection remains 2.4 s when truth positions/errors are changed and that `[1.622,2.4)` remains startup unavailable.
- [x] Preserve incomplete capture, readiness failure, unknown reset/quality, uncalibrated covariance, and false qualification.

### Task 4: Verification and publication

- [x] Run focused tests, full regression, changed-file Ruff, whole-tree Ruff comparison, and diff check.
- [x] Record upstream versions/licenses/maintenance/resource/adaptation decisions and the single-agent review limit.
- [x] Seal code, tests, fixed-input audit, hashes, failures, and report in an indexed evidence ZIP.
- [x] Create and attach a stacked draft PR, then update the automation to the next physical preflight without rerunning PR48.
