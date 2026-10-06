# Declared Launch Environment Report

## Outcome

The launch environment is now a prospective, executable part of the capture contract. The supervisor passes only the declared non-null entries to the worker, and the worker independently records its initial Linux environment before inspecting or starting runtime resources. A bounded real WSL child proved exact transport, including the difference between an absent variable and a present variable with an empty value.

This stage did not start PX4, Gazebo, OpenVINS, training, or a physical capture. It qualifies only the supervisor-to-worker environment transport. Physical-environment qualification, runtime-map coverage, runtime closure, VIO accuracy, estimator health, fusion eligibility, and flight readiness remain false.

## Design and implementation

The design is recorded in `docs/superpowers/specs/2026-10-06-declared-launch-environment-design.md`; the executed plan is `docs/superpowers/plans/2026-10-06-declared-launch-environment.md`.

The implementation:

- derives one deterministic nullable environment map from the validated v3 runtime binding and its sealed resource graph;
- preserves absent values as `null` and present-empty values as `""`;
- rejects malformed names, NUL bytes, mixed types, conflicting overlap, duplicate JSON keys, and declarations larger than 64 KiB;
- emits `capture-execution-v2` only when an explicit launch environment is supplied, retaining legacy v1 behavior and bytes otherwise;
- writes the exact declaration, materialization, execution-contract path, byte count, and SHA-256 before spawning the worker;
- invokes `Popen` with only the materialized map, so ambient parent variables are not inherited;
- parses the worker's original `/proc/self/environ` strictly and records it before active-resource inspection, generated scene copies, TestFixture, PX4, or OpenVINS;
- refuses any declaration, materialization, hash, worker observation, or terminal cleanup mismatch;
- keeps every broader qualification false in both runtime evidence and the independent auditor.

The fixed research basis was CPython 3.12.3, the official `subprocess.Popen(env=...)` contract and CPython source, plus Linux `execve(2)` and `environ(7)`. No dependency was added.

## Fixed preparation evidence

The first operator wrapper failed before the builder because shell output redirection targeted a parent directory that did not yet exist. The failure is retained in `prepare-command-failure.txt`; it started no runtime process.

The subsequent `dry-v1` preparation succeeded. It contains 19 declared environment keys, 12 materialized keys, an execution-contract SHA-256 of `819cbaa0974ed6eeb4f14b0a2b6d53bb28f8716bd5a87a9422fa56c1f69ba335`, and a runtime-binding SHA-256 of `c36fdab0ef13d5b3585644ae2419e0888f42d435daf078a08b610d87a6364675`. It fixes ordinary capture and supervisor limits at 300 seconds, declares `PYTHONPATH` absent, and preserves present-empty lookup variables such as `SDF_PATH`.

The retained PR58 online failure was projected through the new auditor without editing or rerunning it. The projection correctly fails because that historical study used execution-contract v1 and has no supervisor or worker environment records. Its physical and VIO conclusions remain unchanged.

## Real bounded harness

One new WSL harness was run through the production process-group supervisor. The parent intentionally contained hostile `PYTHONPATH`, `HTTP_PROXY`, and `LD_PRELOAD` values. The frozen declaration required those names to be absent in the child, while requiring a present-empty `SDF_PATH`.

The worker independently observed exactly these five materialized entries:

- `HOME=/home/yuchen7509`;
- `LANG=C.UTF-8`;
- `LC_ALL=C.UTF-8`;
- `PATH=/usr/bin:/bin`;
- `SDF_PATH=`.

The three hostile variables were absent. The contract SHA-256 was `1343773f57d9e603fbbe47b6ead6ae35a76fdbab4e3cd67a67aa4b862b6d75cb`. The child exited 0 with `capture_completed`. The owned original process group had no executing members, was absent after the leader was reaped, and received no SIGKILL. As in the existing supervisor contract, escaped descendants are outside this evidence and are not claimed as covered.

The independent audit reported no failures and set only `environment_transport_verified=true`. It kept physical environment, runtime mapping, runtime closure, VIO accuracy, estimator health, fusion, and flight claims false. A post-run process scan found no relevant remaining process.

## Verification

Implementation commits are:

- `9f6faee` design and plan;
- `a5a4702` exact nullable contract and builder integration;
- `5395ebf` supervisor and worker enforcement;
- `5b7f056` independent auditor;
- `52bb5b1` bounded real-child harness.

Verification results:

- focused environment, supervisor, builder, auditor, and harness tests: 90 passed, 1 Windows symlink skip;
- full Python regression with the current worktree `src` explicitly selected: 1,241 passed, 3 skipped, 2 existing warnings;
- Ruff on every changed Python file: passed;
- whole-repository Ruff: 53 findings in 34 files, equal to the PR58 base count; whole-repository lint is not claimed as passing;
- `git diff --check`: passed.

The sealed evidence archive is `evidence/declared-launch-environment-dev-1701.zip`: 38 members, 240,142 bytes, SHA-256 `58413476f5669e55c68b3da82dda70016b08513336a7ae274fd2ff6eacef6ceb`. Its embedded manifest records every payload member's byte length and SHA-256; ZIP CRC and manifest verification passed. The archive producer commit is `8289d5abf4f3eff5c1b926072d48dafa372cd195`. This publication paragraph postdates the immutable payload.

Self-review covered ambient leakage, absent-versus-empty semantics, overlapping declarations, worker-observation timing, partial evidence writes, spawn failure, timeout and cleanup preservation, v1 compatibility, PR58 historical projection, and overclaiming. No independent reviewer was used under the active single-agent constraint.

## Evidence boundaries

Verified:

- exact nullable environment declaration and materialization;
- real supervisor transport to a real Linux child;
- independent initial worker observation before runtime-resource work;
- conservative terminal auditing and bounded original-process-group cleanup.

Not verified in this stage:

- a physical PX4/Gazebo/OpenVINS launch under the new environment contract;
- full-load runtime-map coverage or runtime closure;
- VIO trajectory accuracy, health, reset, quality, or covariance calibration;
- fusion, arming, flight, training, or fruit-fly policy behavior.

Unchanged prior failures and blockers include the PR48 readiness rejection at 6.417 s with indeterminate VIO accuracy, the PR37 29.5355 m displacement-error lower bound, the old contact/undersampling diagnosis, the 0.873 five-aircraft camera RTF below the 0.95 gate, the uncalibrated `raw-model-zero-bias-diffusion-v1`, and the external requirements for native Linux comparison, HITL, hardware, and real flight.

## Next gate

Before another physical study, the trajectory/gauge contract must be fixed prospectively. OpenVINS became internally available only after lift began in PR48, so the next work must define startup-unavailable handling, the estimator gauge, frame alignment, scoring start and end, failure retention, and truth isolation before seeing a new trajectory. Truth may be used only for an external safety stop and offline scoring; it may not initialize or correct VIO.
