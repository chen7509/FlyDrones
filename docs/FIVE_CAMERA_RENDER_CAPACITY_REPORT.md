# Five-Camera Render Capacity Report

> Current update (2026-09-30): after fixing the PX4 first-IMU-sample defect, the gated campaign `first-imu-dt-camera-20260930-01` completed all 12 slots. It remains `non_monotonic_or_inconclusive` and is not production-integration eligible. Valid idle runs measured 0.6032–0.6089 RTF; valid native five-camera runs measured 0.5072–0.5087 RTF. Five slots had invalid startup or camera-integrity evidence. The gate now binds the exact readiness-tested PX4 binary, board configuration, patch, and `VehicleIMU.cpp`; a post-run check confirmed the same binary in every evidence-valid slot. See [`PX4_SENSOR_READINESS_REPORT.md`](PX4_SENSOR_READINESS_REPORT.md) and the [new compact evidence](results/camera-render-capacity/first-imu-dt-camera-20260930-01). The report below preserves the preceding `task7-frozen-20260929-234951` campaign for comparison.

Date: 2026-09-30

Campaign: `task7-frozen-20260929-234951`

Verdict: **inconclusive**

Root-cause code: `non_monotonic_or_inconclusive`

Production native integration eligible: **no**

## Decision

Do not integrate the native `schedule-observe` auxiliary into the production
flight gate. The frozen campaign contains all twelve immutable slots, but only
the first two reached a scored window. The remaining ten failed the concurrent
PX4 sensor-readiness gate before the observer and scheduler could start. The
campaign scorer therefore correctly reports `invalid_run_evidence` and cannot
compute the frozen cell medians, ranges, or native-minus-Python deltas.

The two valid runs also reject the current host as a real-time baseline. The
zero-sustained-camera `idle-0` run measured RTF 0.5575, and the one-camera
native run measured RTF 0.5792. Both are far below the frozen 0.95 threshold.
Moving the camera boundary from Python to C++ cannot be credited for a host
baseline that already misses real time without sustained camera subscriptions.

## Frozen system

- PX4 revision: `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`
- PX4 build: `px4_sitl_nolockstep`
- PX4 binary SHA-256: `d1e2b5eec3b061b45216facc7f3d95eb4387cbb3fff0a654ab013207119878f8`
- Native camera executable SHA-256: `c5d5275ad34118670a984532ace70eff797d9bf4969a4fdaebdb6fd45b331b85`
- Gazebo Transport: 13.6.0
- Gazebo Messages: 10.4.0
- Renderer profile: D3D12 NVIDIA under WSL
- Five PX4 vehicles, 4 ms physics step, 160 x 120 `R_FLOAT32` depth at 10 Hz
- Phase offsets: 0, 20, 40, 60, and 80 ms
- Scored window: 30 simulation seconds; wall timeout: 120 seconds
- RTF threshold: 0.95; phase-error p95 threshold: 8 ms

Every frozen source, model, runner, config, and executable hash matched before
the campaign started. Targeted capacity tests, native CTest, and the official
PX4 revision/build checks passed during preflight.

## Twelve-run result

| Seq. | Slot | Cell | Evidence | Scored RTF | Result |
|---:|---|---|---|---:|---|
| 1 | `capacity-01-idle-0-r1` | idle-0 | valid | 0.5575 | `rtf_below_threshold` |
| 2 | `capacity-02-native-1-r1` | native-1 | valid | 0.5792 | `rtf_below_threshold` |
| 3 | `capacity-03-python-5-r1` | python-5 | invalid | — | PX4 concurrent sensor readiness failed |
| 4 | `capacity-04-native-5-r1` | native-5 | invalid | — | PX4 concurrent sensor readiness failed |
| 5 | `capacity-05-native-5-r2` | native-5 | invalid | — | PX4 concurrent sensor readiness failed |
| 6 | `capacity-06-python-5-r2` | python-5 | invalid | — | PX4 concurrent sensor readiness failed |
| 7 | `capacity-07-native-1-r2` | native-1 | invalid | — | PX4 concurrent sensor readiness failed |
| 8 | `capacity-08-idle-0-r2` | idle-0 | invalid | — | PX4 concurrent sensor readiness failed |
| 9 | `capacity-09-python-5-r3` | python-5 | invalid | — | PX4 concurrent sensor readiness failed |
| 10 | `capacity-10-idle-0-r3` | idle-0 | invalid | — | PX4 concurrent sensor readiness failed |
| 11 | `capacity-11-native-5-r3` | native-5 | invalid | — | PX4 concurrent sensor readiness failed |
| 12 | `capacity-12-native-1-r3` | native-1 | invalid | — | PX4 concurrent sensor readiness failed |

