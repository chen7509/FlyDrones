# Estimator-Aware Readiness Preflight Report

## Result

The estimator-aware readiness route and its prepare-only physical-study package passed their focused tests, full regression, changed-file Ruff checks, and an independent package audit.

The new opt-in profile is `ready-shadow-heartbeat-estimator-v1`. It preserves the existing sensor and journaled unarmed-heartbeat gates and adds one causal requirement: a camera acknowledgement returned by the existing single OpenVINS native worker must report `internal_initialized=true`. Only then may the existing motion policy select its immutable future anchor at current simulation time plus 200 ms. The acknowledgement must be no more than two wall-clock seconds old.

This condition does not use Gazebo truth, `public_initialized`, later trajectory error, elapsed startup time alone, or error feedback. Internal initialization authorizes anchor selection only. It does not establish VIO accuracy, estimator health, quality, reset handling, covariance calibration, fusion, or flight readiness.

No OpenVINS, PX4, Gazebo, training, capture worker, or physics process was started in this stage. The generated command was not invoked and no `capture-v1` directory exists.

## Why this gate is needed

The retained PR48 supported-motion run selected its motion anchor at simulation time 1.622 s, while OpenVINS produced its first internal initialized state at 2.4 s. The frozen trajectory contract therefore could not define its required origin before motion and correctly classified accuracy as indeterminate. Repeating the same start condition would preserve that structural failure.

The new route keeps the same 8 s readiness deadline, 200 ms future anchor, 25 s study duration, 1 ms physics step, 250 Hz raw IMU, 10 Hz 160x120 RGB-D, 0.4 m two-second support lift, 26 N 1.6 s lateral excitation, original safety bounds, two-second source/native watchdogs, and 300 s wall/supervisor limits. It changes only the source fan-out profile and adds the pre-motion internal-state requirement.

## Implementation evidence

`ShadowInput` now retains the exact acknowledgement batch returned while consuming each source record. It clears the batch before the next source, keeps a successfully acknowledged prefix if a later native call fails, and does not alter the existing native request/response files.

`EstimatorAwareReadiness` validates the exact native acknowledgement schema, integer and clock types, causal clock order, sample/state equality, monotonic sequence and sample values, finite 16-element state, unit quaternion, two-second freshness, and the existing `fusion_eligible=false`, `quality=null`, and `reset_counter=null` claims. It journals immutable first evidence and refreshable latest evidence. Journal write, flush, close, concurrency, stale, malformed, duplicate, future, and partial-delivery cases are covered by tests.

The base fan-out gained a no-op post-shadow hook. Only the new subclass uses it, after the native worker has returned and before source readiness commits. Legacy `ready-shadow-v1` and `ready-shadow-heartbeat-v1` behavior remains unchanged.

The first generated `study-v1` package was not published after final source formatting changed one declared code identity. It is retained locally as superseded evidence and was not executed. The package was regenerated from the finalized bytes as `study-v2` and audited independently; this was a prospective evidence-drift refusal, not an OpenVINS, PX4, Gazebo, training, or fruit-fly failure.

## Prepare-only package

The fixed directory `results/estimator-aware-readiness-preflight-dev-1701/study-v2` contains exactly six files:

- `estimator-readiness-contract.json`: 7,705 bytes, SHA-256 `7fc0d8de6860f3b179c0e929568eed96be5db8c6c6bb17bfae89e0d3b30a8448`
- `execution-contract.json`: 4,445 bytes, SHA-256 `df4f193a6e079995836ceb6e8130bda5a8380e2a2ab6e06f212a7e24c6fcd80f`
- `lazy-runtime-contract.json`: 21,086 bytes, SHA-256 `caa64813b32cc19967e9c12365bcccbe4c62edbe065ae2a2538db4909a79b233`
- `runtime-binding-v3.json`: 472,784 bytes, SHA-256 `c3f3cbdb3644c80aa834493dfb9dc8119f5e27f1f2617f3cf0862ab7bca17505`
- `study-manifest.json`: 14,423 bytes, SHA-256 `34a8e7b92b3706bf4dc4ade4e3dbada0e50a62569b9f173ea8abecf840591801`
- `trajectory-gauge-policy.json`: 1,031 bytes, SHA-256 `a97bc126e90e0bfb88cc995f782904a7a842e460854dbd71cec977cd98800463`

