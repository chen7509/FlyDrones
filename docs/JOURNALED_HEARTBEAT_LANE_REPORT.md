# Independent heartbeat observation and queued reconciliation

## Scope and implementation
Adds opt-in ready-shadow-heartbeat-v1; ready-shadow-v1 behavior remains unchanged. The existing receiver writes/flushes actual heartbeat identity to heartbeat-observations.jsonl under the shared force gate, then submits the identical event to the existing source queue. The source/native thread later reconciles ordered heartbeat identity without replacing the newer readiness observation with an older queued one. This is observation evidence, not a native acknowledgement or fsync durability.

No additional receiver/native thread, no reordered sensor queue, no TTL increase. IMU/RGB/CameraInfo still require prior successful native/source delivery and2s freshness. Native packet2s and source2s remain; at most32unreconciled heartbeat observations, oldest receipt limited to2s. Hidden native/readiness failure, missing/changed/out-of-order receipt, armed/future/stale/invalid source, journal failure and close failure fail closed. A flush that blocks until arrival expires cannot commit readiness. Journal failure is latched before releasing the force gate. A step already in progress before failure may finish; no real-time filesystem guarantee.

## Research
Pinned PX4d6f12ad BSD3: HEARTBEAT configured constant1Hz; MavlinkStream schedules from hrt_absolute_time. GZBridge sets PX4 clocks from Gazebo sim time; drv_hrt uses lockstep scheduler under ENABLE_LOCKSTEP_SCHEDULER. Four installed inspected sources byte-match pinned source; current build.ninja/compile_commands contain the lockstep define. This is current source/build evidence, not a reconstruction of missing PR48 runtime hashes. Installed unrelated VehicleIMU/submodule changes are recorded. Nominal1Hz must not be called wall1Hz.

Use existing Python3.12.3 locks/receiver/readiness rather than adding ROS/DDS services. One small journal and bounded pending deque add I/O/memory; no performance improvement claimed. Versions/licenses/metadata/resource and rejected alternatives in research.md and source manifests. OpenVINS paper remains estimator background, not proof of heartbeat gate safety.

## Fixed failure-time projection
Producer e8bf8a8 consumed two members of sealed PR48 archiveSHA07a2a247b87ff43304ec4c0fe787640264772ad12c272b354d5a5116cdecaeb2. Six original heartbeat identities are mapped to a synthetic heartbeat-only0..5sequence. Observations occur at recorded arrival times on a virtual clock; existing recorded sensor-readiness rows are seeded, not reprocessed by an estimator. At the original readiness-check time, old queued-HB proof is unavailable while independently journaled new-HB proof is available. All6projected receipts reconcile; a deliberately injected downstream sink failure then rejects a synthetic gated callback.

This projection does not prove that real journal I/O completes promptly, that PX4/Gazebo will finish25s, or that VIO is accurate. It is not native replay, measured latency, training, physical simulation or flight. The original capture remains failed. No physical/estimator process launched this stage.

## Verification and remaining gates
Initial module-absentRED, then24unitGREEN; added3RED for blocking-journal expiry and missing opt-in CLI/receiver helper, then105targeted testsGREEN across lane/fanout/readiness/native transport. Atomic failure against waiting force and constructor close coverage included. First blocked-native test mistakenly changed source owner thread and correctly failed; test was corrected to retain one source owner, without weakening production ownership. Full regression and independent review recorded below when complete.

Future physics still requires tested agreement of prospective/enforced timeouts, a complete declared runtime snapshot including Gazebo/Python bindings and PX4 startup/environment inputs, and an independently planned initialization/trajectory comparison origin. Missing PR48 pre-run hashes cannot be backfilled. If slow simulation itself produces wall gaps>2s, report the platform limit; do not loosen the guard or attribute it to fly learning. Original25s/1ms/250Hz/10Hz/forces/anchor/safety unchanged. Quality/reset unknown, covariance uncalibrated; fusion=false, no ODOMETRY or arming. Earlier failures and five-camera0.873RTF<0.95 remain.

## Independent review
NoCritical/Minor;1Important reconciliation-flush deadline hole reproduced(1failed,29passed): the observation was popped before postflush expiry checking. Fixed by rechecking while the original dequehead remains; expired identity retained and subsequent gated action refused. Final106targetedGREEN. A heartbeat_reconciled journal row records identity matching; only successful source_delivery plus failure-free terminal state establishes that the route committed. The fixed projection used producer e8bf8a8 before this final deadline hardening; no repeat of that projection or any estimator/physical run after the fix.

Current compile_commands entries for drv_hrt.cpp, mavlink_main.cpp and GZBridge.cpp each explicitly contain ENABLE_LOCKSTEP_SCHEDULER; retained commands are build evidence, not historical runtime provenance. PX4metadata nonarchived,lastpush2026-10-05T22:53:15Z.

## Final verification
Final regression: 1051 passed, 2 existing loader warnings, 289.00 seconds. Changed-file Ruff and git diff whitespace checks pass. Whole-repository Ruff remains failed: 52 findings across 33 files unchanged from base49cf775; this stage does not claim a clean repository-wide lint result.

Verified: synthetic failure/concurrency gates and fixed virtual-time identity projection. Implemented but not physically validated: receiver journal integration. Not tested here: online native estimator, supported-motion repeat, VIO accuracy, EKF2 fusion, training or flight. Historical physical failures remain unchanged.

## Publication
Draft PR49: https://github.com/chen7509/FlyDrones/pull/49. Exclusive evidence archive evidence/journaled-heartbeat-lane-dev-1701.zip: 46 members, 657389 bytes, SHA256 0f5887c7a835c96a6045bc5b7be851f978f523f11323f0eccfd8074fd24c158c. Every member hash and CRC verified. Sealed source14e8f21; archive commitc7496ff. Later publication metadata does not rewrite the archive.