Slots 3–12 record the same launcher failure: one or more PX4 instances did not
reach concurrent sensor readiness. Logs contain missing accelerometer,
barometer, gyro, and EKF2 data, including `Accel #0 fail: TIMEOUT!`. None of
those slots has a scored epoch or per-run `score.json`; each retained its
failed manifest and summary and consumed its scheduled identity.

Pre-merge review found that the historical campaign-level summary had assigned
derived performance labels to some of these unscored startup failures. Those
labels are preserved as provenance but are not measurements and do not support
the verdict. Amendment 46 changes future scoring so incomplete windows are
explicitly `unscored` with no performance failures; missing or non-finite camera
metrics are evidence failures and can never open the production-native gate.

Because each cell needs three valid repetitions, medians and ranges are not
defined. Native-minus-Python deltas are also not defined. Reporting such values
from the two valid slots or from empty startup failures would misrepresent the
experiment.

## Independent checks

RTF was independently recomputed from each valid slot's raw `clock-probe.csv`
and `scored-epoch.json`:

| Slot | Recorded RTF | Recomputed RTF | Absolute difference |
|---|---:|---:|---:|
| `capacity-01-idle-0-r1` | 0.5575 | 0.5586 | 0.0011 |
| `capacity-02-native-1-r1` | 0.5792 | 0.5804 | 0.0011 |

Both valid runs had accepted resource evidence. Idle Gazebo peak RSS was
577,921,024 bytes with 55 peak threads; native-one peak RSS was 581,570,560
bytes with 55 peak threads. Both reported 171 MiB peak GPU memory, with 2% and
1% peak sampled utilization respectively. These counters describe the WSL
D3D12 execution path; they do not establish native-GPU saturation.

All twelve slots retained five non-empty PX4 ULogs. All twelve report successful
owned-process cleanup and shared-file restoration. Post-campaign Windows and
WSL process checks found no remaining PX4, Gazebo, scheduler, observer, relay,
runtime-probe, or worker process.

## Development integration evidence

Before the formal campaign, the final Task 6 checks established that the
single-process native warmup transition works and that failures close safely:

- Native-one: one exact scored subscriber, 300 images at 10 Hz, valid evidence,
  phase-error p95 12 ms, RTF 0.5629, and complete cleanup.
- Native-five: five exact scored subscribers, 300–301 images per stream at
  approximately 10 Hz, zero integrity counts, zero median adjacent-spacing
  error, per-camera phase-error p95 values 12, 12, 8, 12, and 8 ms, RTF
  0.5414, and complete cleanup.
- Directed failure: exactly five trigger records, scheduler exit 4, native
  observer termination before readiness, zero scored seconds, no scored epoch
  or score, five ULogs, and complete cleanup/restoration.

These results are valid evidence of poor performance and jitter. They are not
evidence that the native boundary reaches the frozen real-time gate.

## Evidence locations

- Raw campaign:
  `results/camera-render-capacity/task7-frozen-20260929-234951/`
- Compact versioned evidence:
  `docs/results/camera-render-capacity/task7-frozen-20260929-234951/`
- Raw artifact index:
  `docs/results/camera-render-capacity/task7-frozen-20260929-234951/raw-artifact-index.json`

The raw index contains 396 omitted artifacts totaling 907,773,599 bytes. It
records every raw ULog, CSV, JSONL, log, configured world/model, marker, PID,
and nested startup-evidence file exactly once with byte size and SHA-256. The
snapshot verifier recomputed the complete file set, sizes, and hashes after
creation.

## Interpretation limits

Earlier near-real-time renderer evidence used short-lived subscriptions long
enough for renderer attestation. It did not measure five sustained depth
streams. The later sustained development trials measured roughly 0.54 RTF, but
the formal campaign could not reproduce enough valid slots to separate Python
transport overhead from sustained rendering cost.

This work is a computer simulation using Gazebo truth-based localization in
the existing stack. It does not prove camera-plus-IMU VIO, hardware in the
loop, radio/network scaling, physical camera timing, or real flight. No policy
weights, loss function, safety supervisor, flight dynamics, sensor contract,
or acceptance threshold changed. Task 8 and its conditional flight gate were
skipped because `production_integration_eligible` is false.

The next work package should diagnose and stabilize concurrent PX4 sensor
readiness and the host/Gazebo baseline before rerunning a new, separately
identified campaign. The current immutable campaign must not be resumed or
replaced in place.
