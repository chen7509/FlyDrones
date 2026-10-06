# Supported Heartbeat Gauge Preflight Report

## Outcome

The next supported-motion OpenVINS study now has a prepare-only, independently audited launch package. Its truth-independent trajectory policy is fixed before launch, its runtime file identity is included in the existing v3 binding, and the exact worker command uses the already qualified nullable launch environment and journaled heartbeat path.

Three declared integration attempts were retained. The first two stopped before PX4, Gazebo, OpenVINS, or physics because the inherited PR59 inventory omitted worker-imported modules. The corrected `dry-v5` package passed its preflight audit and reproduced the complete static worker input list, but its physical attempt was safely stopped at 10 ms simulation time when the OpenVINS process mapped an undeclared lazy runtime dependency, `/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2.11`. No estimator state was accepted, no ULog was produced, and no support or lateral force was applied. These are runtime binding failures, not VIO accuracy, PX4 dynamics, training, or fruit-fly learning evidence. Runtime closure, VIO accuracy, estimator health, fusion eligibility, and flight readiness remain false.

## Contract

The design is recorded in `docs/superpowers/specs/2026-10-06-supported-heartbeat-gauge-preflight-design.md`; the executed plan is `docs/superpowers/plans/2026-10-06-supported-heartbeat-gauge-preflight.md`.

`trajectory-gauge-policy-v1` fixes the first internally initialized estimator state as the origin rule, yaw-plus-translation alignment, unit scale, zero time shift, exact timestamp matching, 3 s lateral-start offset, 25 s duration, public coverage, error screens, and offline-only truth scope. It names the anchor source as `immutable_readiness_anchor` and intentionally contains no numeric anchor. The existing run-specific `trajectory-gauge-contract-v1` will be instantiated only after the readiness subsystem records that immutable anchor.

`capture-execution-v3` retains every v2 workload, profile, input, timeout, hash, and launch-environment field and adds the policy's requested path, resolved path, byte count, SHA-256, and schema. Existing v1/v2 callers remain unchanged when no policy is supplied. Parent and worker validation reject malformed, duplicate, semantically changed, or drifting policy files before runtime-resource inspection. The worker records the same policy identity before active-resource scanning, and the runtime binding protects it in pre/post file snapshots.

## Dry-build evidence

All dry builds and integration attempts are retained:

1. `dry-v1` initially passed the first auditor, but self-review found that the declared capture script was relative. The strengthened auditor now rejects it as `command:absolute_executables`. It started no runtime process.
2. `dry-v2` used the absolute command and initially passed. A later source cleanup changed a file already covered by its baseline, so the final audit correctly rejects it as `binding:baseline`. It also started no runtime process.
3. `dry-v3` passed its preflight audit, then its one physical attempt correctly refused before runtime because the inherited inventory did not include the newly imported `trajectory_gauge_contract.py`. The worker created no ULog and ran no physics. A fixed-input diagnostic reproduced exactly one missing project module.
4. The first correction added only `trajectory_gauge_contract.py`. `dry-v4` passed its original dry audit but its physical attempt again refused before runtime: calling the existing `estimator_inputs` validator imported `openvins_online_shadow.py` and `openvins_causal_input.py`, which the older PR59 builder had discovered only after it froze project inputs. No PX4, Gazebo, OpenVINS, ULog, or physics ran.
5. A second TDD correction replaced the single-file assumption with one explicit prospective worker-policy code closure containing all three modules and made the auditor require the exact list. `dry-v5` passed the independent audit. A probe outside the repository reproduced the worker's pre-binding imports and fixed required list: all 39 selected inputs were present and none were missing.
6. The `dry-v5` physical attempt passed the declared baseline, launch-environment, policy, and static worker-input gates. It reached 10 ms of simulation, then the owned OpenVINS runtime-map check rejected one exact undeclared mapping: `/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2.11` (device `08:30`, inode `238769`). The OpenVINS executable identity remained stable and there were no mismatched declared mappings. The run remained `capture_failed`; it is not a partial success.

The accepted `dry-v5` package contains 398 declared files in 108 roles. It retains `supported-ready-v1`, `substep-ready-v1`, and `ready-shadow-heartbeat-v1`; 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGBD; 300 s parent and supervisor budgets; the fixed OpenVINS input, native reference module, PX4 inputs, selected resource graph, launch environment, runtime mapping declarations, policy file, and the exact three-file prospective worker-policy code closure.