The independent `estimator-aware-readiness-preflight-audit-v1` reported no failures and set only `prepare_qualified=true`. It recomputed the new binding, execution contract, command, code identities, source records, runtime-map preservation, and exact future destination. All physical execution, runtime closure, VIO accuracy, estimator health, fusion, and flight claims remain false.

PR63's historical study and audit are byte-matched to the sealed archive `evidence/openvins-lazy-runtime-prepare-dev-1701.zip`, SHA-256 `21f8f908549d6dc52c8717e9f6266fd43eca62787a90d2614986f6e5a34392bb`, including ZIP CRC verification. Its old mutable runtime baseline is explicitly recorded as no longer current after this code change. The new package does not relabel it as current; it snapshots a fresh prospective baseline containing all six readiness-route code files and the new contract.

## Upstream basis

The design continues to use OpenVINS commit `69488123ed9362dd44b6f28e7f4680abbff1442b` under GPL-3.0, PX4 commit `d6f12ad` under BSD-3-Clause, Gazebo Sim 8.15 under Apache-2.0, and the qualified oneTBB `v2021.11.0` allocator mapping under Apache-2.0. OpenVINS remains non-archived in the retained metadata but its last recorded push was 2025-11-30, so active 2026 maintenance is not claimed.

The implementation follows the fixed OpenVINS native acknowledgement and initialization semantics already exercised by the online shadow probe. Gazebo/PX4 lockstep timing and physical truth remain outside the estimator payload. The relevant primary references are the OpenVINS initialization report and evaluation documentation, PX4 simulation documentation, and Gazebo TestFixture/components documentation retained in the design record.

## Verification

- Focused route and package tests: 165 passed.
- Full regression: 1,374 passed, 3 skipped, with 2 existing warnings, in 240.30 seconds.
- Changed-file Ruff: passed.
- Tracked source-tree Ruff: 53 findings in 34 unchanged files, equal to the established baseline.
- `git diff --check`: passed; only existing CRLF normalization warnings were emitted.
- Independent fixed-package audit: no failures, `prepare_qualified=true`.
- The fixed study contains no `capture-v1` member or directory.

## Classification

**Verified:** strict acknowledgement validation, causal ordering, freshness and monotonicity, failure latching, journal behavior, estimator-aware fan-out order, exact worker forwarding, legacy route regression, archived PR63 source identity, fresh prospective runtime binding, profile-only behavioral contract change, and independent prepare-only audit.

**Implemented but not physically exercised:** the estimator-aware anchor gate in the capture worker and the generated future physical command.

**Not tested in this stage:** online estimator-aware heartbeat reconciliation, full 25 s supported motion, public VIO continuity and accuracy, loss/reset response, quality and covariance, ODOMETRY, EKF2 injection, arming, multi-aircraft behavior, training, or flight.

**Still failed or blocked:** PR48 remains a 6.417 s source-health refusal with indeterminate accuracy. PR37's 29.5355 m displacement-error lower bound, PR39's old contact/mixing result, PR40's startup failure, the five-aircraft 0.873 RTF capacity failure, and native-Linux, HITL, hardware, and flight dependencies remain unchanged.

## Next gate

The next bounded step is exactly one physical run of the generated command. It must preserve the declared workload and safety limits, keep every failure, and stop on any source, native, runtime-map, truth-reference, or estimator-readiness refusal. A successful full-duration run still must be audited for trajectory accuracy, public continuity, loss/reset behavior, quality, and covariance before ODOMETRY or EKF2 injection is allowed.
