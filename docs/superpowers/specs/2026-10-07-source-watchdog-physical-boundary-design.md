# Source-watchdog corrected physical boundary design

## Purpose

Authorize at most one physical `study-v19/capture-v1` attempt after the source-watchdog startup-cohort correction and the successful startup-only preflight. This stage builds and audits the boundary only. It does not run PX4, Gazebo, OpenVINS or the declared physical command.

## Inputs and identity

The boundary binds the live committed Git HEAD, the authoritative `study-v19` package, its committed and post-startup package audit, the independent startup-preflight audit, startup dispatch/completion/supervisor evidence, and `evidence/source-watchdog-retry-preflight-dev-1701.zip` with SHA-256 `02055f4886eb0fe5cb2668506d393a2e631c703c93049c4a57a4b3f666196b6d`.

The archive is checked for CRC, unique names, manifest schema/count, every member size/hash and byte equality for the package/startup evidence consumed by the boundary. The package and startup audits are recomputed from live files. The startup audit must prove return code zero, only `postgraph`/`bootstrap` phases, empty PX4/OpenVINS owned phases, clean original owned-group cleanup and no physical artifacts.

## Fail-closed boundary

The exact manifest command must target the still-absent `study-v19/capture-v1`, must not contain `--startup-preflight`, and must retain the 25 s / 1 ms / 250 Hz / 10 Hz 160x120 workload, original estimator/native inputs and profiles, 300 s process limits, 10 s startup and unchanged 2 s operational source-health limits. All downstream claims remain false.

The boundary, dispatch, output and completion paths must all be absent. Active PX4, Gazebo, OpenVINS, training or test resources reject the boundary. Boundary and executor outputs use exclusive creation. A later executor must re-audit the boundary immediately before dispatch and can invoke the command at most once. Any failure or partial destination is permanent evidence and may not be overwritten or blindly retried.

## Limits

A passing boundary authorizes one attempt; it does not qualify physical execution, VIO accuracy or health, runtime closure, quality/reset/covariance, ODOMETRY, EKF2, arming, flight or fruit-fly policy performance. Those claims depend on the later immutable run evidence.
