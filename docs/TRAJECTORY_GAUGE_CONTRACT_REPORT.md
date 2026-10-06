# Trajectory and Gauge Contract Report

## Outcome

The supported-motion trajectory now has a prospective, testable gauge that remains valid when OpenVINS initializes after lift begins. Origin selection is the first internally initialized state in the estimator session and never consults truth or later errors. The alignment removes only global translation and yaw; it fixes scale and time and preserves gravity-axis and attitude error.

The sealed PR48 failure was projected through this stricter contract without rerunning physics or the estimator. Its first internal state remains fixed at 2.4 s. Since the motion anchor was 1.622 s, the preceding 778 ms is explicitly `startup_unavailable` and is not scored. The partial post-origin diagnostic passes the previously fixed development thresholds, but the capture, public-state coverage, reset/quality, covariance, post-origin trajectory, full-motion trajectory, health, fusion, and flight gates remain false.

This stage is offline only. It did not start PX4, Gazebo, OpenVINS, training, ODOMETRY, arming, or EKF2.

## Research and selection

The design is in `docs/superpowers/specs/2026-10-06-trajectory-gauge-contract-design.md`; the implementation plan is `docs/superpowers/plans/2026-10-06-trajectory-gauge-contract.md`. The dated source and decision record is preserved in `results/trajectory-gauge-contract-dev-1701/research.md`.

| Candidate | Version and maintenance observation | License | Interface, cost, and decision |
|---|---|---|---|
| OpenVINS | fixed `69488123ed9362dd44b6f28e7f4680abbff1442b`; GitHub reports non-archived, last push 2025-11-30 | GPL-3.0 | Reuse the sealed `q_GtoI, p_IinG, v_IinG, bg, ba` producer. No estimator rebuild or new process. Maintenance in 2026 remains uncertain. |
| evo | observed head `9690a0cbf6ab6fe03ccc4a4d9d05bd9f36bccbe2`, 2026-10-05; non-archived | GPL-3.0 | Use its documented APE/RPE and origin/Umeyama distinctions as evaluation references. Reject a new dependency and whole-trajectory, scale, or time fitting for this short prerequisite. |
| NumPy/SciPy Rotation | existing project dependencies | BSD-family | Adopt for constant-size quaternion/matrix operations. Processing is linear in the small saved trajectory and adds no online load. |

OpenVINS' JPL `q_GtoI` is numerically interpreted by Hamilton tooling as IMU-to-estimator-global. The camera state velocity is `v_IinG`, a global velocity; it is deliberately kept separate from the body velocity emitted by `fast_state_propagate`. Reference orientation is FLU-to-world and is converted offline to BODY_FRD-to-world with `diag(1,-1,-1)`. PX4 `LOCAL_FRD` position and `BODY_FRD` velocity remain the separate PR33 wire contract; this audit emits no message.

## Contract

The contract freezes these choices before a new trajectory exists:

- origin is the first internally initialized state in the immutable estimator session;
- the origin must occur by the fixed lateral-excitation start `anchor + 3 s`;
- any interval from the anchor to a later origin remains unavailable and cannot be filled or passed retrospectively;
- yaw is fixed from the two horizontal body-x headings at the origin, translation is fixed at the origin, scale is one, time shift is zero, and no later alignment is allowed;
- initial gravity-axis error is measured after yaw alignment, so roll/pitch disagreement is not removed by the gauge;
- estimator time converts to integer nanoseconds within one nanosecond and must exactly match the camera sample; truth association is exact, with no nearest-neighbor or interpolation fallback;
- internal/public flags, processing clocks, state time, and regular-update time are monotonic; public initialization cannot precede internal initialization or revert;
- the ZUPT latch is reported as a flag and is not mislabeled as a count of accepted zero-velocity updates;
- a known reset must remain absent in the single scored session; unknown reset/quality and uncalibrated covariance keep health and fusion false.

The module rejects malformed or duplicate JSON, unsafe or duplicate ZIP members, manifest/hash mismatch, duplicate or regressed samples, nonfinite or oversized vectors, invalid quaternions, impossible processing clocks, state/sample mismatch, missing exact truth, initialization reversion, degenerate headings, changed session evidence, and output overwrite.

## PR48 fixed-evidence result

The input is `evidence/supported-online-vio-dev-1701.zip`, SHA-256 `07a2a247b87ff43304ec4c0fe787640264772ad12c272b354d5a5116cdecaeb2`. The adapter verifies ZIP CRC plus the byte length and SHA-256 of all six consumed members against the embedded manifest before parsing.

