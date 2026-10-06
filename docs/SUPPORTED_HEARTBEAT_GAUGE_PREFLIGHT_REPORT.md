# Supported Heartbeat Gauge Preflight Report

## Outcome

The next supported-motion OpenVINS study now has a prepare-only, independently audited launch package. Its truth-independent trajectory policy is fixed before launch, its runtime file identity is included in the existing v3 binding, and the exact worker command uses the already qualified nullable launch environment and journaled heartbeat path.

The first declared physical attempt stopped before PX4, Gazebo, OpenVINS, or physics started because the new trajectory-gauge code module was absent from the inherited PR59 file inventory. The environment and policy records passed, the failure was retained, and the original owned process group was cleaned without SIGKILL. This is a pre-runtime binding failure, not VIO, PX4 dynamics, training, or fruit-fly learning evidence. Physical execution, runtime closure, VIO accuracy, estimator health, fusion eligibility, and flight readiness remain false.

## Contract

The design is recorded in `docs/superpowers/specs/2026-10-06-supported-heartbeat-gauge-preflight-design.md`; the executed plan is `docs/superpowers/plans/2026-10-06-supported-heartbeat-gauge-preflight.md`.

`trajectory-gauge-policy-v1` fixes the first internally initialized estimator state as the origin rule, yaw-plus-translation alignment, unit scale, zero time shift, exact timestamp matching, 3 s lateral-start offset, 25 s duration, public coverage, error screens, and offline-only truth scope. It names the anchor source as `immutable_readiness_anchor` and intentionally contains no numeric anchor. The existing run-specific `trajectory-gauge-contract-v1` will be instantiated only after the readiness subsystem records that immutable anchor.

`capture-execution-v3` retains every v2 workload, profile, input, timeout, hash, and launch-environment field and adds the policy's requested path, resolved path, byte count, SHA-256, and schema. Existing v1/v2 callers remain unchanged when no policy is supplied. Parent and worker validation reject malformed, duplicate, semantically changed, or drifting policy files before runtime-resource inspection. The worker records the same policy identity before active-resource scanning, and the runtime binding protects it in pre/post file snapshots.

## Dry-build evidence

All three attempts are retained:

1. `dry-v1` initially passed the first auditor, but self-review found that the declared capture script was relative. The strengthened auditor now rejects it as `command:absolute_executables`. It started no runtime process.
2. `dry-v2` used the absolute command and initially passed. A later source cleanup changed a file already covered by its baseline, so the final audit correctly rejects it as `binding:baseline`. It also started no runtime process.
3. `dry-v3` passed its preflight audit, then its one physical attempt correctly refused before runtime because the inherited inventory did not include the newly imported `trajectory_gauge_contract.py`. The worker created no ULog and ran no physics. A fixed-input diagnostic reproduced exactly one missing project module.
4. TDD added the code module as a separate declared role and made the auditor require it. `dry-v4` passed the independent audit, and a fixed-input import/required-path diagnostic reported zero missing project modules.

The accepted `dry-v4` package contains 396 declared files in 108 roles. It retains `supported-ready-v1`, `substep-ready-v1`, and `ready-shadow-heartbeat-v1`; 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGBD; 300 s parent and supervisor budgets; the fixed OpenVINS input, native reference module, PX4 inputs, selected resource graph, launch environment, runtime mapping declarations, policy file, and policy implementation module.

Accepted hashes are:

- study manifest: `65848238aa5a40e87444a5f85e200760f0c77ff1f6a4602e4b32c25a45626013`;
- execution contract: `cc3b939d63de00b86f70f6e054d43300f4c507c2e316659f696909a19fbba707`;
- runtime binding: `ee339f1637addedf73bb3f03683ffc6fa396dc02033a63be367a527d646fdd20`;
- trajectory policy: `a97bc126e90e0bfb88cc995f782904a7a842e460854dbd71cec977cd98800463`.

The package consumes the qualified PR59 preparation directly. Its three source hashes are `c36fdab0ef13d5b3585644ae2419e0888f42d435daf078a08b610d87a6364675` for the binding, `819cbaa0974ed6eeb4f14b0a2b6d53bb28f8716bd5a87a9422fa56c1f69ba335` for the v2 execution contract, and `95ae6987eb14522fcc63a9de6be1ecfc0e136c3cd596be65ef6e1c34333427c2` for its study manifest.

## Verification

TDD retained the missing-module/API failures and then passed:

- 85 focused policy, execution, builder, and auditor tests after the missing-code-inventory fix;
- 1,290 full Python regression tests, with 3 skips and 2 existing warnings;
- Ruff on all changed Python files;
- `git diff --check`;
- whole-repository Ruff remains at the existing 53 findings in 34 files and is not claimed as passing;
- real WSL `dry-v4` audit: no failures and `preflight_qualified=true`;
- fixed-input required-path diagnostic: 16 current project inputs and zero absent from the `dry-v4` baseline.

Self-review added two material guards: prospective policy and concrete run anchor are separate, so a numeric truth-influenced anchor cannot be frozen prematurely; and executable/script paths must be absolute, so a later working-directory change cannot silently alter the declared launch.

The sealed evidence archive is `evidence/supported-heartbeat-gauge-preflight-dev-1701.zip`: 45 members including its manifest, 328,258 bytes, SHA-256 `a15246397ff5ed59bbe21a85a784acc7e93a1f4646d749cdfd4050e074b26061`. The embedded manifest records 44 payload members with byte lengths and SHA-256 values; ZIP CRC and manifest verification passed. Its producer commit is `2cf40dd14fca57bea3b3ba963267979cc5149777`. This publication paragraph postdates the sealed payload and does not alter it.

Review is published as draft [PR 61](https://github.com/chen7509/FlyDrones/pull/61), stacked on the trajectory/gauge contract in PR 60. This PR-link commit also postdates the immutable evidence payload.

## Evidence boundaries and next gate

The package does not repair PR48's incomplete 6.417 s run, its unknown reset/quality, or its uncalibrated covariance. It does not alter the retained PR37 drift failure, PR39 contact/undersampling diagnosis, PR40 startup failure, or the five-aircraft 0.873 RTF capacity failure. `raw-model-zero-bias-diffusion-v1` remains an uncalibrated development assumption.

The next step is the corrected physical `dry-v4` attempt using its exact accepted command. This is a root-cause-tested correction of the pre-runtime refusal, not a blind retry. Immediately before launch, the package and all referenced identities must be re-audited and relevant processes must be absent. The run must retain every failure. Only after a complete trajectory, reliable public VIO, loss/reset/quality/covariance evidence, and safety gates pass may VIO-to-EKF2 injection be designed. Native Linux capacity comparison, HITL, hardware, and real flight remain external requirements.
