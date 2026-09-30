# PX4 SITL sensor-readiness gate

Date: 2026-09-30

## Decision

The camera-capacity rerun is **not authorized**. The frozen formal gate required ten successful five-vehicle starts out of ten. The campaign produced nine valid passes and one invalid start, so the result is `inconclusive_or_invalid` and `camera_rerun_eligible=false`.

This work tests PX4 SITL and Gazebo on this Windows/WSL host. It is not HITL or real flight evidence. Gazebo `/clock` supplied simulated time, while RTF and startup time were measured against the host monotonic clock. No policy training, reward change, weight update, or autonomous-flight tuning was performed.

## Completed steps

1. PR #1 was merged into the fork integration branch `codex/hybrid-local-planner` at merge commit `8894add6a5cd817a2a7571d66c6e2e2edd6c99d0`.
2. A versioned no-camera sensor-readiness launcher and diagnostic were added for one, two, and five vehicles. The frozen camera/takeoff launcher and world generator remain byte-for-byte unchanged. The diagnostic records the Gazebo sensor publishers, PX4 subscribers, initial and post-window MAVLink health, EKF2 health, ULogs, Gazebo CPU/RSS/thread samples, simulation clock, cleanup, and restoration evidence.
3. The formal five-vehicle gate ran ten isolated starts with a 30-second simulated scoring window and a 120-second wall timeout.
4. The camera rerun was stopped by the gate. No new idle/one-camera/five-camera campaign was launched. Future reruns must use `tools/run_gated_camera_render_capacity_campaign_wsl.py`, which verifies the frozen readiness config and summary hashes and rejects anything other than the exact ten-slot formal pass before it invokes the legacy frozen camera runner.

## Startup diagnosis and correction

The first diagnostic batch could not run one- or two-vehicle cases because the world generator only accepted zero or five preloaded vehicles. That was an adapter defect; the failed batch remains preserved as `dev-20260930-01`.

The next batch showed a repeatable `Accel #0 fail: TIMEOUT!` on the last PX4 instance at every fleet size. The launcher restored the Gazebo clock before the final PX4/Gazebo bridge was ready. Moving the bridge barrier before clock resume fixed one- and two-vehicle starts, but made all five PX4 instances wait too long while simulation was paused.

The final sequence is:

1. Start Gazebo paused with all vehicle models preloaded.
2. Verify all IMU, magnetometer, GPS, and barometer publishers before starting PX4.
3. Start all PX4 instances without a per-instance serial publisher wait.
4. Wait for every PX4/Gazebo bridge.
5. Resume the world, witness one message on every sensor source, verify one publisher and one PX4 subscriber per source, then sample concurrent MAVLink health.

That sequence passed the final development campaign at every tested scale:

| Vehicles | Evidence | Sensor timeout | RTF |
|---:|---|---:|---:|
| 1 | valid/pass | 0 | 0.99971 |
| 2 | valid/pass | 0 | 0.99969 |
| 5 | valid/pass | 0 | 0.99951 |

These values are from `dev-20260930-05`, rerun after the readiness launcher and world generator were isolated from the legacy frozen camera inputs and after artifact-integrity checks became fail-closed.

## Formal gate result

Runs 1–9 had valid initial and post-window EKF2 health, five nonempty hashed ULogs per run, no matched sensor timeout, successful owned-process cleanup, restored PX4 shared files, and RTF above 0.95.

For the nine scored runs:

- RTF minimum: 0.998405
- RTF median: 0.999504
- RTF maximum: 0.999766
- RTF range: 0.001361, within the 0.03 repeatability limit
- Gazebo process: 55 threads in every scored run
- Peak Gazebo RSS: approximately 566–575 MB

Run 10 failed the startup-health gate. Gazebo delivered all 20 source streams and topic inspection found exactly 20 publishers and 20 PX4 subscribers. All five PX4 processes emitted ULogs and were cleaned up correctly, but all five startup-health records still reported `estimator_healthy=false` after the 60-second readiness window. The Gazebo clock advanced to about 66.5 simulated seconds, no `Accel/Gyro/BARO/MAG TIMEOUT` was recorded, and every PX4 log continued to report `ekf2 missing data`. This isolates the remaining intermittent fault to EKF2 initialization or delivery into PX4 after transport discovery, rather than camera rendering, port leakage, missing Gazebo publishers, or low RTF.

The failed tenth start is retained. It is not discarded or replaced by an extra successful run.

The original formal manifests and scores were produced by the first readiness scorer. They remain immutable. [`formal-20260930-01-amendment-v2`](results/px4-sensor-readiness/20260930/formal-20260930-01-amendment-v2) binds each original manifest and summary to the raw build, per-topic source/topology, per-process cleanup, and per-file restoration evidence by SHA-256, then replays all ten slots through the hardened scorer. The amendment independently reproduces nine valid passes, one invalid tenth run, `readiness_rate=0.9`, and `camera_rerun_eligible=false`.

## Evidence

Compact, reviewable evidence is under [`docs/results/px4-sensor-readiness/20260930`](results/px4-sensor-readiness/20260930). It includes every development campaign summary, the ten original formal manifests/summaries/scores, the hardened-scorer amendment with source hashes and embedded nested evidence, the failed run's five startup-health records, and the explicit step-4 gated-skip record. The gated camera entry was also exercised against the 9/10 summary: it rejected the summary before writing gate authorization evidence or creating a camera campaign directory.

Raw evidence remains local under `results/px4-sensor-readiness`. It includes approximately 1.05 GB of ULogs, console logs, Gazebo clock/resource/GPU samples, and all failed development attempts. Raw data is excluded from Git to avoid replacing or compressing original evidence into the repository.

## Required next work

The next work package should inspect the failed run's five ULogs for `estimator_status`, `vehicle_local_position`, `sensor_combined`, and `vehicle_imu` timing, and compare them with a passing run. It should add an explicit EKF2 initialization trace and a fail-closed check for simulator timestamp resets or data-age skew. The same frozen ten-run gate must then be executed under a new campaign ID. Camera capacity can resume only after a complete 10/10 pass; the old `task7-frozen-20260929-234951` campaign remains unchanged.
