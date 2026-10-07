# OpenVINS to EKF2 file-only shadow report

Date: 2026-10-08

Branch: `codex/estimator-aware-physical-diagnosis`

Review: draft PR 65

## Decision

Task 3 of the staged OpenVINS-to-EKF2 plan passes in the frozen Gazebo/PX4 simulation domain. Actual retained IMU, camera, native request and native acknowledgement records produce ordered file-only ODOMETRY candidates. The receiver-rate shadow passes at 10 Hz, and an independently qualified native propagation stream produces unique file-only candidates at 50 Hz.

This result does not publish MAVLink ODOMETRY, access or change PX4 parameters, inject data into EKF2, arm the aircraft, run policy training, or authorize multi-aircraft testing. Every candidate records `fusion_eligible=false`. The covariance remains uncalibrated on hardware, HITL and real flight.

## Implemented path

- `OfflineEkf2Composer` remains the sole owner of positive camera health, estimator reset, quality, covariance profile and session state. Callers cannot supply those fields.
- `FileOnlyEkf2ShadowEvidence` is attached to the existing `ShadowInput` path and exposes no transport API. It records capture sample, source arrival, dispatch, native receive/start/end and acknowledgement clocks separately.
- The retained-source replay validates every reconstructed causal IMU/camera action against the original native request and acknowledgement identities and validates RGB bytes against the original request hash.
- The normal replay monkeypatches socket construction to fail. The implementation writes JSONL only; it cannot create a MAVLink endpoint.
- The fast producer aligns native prediction targets to the absolute 20 ms grid. It requires a distinct later IMU boundary and a visual update no older than 100 ms. It never repeats camera state to manufacture rate.
- Fast 12-state covariance is independently bounded and transformed to the 9-state PX4 geometry. Camera covariance qualification is not inherited by the propagated stream; a separate prospectively frozen cohort is required.

## Preserved development failures

Two development failures were retained and no held-out seed was consumed for either one.

1. `results/openvins-ekf2-fast-physical-dev-1701/development-seed-27401` used a fast grid inherited from the first 1 ms IMU sample. Of 1,109 public samples, 221 reached 101 ms visual age against the frozen 100 ms limit. The gate failed before held-out dispatch.
2. `results/openvins-ekf2-fast-aligned-physical-dev-1701/development-seed-27501` corrected the phase, but the old evidence builder still required a hard-coded 1,250 predictions. The causal 20 ms to 24.98 s grid correctly contains 1,249 predictions because the first estimate needs a received IMU and the final target must precede a later IMU boundary. The gate again failed before held-out dispatch.

The final builder derives the exact expected grid from the first retained IMU and exclusive simulation end. These failures are integration/auditor failures, not fruit-fly learning failures.

## Prospective propagated covariance cohort

The accepted cohort is `results/openvins-ekf2-fast-grid-physical-dev-1701`. Before any result, it froze implementation commit `cdfef28f25873faa3b24bfc3b22382e1846c7c65`, aligned native binary SHA-256 `97a1af94a9e5b29fa00a42ed1eba4e39a29ee732a524506fb95491ae236f24de`, thresholds, profile, development seed 27601 and held-out seeds 27611, 27612 and 27613. Test-set tuning was forbidden.

All four cases kept the existing workload and safety boundary: 25 seconds, 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGB-D, the same vehicle, gravity, support/lateral force, watchdogs and unarmed gate. Each run completed with 1,249 unique native predictions and 1,109 public scored samples.

|Run|Max position error (m)|Max velocity error (m/s)|Max attitude error (deg)|Terminal position error (m)|
|---|---:|---:|---:|---:|
|development 27601|0.066513|0.057666|0.905376|0.024348|
|held-out 27611|0.065474|0.058363|0.900182|0.018387|
|held-out 27612|0.065224|0.022079|0.943258|0.016397|
|held-out 27613|0.077579|0.081423|0.979000|0.017274|

The development gate passed before held-out dispatch. The exact predeclared held-out audit then evaluated 3,327 samples. All nine attitude, position and body-velocity components had 3-sigma coverage `1.0`; the minimum coverage was `1.0`, the maximum consecutive violation count was `0`, and no run was discarded. `fast-cohort-audit.json` therefore records `propagated_covariance_sim_domain_qualified=true`, `hardware_covariance_calibrated=false` and `fusion_eligible=false`.

The retained ULog SHA-256 values are:

