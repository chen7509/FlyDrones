# PX4 SITL sensor-readiness and camera-capacity rerun

Date: 2026-09-30

## Decision

The five-vehicle PX4 sensor-readiness gate now passes 10/10 with a median real-time factor (RTF) of 0.999861 and a range of 0.001119. This authorized a new camera-capacity campaign through the fail-closed gate.

The camera campaign completed all 12 frozen slots, but it is **not eligible for production integration**. Its classification is `non_monotonic_or_inconclusive`: five slots had invalid evidence, and every valid slot missed the 0.95 RTF threshold. The valid no-subscriber renderer baseline was only 0.6032–0.6089 RTF, while the three valid native five-camera slots measured 0.5072–0.5087 RTF.

This is PX4 SITL plus Gazebo evidence on one Windows/WSL host. It is not HITL or real flight evidence. No policy training, loss change, reward change, or weight update was performed.

## EKF2 startup root cause

The earlier formal campaign passed nine starts and failed the tenth because all five EKF2 instances exceeded the 60-second health timeout. Comparing all ten runs showed a deterministic trend:

| Formal run | Mean first EKF2 output | First gyro integration interval |
|---:|---:|---:|
| 1 | 24.797 s | 471.952 s |
| 5 | 40.583 s | 786.936 s |
| 9 | 59.778 s | 1172.160 s |
| 10 | 65.773 s | 1281.313 s |

PX4 revision `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` runs the no-lockstep build against the host monotonic clock. `VehicleIMU::UpdateAccel` and `VehicleIMU::UpdateGyro` previously computed the first integration interval by subtracting the zero-initialized previous timestamp. The resulting hundreds-of-seconds first sample was accepted by the integrator and delayed EKF2 initialization in proportion to accumulated host uptime.

The pinned patch sets the first accelerometer and gyroscope integration interval to zero, using the first sample only as the integration baseline. Subsequent samples retain the original timestamp-difference behavior. The readiness build now binds the PX4 revision, patch SHA-256, patched `VehicleIMU.cpp` SHA-256, board configuration, and binary SHA-256 in a build attestation; launch fails closed if any value differs.

Across all 50 ULogs in the successful formal campaign, the first gyroscope integration interval is now 4.451–54.503 ms, with a median of 22.974 ms. The maximum value within the first ten samples is 66.605 ms. These values include host scheduling jitter but eliminate the former 472–1281 second first-sample error.

## Orchestration faults found during rerun

The first post-patch formal campaign, `formal-first-imu-dt-01`, was retained as an 8/10 invalid result:

- Run 7 falsely reported failed cleanup because the ownership cleaner waited only 10 ms after `SIGKILL` before recording the process as still alive.
- Run 9 launched all five Gazebo bridges concurrently; one PX4 instance remained at bridge initialization, leaving 4 of 20 sensor subscribers absent.

The cleanup logic now waits for process disappearance after forced termination. The sensor-readiness launcher starts each PX4 instance only after its four Gazebo sensor subscriptions are visible, then performs the existing all-vehicle barrier before resuming simulated time. A second development campaign passed at one, two, and five vehicles before the new formal campaign began.

## Successful formal gate

Campaign: `formal-first-imu-dt-02`

| Run | RTF | Evidence | Result |
|---:|---:|---|---|
| 1 | 1.000162 | valid | pass |
| 2 | 0.999871 | valid | pass |
| 3 | 1.000115 | valid | pass |
| 4 | 1.000215 | valid | pass |
| 5 | 0.999851 | valid | pass |
| 6 | 1.000246 | valid | pass |
| 7 | 0.999693 | valid | pass |
| 8 | 0.999579 | valid | pass |
| 9 | 0.999127 | valid | pass |
| 10 | 0.999610 | valid | pass |

Every run has 20/20 Gazebo sensor publishers, 20/20 PX4 subscribers, five healthy startup and post-window states, five nonempty hashed ULogs, no matched sensor timeout, complete owned-process cleanup, restored shared files, and a 30-second simulated scoring window within the 120-second wall limit.

