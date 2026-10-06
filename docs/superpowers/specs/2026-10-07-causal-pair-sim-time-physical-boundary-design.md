# Causal-pair simulation-time physical boundary design

## Purpose

Authorize at most one physical `study-v18/capture-v1` attempt after the camera-pair clock-domain correction and startup-only preflight. The boundary must fail before launching PX4, Gazebo or OpenVINS if the committed tree, sealed evidence, package audit, startup evidence, declared command, destination or resource state has changed.

## Frozen inputs

The boundary consumes the authoritative `study-v18` package, its committed-tree and after-startup audits, the startup dispatch/completion/audit, and `evidence/causal-pair-sim-time-retry-preflight-dev-1701.zip` with SHA-256 `c82a50d272acc80230e52763c53c3143dc71c093bb75281cd0d64fbd7d196e6b`. It recomputes the package audit from current files instead of trusting a saved boolean. It also re-audits the startup preflight and verifies the exact 25 s / 1 ms / 250 Hz / 10 Hz 160x120 execution contract, estimator inputs, profiles and unchanged 2 s wall watchdogs.

The physical command is exactly the manifest command for the absent `study-v18/capture-v1` destination. It may not contain `--startup-preflight`. The boundary, dispatch, completion and output records use exclusive creation and are immutable after first use. The boundary records the exact committed head and must be generated only after its implementation and tests are committed.

## Runtime behavior

Immediately before dispatch, the launcher revalidates the boundary against the same committed head, live package and startup audits, sealed archive, absent destination and empty resource scan. It writes a dispatch record before running the declared command, captures output, writes completion and performs a post-run resource scan. No automatic retry is allowed regardless of exit status.

The attempt keeps the existing vehicle, gravity, board textures, supported motion, lateral force, readiness anchor, trajectory gauge, OpenVINS binary/configuration, native reference and all safety/failure gates. It does not raise timeouts, repeat frames, reduce load, inject Gazebo truth, publish ODOMETRY, arm, or bypass PX4 or the safety supervisor.

## Interpretation

A completed process is not automatically a successful VIO run. The retained result must be audited for complete 25 s execution, runtime mapping, ULog, estimator initialization, health, reset/quality/covariance, trajectory-gauge accuracy, source loss and cleanup. Any earliest refusal remains evidence and is not retried. No outcome from this stage alone qualifies EKF2 injection, flight, multi-vehicle scaling, the complete fruit-fly policy, training speed or the open-source comparison.
