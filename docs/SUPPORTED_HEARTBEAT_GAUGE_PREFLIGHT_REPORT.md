# Supported Heartbeat Gauge Preflight Report

## Outcome

The next supported-motion OpenVINS study now has a prepare-only, independently audited launch package. Its truth-independent trajectory policy is fixed before launch, its runtime file identity is included in the existing v3 binding, and the exact worker command uses the already qualified nullable launch environment and journaled heartbeat path.

No PX4, Gazebo, OpenVINS, training, ODOMETRY, arming, EKF2 injection, or physical simulation was started in this stage. Only `preflight_qualified` is true. Physical execution, runtime closure, VIO accuracy, estimator health, fusion eligibility, and flight readiness remain false.

## Contract

The design is recorded in `docs/superpowers/specs/2026-10-06-supported-heartbeat-gauge-preflight-design.md`; the executed plan is `docs/superpowers/plans/2026-10-06-supported-heartbeat-gauge-preflight.md`.

`trajectory-gauge-policy-v1` fixes the first internally initialized estimator state as the origin rule, yaw-plus-translation alignment, unit scale, zero time shift, exact timestamp matching, 3 s lateral-start offset, 25 s duration, public coverage, error screens, and offline-only truth scope. It names the anchor source as `immutable_readiness_anchor` and intentionally contains no numeric anchor. The existing run-specific `trajectory-gauge-contract-v1` will be instantiated only after the readiness subsystem records that immutable anchor.

`capture-execution-v3` retains every v2 workload, profile, input, timeout, hash, and launch-environment field and adds the policy's requested path, resolved path, byte count, SHA-256, and schema. Existing v1/v2 callers remain unchanged when no policy is supplied. Parent and worker validation reject malformed, duplicate, semantically changed, or drifting policy files before runtime-resource inspection. The worker records the same policy identity before active-resource scanning, and the runtime binding protects it in pre/post file snapshots.

## Dry-build evidence

All three attempts are retained:

1. `dry-v1` initially passed the first auditor, but self-review found that the declared capture script was relative. The strengthened auditor now rejects it as `command:absolute_executables`. It started no runtime process.
2. `dry-v2` used the absolute command and initially passed. A later source cleanup changed a file already covered by its baseline, so the final audit correctly rejects it as `binding:baseline`. It also started no runtime process.
3. `dry-v3` was generated after the final source change and passed the final independent dry audit with no failures.

The accepted `dry-v3` package contains 395 declared files in 107 roles. It retains `supported-ready-v1`, `substep-ready-v1`, and `ready-shadow-heartbeat-v1`; 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGBD; 300 s parent and supervisor budgets; the fixed OpenVINS input, native reference module, PX4 inputs, selected resource graph, launch environment, and runtime mapping declarations.

Accepted hashes are:

- study manifest: `9b076418dd5948f25a0de4b45945215f41c41cd6199c6c0f71e2216e91fe7d2b`;
- execution contract: `337794016a46f078f476ad9ead1ed28abb323e5544f87c0c3d36a651913e460f`;
- runtime binding: `42682dd5f3e0242524a568f3acbf6eaaab23d8191f3c09e355d0de863bcce831`;
- trajectory policy: `a97bc126e90e0bfb88cc995f782904a7a842e460854dbd71cec977cd98800463`.

The package consumes the qualified PR59 preparation directly. Its three source hashes are `c36fdab0ef13d5b3585644ae2419e0888f42d435daf078a08b610d87a6364675` for the binding, `819cbaa0974ed6eeb4f14b0a2b6d53bb28f8716bd5a87a9422fa56c1f69ba335` for the v2 execution contract, and `95ae6987eb14522fcc63a9de6be1ecfc0e136c3cd596be65ef6e1c34333427c2` for its study manifest.

## Verification

TDD retained the missing-module/API failures and then passed:

- 84 focused policy, execution, builder, and auditor tests;
- 1,290 full Python regression tests, with 3 skips and 2 existing warnings;
- Ruff on all changed Python files;
- `git diff --check`;
- whole-repository Ruff remains at the existing 53 findings in 34 files and is not claimed as passing;
- real WSL `dry-v3` audit: no failures and `preflight_qualified=true`.

Self-review added two material guards: prospective policy and concrete run anchor are separate, so a numeric truth-influenced anchor cannot be frozen prematurely; and executable/script paths must be absolute, so a later working-directory change cannot silently alter the declared launch.

The sealed evidence archive is `evidence/supported-heartbeat-gauge-preflight-dev-1701.zip`: 45 members including its manifest, 328,258 bytes, SHA-256 `a15246397ff5ed59bbe21a85a784acc7e93a1f4646d749cdfd4050e074b26061`. The embedded manifest records 44 payload members with byte lengths and SHA-256 values; ZIP CRC and manifest verification passed. Its producer commit is `2cf40dd14fca57bea3b3ba963267979cc5149777`. This publication paragraph postdates the sealed payload and does not alter it.

Review is published as draft [PR 61](https://github.com/chen7509/FlyDrones/pull/61), stacked on the trajectory/gauge contract in PR 60. This PR-link commit also postdates the immutable evidence payload.

## Evidence boundaries and next gate

The package does not repair PR48's incomplete 6.417 s run, its unknown reset/quality, or its uncalibrated covariance. It does not alter the retained PR37 drift failure, PR39 contact/undersampling diagnosis, PR40 startup failure, or the five-aircraft 0.873 RTF capacity failure. `raw-model-zero-bias-diffusion-v1` remains an uncalibrated development assumption.

The next step is one newly named physical `supported-ready-shadow-heartbeat-gauge-v1` attempt using the exact accepted command. Immediately before launch, the package and all referenced identities must be re-audited and relevant processes must be absent. The run must retain every failure and may not be retried blindly. Only after a complete trajectory, reliable public VIO, loss/reset/quality/covariance evidence, and safety gates pass may VIO-to-EKF2 injection be designed. Native Linux capacity comparison, HITL, hardware, and real flight remain external requirements.