The authoritative projection is `results/trajectory-gauge-contract-dev-1701/pr48-audit-v4.json`. Earlier projections are retained: review first renamed the overly broad `accuracy_screens_pass` field, then separated post-origin from full-motion qualification, and finally added per-row reset/quality plus cross-row clock/initializer checks. No input or metric changed.

- 65 camera state rows; 41 internally initialized; 37 public;
- origin 2.4 s, selected as the first internal state without truth;
- first public state 2.8 s; maximum observed public spacing 100 ms;
- startup unavailable from 1.622 s to 2.4 s, duration 778 ms;
- 41 exact state/reference matches;
- maximum yaw/translation-aligned position error 0.102411083 m;
- terminal position error 0.015603018 m;
- maximum global velocity error 0.150661283 m/s;
- maximum attitude error 0.967500451 degrees;
- initial gravity-axis error 0.006404594 degrees;
- maximum rotation-invariant displacement-error lower bound 0.040369875 m.

These values pass the fixed partial diagnostic thresholds. They do not qualify the run: it ended at 6.42 s instead of 25 s, public coverage did not reach 24.9 s, reset and quality are unknown, covariance is uncalibrated, and the readiness failure remains. `post_origin_trajectory_qualified`, `full_motion_trajectory_qualified`, `trajectory_qualified`, `estimator_health_qualified`, `fusion_eligible`, and `flight_ready` are all false. Even a future complete post-origin result cannot make `full_motion_trajectory_qualified` true while startup remains unavailable.

The new 4DoF result is stricter than the old full-attitude exploratory comparison. It may report a larger position error because roll/pitch are no longer absorbed into the alignment. This is an intended correction, not estimator regression.

## Verification

Implementation commits before final publication are:

- `87bc5a8` design and plan;
- `44012d1` strict contract, analytic gauge, archive projection, and tests.

Verification results:

- trajectory/gauge analytic and fixed-archive tests: 21 passed;
- focused trajectory, prior gauge, odometry-frame, state-diagnostic, and execution-contract tests: 138 passed;
- full Python regression with this worktree's `src` explicitly selected: 1,262 passed, 3 skipped, 2 existing warnings;
- changed-file Ruff: passed;
- whole-repository Ruff: 53 findings in 34 files, equal to base `5b442aa`; whole-repository lint is not claimed as passing;
- `git diff --check`: passed.

The initial TDD run failed at import because the new module did not exist. The first implementation then exposed an internal validation defect: the strict vector helper rejected its own NumPy slices. That failure was retained in the stage ledger and the helper was fixed without weakening scalar type, finite, magnitude, shape, or quaternion checks.

Self-review covers JPL/Hamilton direction, global versus body velocity, FLU/FRD conversion, yaw-only alignment, truth-independent origin selection, unavailable startup, exact time association, cross-row receive/start/end ordering, initializer and regular-update monotonicity, per-row reset/quality changes, archive provenance, incomplete-run handling, output overwrite, and broad-claim defaults. No independent reviewer is available under the active single-agent constraint.

The sealed evidence archive is `evidence/trajectory-gauge-contract-dev-1701.zip`: 32 members, 62,089 bytes, SHA-256 `a4d02e4c8a96fb272d463bcbb5d8b773b2836a3f7266f56c67c80a68a5918ecc`. Its embedded manifest records every payload member's byte length and SHA-256; ZIP CRC and manifest verification passed. The PR48 source archive is referenced by hash and is not duplicated. The producer commit is `0842750f39819a9a4ab218ef891f0967ebbe3644`; this publication paragraph postdates the immutable payload.

## Evidence boundary and next gate

Verified here: the contract logic, exact sealed-input provenance, and the PR48 partial diagnostic under a truth-independent first-internal-state gauge.

Still failed or unqualified: PR48's 25 s completion/readiness, public end coverage, reset/quality/covariance health, VIO-to-EKF2, flight, fruit-fly policy learning, and the 0.873 RTF five-aircraft camera gate. PR37's 29.5355 m old-condition error lower bound, PR39's ground/contact undersampling evidence, and PR40's startup failure remain separate retained results.

The next physical candidate must be a newly named `supported-ready-shadow-heartbeat-gauge` study. Before it can start, its builder must include this gauge contract and PR59's execution-environment v2 in the same declared command/runtime binding, freeze the actual 300/300-second limits and full runtime resources, and pass a dry audit. The one physical attempt must keep the original 25 s / 1 ms / 250 Hz / 10 Hz 160x120 workload, motion, watchdog, safety, truth-isolation, and failure-retention rules. It will simultaneously test the previously offline-only journaled heartbeat lane, full runtime mapping, and this gauge; no old run may be rewritten or retried under its old name.