- development 27601: `bb84abacfecb838c1a21cec6c0dc9116a2a4a2216882ff519fb7799e87299c2c`;
- held-out 27611: `cb26498e91084c4fad568cf311d4676fa70bc31cce2055b85ab33102dfb28e50`;
- held-out 27612: `6394ff4c559e70feeb34c473dc481cb2d53dd29f2667f3e1fd2a988f4685e035`;
- held-out 27613: `123d10c818aa43b5f3b8ff027e8cfabc6a149e56060b9e0cf8a1c162727b938a`.

## Real-source file-only replay

The accepted replay is `results/openvins-ekf2-file-shadow-dev-1701-v2`. Its manifest was created at commit `773d123` before the four cases and freezes the journal, native request/ack files, native binary/config, runtime binding and all replay/integration/health source files.

|Case|Observed behavior|Result|
|---|---|---|
|normal|6,501 retained IMU/camera actions consumed exactly; 222 unique 10 Hz candidates; 28 initialization refusals; all clocks retained separately|Pass; receiver rate true, fusion rate false|
|source loss at 8 s|2,080 actions consumed; 52 earlier candidates retained; quality latched `-1`; 4,421 later actions not replayed|Expected fail-closed pass|
|native timeout at 12 s|3,122 actions consumed; timeout latched before the selected camera acknowledgement; quality `-1`; later source delivery stopped|Expected fail-closed pass|
|session replacement at 12 s|all 6,501 actions consumed; two health sessions; reset total/counter `1`; 222 candidates|Pass|

An earlier normal replay in `results/openvins-ekf2-file-shadow-dev-1701` is preserved as failed. Its exact 10 Hz sequence exposed an auditor bug: `zip(strict=True)` was incorrectly applied to adjacent lists whose lengths naturally differ by one. The corrected adjacent-pair check has a dedicated regression test; no source estimate was changed.

After both camera and propagated covariance gates passed, `results/openvins-ekf2-fast-file-shadow-dev-1701` produced 1,109 unique file-only 50 Hz candidates from 2.82 s through 24.98 s. Each candidate uses its own native state and covariance, a real later IMU boundary, and the latest authoritative positive camera health/reset state. The result records `propagated_shadow_rate_qualified=true`, `network_odometry=false`, `hardware_covariance_calibrated=false` and `fusion_eligible=false`.

## Evidence boundary

|Status|Evidence|
|---|---|
|Verified|Pinned coordinate/covariance math; authoritative health/reset composition; actual retained source/request/ack file replay; 10 Hz receiver shadow; source-loss, native-timeout and session-replacement latching; prospective 50 Hz physical covariance cohort; 50 Hz file candidates; preserved runtime bindings, ULogs and failures.|
|Implemented only|Transport-neutral ODOMETRY fields and in-memory pymavlink round-trip from Task 2; no live clock synchronization or sender.|
|Not tested|MAVLink endpoint, TIMESYNC convergence, PX4 `vehicle_visual_odometry`, EKF2 innovations/fusion, parameter rollback, HITL, hardware or flight.|
|Still failed or blocked|Five-camera WSL2 capacity remains 0.873 RTF below 0.95. Hardware covariance and raw IMU calibration remain unavailable. Historical PR37/PR39/PR40 failures remain retained.|

The next permitted stage is Task 4: prepare a reversible, disarmed PX4 receiver-only study. That stage may research and implement preflight, TIMESYNC, parameter snapshot/rollback and ULog acceptance rules, but it still may not transmit ODOMETRY or change PX4 parameters. Task 5 remains a separately authorized network/PX4 mutation stage.

## Sealed evidence and verification

The curated evidence archive is `evidence/openvins-ekf2-file-shadow-dev-1701.zip` (23,589,918 bytes, 248 members including its internal manifest), SHA-256 `d834874a46f8eedb6c2a0518036aa08dbe26a92ceeeacc8c1a8a9730bb77bdae`. The companion summary is `evidence/openvins-ekf2-file-shadow-dev-1701-manifest.json`. The archive contains the accepted physical and file-only evidence, retained development failures, ULogs, source and test inputs, terminal audit and verification output; it does not replace the full untracked raw result directories.

The final repository test run completed with `1,946 passed, 3 skipped` and two previously known warnings. Changed-file Ruff checks and `git diff --check` passed. `results/openvins-ekf2-task3-terminal-audit.json` records an empty failure list and `task3_qualified=true`, while separately retaining `network_odometry=false`, `px4_parameter_access=false`, `hardware_covariance_calibrated=false`, `fusion_eligible=false` and `flight_ready=false`.
