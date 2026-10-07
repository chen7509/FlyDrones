# OpenVINS Health Contract Report

Date: 2026-10-07

Branch: `codex/estimator-aware-physical-diagnosis`

Review: draft PR 65

## Decision

The fixed `px4-d6f12ad-gate-floor-v1` covariance profile is qualified only for the frozen Gazebo/PX4 simulation domain used by this study. The result does not calibrate the raw IMU model or the covariance on hardware, HITL, or a real aircraft. Fusion remains disabled: no ODOMETRY was published, no data was injected into EKF2, the vehicle stayed unarmed, and no training or multi-aircraft run was started.

This stage authorizes design of the next VIO-to-EKF2 shadow integration. It does not authorize flight or positive fusion quality on hardware.

## Implemented contract

- Quality is fail closed: `-1` means failed, `0` means unknown or not yet qualified, and `1` is the only positive value. It is not a percentage score.
- A native OpenVINS camera acknowledgement carries the read-only 15x15 IMU-state covariance. Python validates its shape, finite values, symmetry, positive semidefiniteness, timestamp order, source health, and estimator session identity.
- Estimator process replacement creates a new session, increments the absolute reset total once, and derives the one-byte reset counter from that total. Reused or rolled-back sessions are rejected.
- The health state machine never changes OpenVINS state, PX4 state, the physical model, or the safety supervisor. Gazebo truth is used only by isolated offline scoring.
- The physical source-loss and restart adapters operate after raw sensor journaling, so the original raw record remains available. Both failures stop motion through the existing readiness and pre-step safety gates.

The physical health binary is `online_probe-health-v1`, SHA-256 `188e886b72224762dcb9418d1b9409237cc46862701320266c8dbe86419618d2`.

## Fixed replay and fault matrix

The fixed-input matrix retained seven profiles: normal, IMU silence, camera silence, truncated image, timestamp regression, processing timeout, and process restart. All seven matched their predeclared outcome. Faults latched quality `-1`; the normal replay remained quality `0` because the covariance profile was not yet simulation-qualified; process restart produced two clean native sessions and reset total `1`. Network output, ODOMETRY, and fusion remained false. The audit is `results/openvins-health-contract-dev-1701/fault-matrix-audit-v1.json`.

## Physical covariance cohort

The accepted cohort is `results/openvins-health-physical-dev-1701-v2` and kept the existing load unchanged: 25 seconds, 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGB-D, the same vehicle, gravity, support/lateral force, watchdogs, unarmed gate, and safety thresholds.

The development run used seed 27201 and produced 222 public health samples. Its trajectory gate passed with:

- maximum position error: 0.065985 m;
- maximum velocity error: 0.022883 m/s;
- maximum attitude error: 0.945080 degrees;
- terminal position error: 0.013385 m.

The held-out seeds 27211, 27212, and 27213 each completed once and contributed 222 samples. Across 666 samples, all nine attitude, position, and velocity components had 3-sigma coverage `1.0`; the maximum consecutive violation count was `0`. The frozen thresholds required at least `0.99` coverage and at most `4` consecutive violations. `cohort-audit.json` therefore records `covariance_sim_domain_qualified=true`, `hardware_covariance_calibrated=false`, and `fusion_eligible=false`.

The exact post-run `cohort-audit-manifest.json` was materialized after the runs. Qualification is retained because the earlier `cohort-manifest.json` fixed every run ID, role, seed, profile, and prohibited test-set tuning; the profile constants and the 0.99/max-4 auditor thresholds were committed before dispatch; and every runtime binding froze matching hashes of the health contract, cohort auditor, and preflight code. The post-run manifest introduced no selectable run, threshold, or profile degree of freedom. If this provenance boundary is rejected, the correct remedy is a new four-run cohort whose exact audit manifest is materialized before dispatch; the present result must then be treated as nonqualifying rather than rewritten.

The earlier `results/openvins-health-physical-dev-1701` attempt failed at 10 ms because the readiness adapter did not yet accept `imu_covariance15`. It remains preserved as a failed attempt and is not part of the passing cohort.

## Physical source-loss and restart evidence

The accepted fault cohort is `results/openvins-health-physical-faults-dev-1701-v3`. Its complete preflight manifest was created before either result. Both runs were deliberately expected to end as `capture_failed`, because the safety supervisor must stop after source loss or estimator replacement invalidates the established readiness anchor.

- Seed 27311 dropped the first estimator-side IMU sample at 8 s while preserving raw capture. It latched `source_loss:imu`, health quality `-1`, and reason `source_failure`. The native process exited cleanly, PX4 exited `0`, ULog was retained, heartbeats remained unarmed, the owned group was empty afterward, and fusion remained false.
- Seed 27312 replaced the native process at 8 s. Both native sessions exited `0`; the second accepted a new-session sample; the health contract recorded session count `2`, reset total/counter `1`, and readiness recorded one session replacement. The established motion readiness was intentionally lost, so the pre-step safety gate stopped the run. Runtime mapping observed `ready` and `prestop` for both native processes. PX4 exited `0`, ULog was retained, heartbeats remained unarmed, cleanup was complete, and fusion remained false.

`fault-audit.json` independently checks the preflight identities and hashes, seed application, raw record presence, ULog headers, unarmed heartbeat bits, runtime binding, both native sessions, reset evidence, fail-closed reasons, cleanup, and absence of fusion/ODOMETRY authority.

Two earlier fault rounds remain preserved. The first preflight failed before simulation because the runtime binding schema did not yet declare the second OpenVINS process role. In the next round, source loss was first detected indirectly by the causal camera wait, and restart correctly lost readiness but contradicted the then-predeclared expectation of completion. Neither round is counted as accepted fault evidence. The final v3 profiles changed the source-loss detection to the first dropped estimator sample and predeclared restart as a fail-closed capture failure before dispatch.

## Verification and remaining limits

The targeted health, capture, runtime-binding, preflight, executor, and fault-auditor suites pass. The final repository-wide verification passes 1,879 tests with 3 skips and 2 existing warnings. Changed-file Ruff and `git diff --check` pass. The sealed archive and its CRC/SHA verification are recorded beside `evidence/openvins-health-contract-dev-1701.zip`.

Still unresolved outside this stage:

- `raw-model-zero-bias-diffusion-v1` is a simulation assumption, not a hardware IMU calibration.
- No HIL/HITL or real flight result exists.
- No VIO ODOMETRY has been published to PX4 and no EKF2 fusion behavior has been tested.
- The single-aircraft gate must precede any 5-aircraft or 20-aircraft expansion. The existing five-aircraft camera capacity result remains 0.873 RTF, below the unchanged 0.95 threshold.
- Full fruit-fly learning, decision, division-of-labor, latency, collision, fault-recovery, and fair upstream baseline comparison remain separate downstream work. The health-contract result is not evidence that those stages are complete.