## Gated camera-capacity result

Campaign: `first-imu-dt-camera-20260930-01`

The gate evidence binds the successful readiness summary and configuration by SHA-256. All 12 scheduled camera slots ran and were retained.

| Cell | Valid repetitions | Valid RTF values | Finding |
|---|---:|---|---|
| `idle-0` | 2/3 | 0.6089, 0.6032 | renderer baseline below real time |
| `native-1` | 2/3 | 0.6001, 0.5885 | single camera below real time |
| `native-5` | 3/3 | 0.5073, 0.5072, 0.5087 | five cameras repeatably near half real time |
| `python-5` | 0/3 | two scored windows at 0.5950 and 0.6134 were evidence-invalid | camera integrity/phase evidence failed |

Three slots failed during the legacy camera launcher's intermittent PX4/camera startup path, and two Python five-camera slots completed a timing window but failed camera integrity and phase evidence. Invalid slots are unscored for acceptance even when an RTF value exists.

The camera launcher now fails closed on the exact readiness-tested PX4 binary, board configuration, patch, and patched `VehicleIMU.cpp` hashes. The gated entry also verifies the build evidence in all ten readiness manifests before starting a campaign. This binding was added after the 12-slot run in response to independent review. A post-run check found PX4 build evidence in 9/12 slots; all nine used the exact readiness-tested binary, including every one of the seven evidence-valid slots. The three slots without build evidence are the retained startup failures and remain invalid.

The valid idle baseline already misses 0.95, so the current data cannot credit the native C++ observer as a production solution. The native five-camera results are highly repeatable but approximately 49% slower than real time. Production native integration and the dependent flight gate remain closed.

## Evidence

- Compact readiness evidence: [`docs/results/px4-sensor-readiness/20260930/formal-first-imu-dt-02`](results/px4-sensor-readiness/20260930/formal-first-imu-dt-02)
- ULog first-sample analysis: [`first-imu-dt-evidence.json`](results/px4-sensor-readiness/20260930/formal-first-imu-dt-02/first-imu-dt-evidence.json)
- Preserved first post-patch 8/10 summary: [`formal-first-imu-dt-01-failed-summary.json`](results/px4-sensor-readiness/20260930/formal-first-imu-dt-01-failed-summary.json)
- Compact camera evidence and raw artifact index: [`docs/results/camera-render-capacity/first-imu-dt-camera-20260930-01`](results/camera-render-capacity/first-imu-dt-camera-20260930-01)
- Camera authorization record: [`first-imu-dt-camera-20260930-01-gate.json`](results/camera-render-capacity/first-imu-dt-camera-20260930-01-gate.json)
- Readiness build binding: [`first-imu-dt-camera-20260930-01-build-binding.json`](results/camera-render-capacity/first-imu-dt-camera-20260930-01-build-binding.json)
- Camera PX4 binary post-check: [`first-imu-dt-camera-20260930-01-px4-binary-postcheck.json`](results/camera-render-capacity/first-imu-dt-camera-20260930-01-px4-binary-postcheck.json)
- Raw evidence remains local under `results/px4-sensor-readiness` and `results/camera-render-capacity`.

## Next work

1. Port the proven pre-resume, per-vehicle sensor-subscription barrier into the camera launcher and run a new development campaign. This must use a new campaign ID and frozen hash set; the completed 12-slot campaign remains immutable.
2. Profile the Gazebo D3D12 renderer and sensor system with zero, one, and five triggered depth sensors before changing observers. The 0.60 idle baseline shows that Python transport is not the primary bottleneck.
3. Test reduced camera resolution, rate, or rendering distribution only as separate product configurations. Do not describe a relaxed simulation profile as meeting the existing 160 × 120 at 10 Hz contract.
4. Repeat the 12-slot capacity gate only after the renderer baseline can sustain at least 0.95 RTF. HITL and real flight remain later stages.