Accepted hashes are:

- study manifest: `d61103c014da2b2cbd7d16fc43d4a149df324126c57837b6d4d2b4368e808581`;
- execution contract: `bd7c9cea0359518c3cd2a19fea6cf9ea2c8e8a953acdbca1e786c795855e82a4`;
- runtime binding: `7be9deb4e50e78a32d6634fc5613b979eefccebbf0b221594658175a3adfe5cc`;
- trajectory policy: `a97bc126e90e0bfb88cc995f782904a7a842e460854dbd71cec977cd98800463`.

The package consumes the qualified PR59 preparation directly. Its three source hashes are `c36fdab0ef13d5b3585644ae2419e0888f42d435daf078a08b610d87a6364675` for the binding, `819cbaa0974ed6eeb4f14b0a2b6d53bb28f8716bd5a87a9422fa56c1f69ba335` for the v2 execution contract, and `95ae6987eb14522fcc63a9de6be1ecfc0e136c3cd596be65ef6e1c34333427c2` for its study manifest.

## Verification

TDD retained the missing-module/API failures and then passed:

- 85 focused policy, execution, builder, and auditor tests after the missing-code-inventory fix;
- 1,290 full Python regression tests, with 3 skips and 2 existing warnings;
- Ruff on all changed Python files;
- `git diff --check`;
- whole-repository Ruff remains at the existing 53 findings in 34 files and is not claimed as passing;
- real WSL `dry-v5` audit: no failures and `preflight_qualified=true`;
- external fixed-input required-path diagnostic: 39 current worker-selected inputs and zero absent from the `dry-v5` baseline.

The final physical attempt produced no accepted native state, no committed fan-out record, no ULog, and no force or support step. The source fan-out retained five refusals after the native client rejected the runtime mapping. The PX4 child required an internal SIGKILL during its own cleanup (`px4_exit_code=-9`); separately, the outer recorded supervisor sent no SIGKILL to its original owned process group, reaped its zombie leader, and observed that group absent afterward. These are distinct cleanup facts and do not establish coverage of escaped descendants. A post-run process scan found no remaining relevant PX4, Gazebo, OpenVINS, capture, test, or training process.

Self-review added two material guards: prospective policy and concrete run anchor are separate, so a numeric truth-influenced anchor cannot be frozen prematurely; and executable/script paths must be absolute, so a later working-directory change cannot silently alter the declared launch.

The sealed evidence archive is `evidence/supported-heartbeat-gauge-preflight-dev-1701.zip`: 45 members including its manifest, 328,258 bytes, SHA-256 `a15246397ff5ed59bbe21a85a784acc7e93a1f4646d749cdfd4050e074b26061`. The embedded manifest records 44 payload members with byte lengths and SHA-256 values; ZIP CRC and manifest verification passed. Its producer commit is `2cf40dd14fca57bea3b3ba963267979cc5149777`. This publication paragraph postdates the sealed payload and does not alter it.

Review is published as draft [PR 61](https://github.com/chen7509/FlyDrones/pull/61), stacked on the trajectory/gauge contract in PR 60. This PR-link commit also postdates the immutable evidence payload.

## Evidence boundaries and next gate

The package does not repair PR48's incomplete 6.417 s run, its unknown reset/quality, or its uncalibrated covariance. It does not alter the retained PR37 drift failure, PR39 contact/undersampling diagnosis, PR40 startup failure, or the five-aircraft 0.873 RTF capacity failure. `raw-model-zero-bias-diffusion-v1` remains an uncalibrated development assumption.

Further physical retries are stopped. The next gate is a separate lazy-runtime-mapping closure research and design stage, beginning with the exact TBB allocator mapping above. It must establish the installed TBB package and binary provenance, loader behavior, license and maintenance status, resource cost, and a prospective declaration/test contract that can detect required lazy mappings before another physical run. The retained `dry-v5` failure may be used as fixed diagnostic input, but it must not be rewritten or presented as a completed VIO run. Only after that independent gate passes may a newly named physical study be frozen and attempted. Only after a complete trajectory, reliable public VIO, loss/reset/quality/covariance evidence, and safety gates pass may VIO-to-EKF2 injection be designed. Native Linux capacity comparison, HITL, hardware, and real flight remain external requirements.
