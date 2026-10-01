# Five-Camera Render Capacity Report

> Current update (2026-10-01): profiler-led work found that PX4's default
> Gazebo server configuration loaded `custom::GstCameraSystem` even though the
> test world contains depth cameras and no matching regular `/image` stream.
> Its topic-list and regular-expression search repeated every simulation
> update. Removing only that unused plugin through a private, attested
> run-scoped server config removed the sampled GStreamer hot path. A valid
> exploratory trial measured 0.8574 RTF, but the exact final-code run measured
> 0.7895; their range exceeds the 0.03 repeatability limit, so no stable RTF
> improvement is claimed. A profiled run measured 0.8507 RTF, with Gazebo
> Transport discovery and DART physics becoming the leading sampled costs. The
> 0.95 gate remains closed. See the
> [compact profiler evidence](results/camera-render-capacity/renderer-profiler-20261001-01).
>
> The preceding audit found that the historical
> `idle-0` cells had zero depth-image subscribers but still triggered all five
> cameras at 10 Hz. They were not true zero-render baselines. The scheduler now
> changes from the five-camera attestation phase to the selected scored trigger
> count before the scored epoch. Corrected Ogre2 development trials measured
> 0.7798–0.8349 RTF with zero steady triggers, 0.7024 with one camera, and
> 0.5135 with five cameras. An independently attested Ogre1 zero-trigger trial
> measured 0.7567 RTF, so Ogre1 was rejected before expanding to one and five
> cameras. The formal 0.95 gate remains closed and the 12-slot campaign was not
> rerun. See the [compact renderer diagnosis](results/camera-render-capacity/renderer-diagnosis-20260930-01).

## Renderer activation diagnosis

### Profiler-led server-plugin result

The first scored-window profile captured 13,683 `cpu-clock:u` samples. The
unused `libGstCameraSystem.so` accounted for about 7.32% self samples;
`custom::GstCameraSystem::findCameraTopic()` accounted for 5.53% cumulative
samples. Local source inspection at the frozen PX4 revision showed that
`PostUpdate` called `findCameraTopic()` until initialization, while
`findCameraTopic()` listed every topic and applied a regular expression that
matches a regular camera `/image` topic. This depth-only world never satisfies
that match. PX4's upstream server configuration and GStreamer plugin are
available in the official
[server config](https://github.com/PX4/PX4-Autopilot/blob/main/src/modules/simulation/gz_bridge/server.config)
and [GStreamer plugin documentation](https://github.com/PX4/PX4-Autopilot/blob/main/src/modules/simulation/gz_plugins/gstreamer/README.md).

The corrected launcher can now create a private server config for a development
trial, remove `custom::GstCameraSystem`, and pass its exact path and SHA-256 to
the renderer attester. The attester reads the running Gazebo process
environment, parses the bound config, rejects a remaining forbidden plugin
entry, and rejects a mapped `libGstCameraSystem.so`. The shared PX4
`server.config` is never edited.

| Trial | Evidence | RTF | Result |
|---|---|---:|---|
| Ogre2, zero triggers, GStreamer disabled, exact final code | valid | 0.7895 | below 0.95 |
| same retained behavior, earlier exploratory runner | valid | 0.8574 | below 0.95; not hash-identical |
| same configuration under `perf` sampling | valid | 0.8507 | 10,906 samples, zero lost |
| Bullet Featherstone, GStreamer disabled | valid | 0.8232 | rejected; slower and teardown segfault |
| DART PGS, GStreamer disabled | valid | 0.7732 | rejected; slower |
| SceneBroadcaster disabled | invalid/unscored | — | rejected; PX4 could not discover the Gazebo world |

The two unprofiled no-GStreamer measurements span 0.0678 RTF, above the 0.03
repeatability limit. The no-GStreamer profile no longer contains the former
plugin hot path, but this host variance prevents a stable performance-gain
claim. Its cumulative samples were led by Gazebo Transport publisher discovery (43.31%),
Physics update (29.13%), DART forward step (23.10%), and subscriber-change
handling (12.91%). SceneBroadcaster `PostUpdate` was 2.78%, Sensors
`PostUpdate` 2.09%, and `RenderUtil::UpdateFromECM` 1.00%. These percentages
span multiple Gazebo threads and do not add into a single critical-path
percentage; they identify where further native-Linux tracing should focus.

The Bullet and PGS branches were not kept in production code. Removing
SceneBroadcaster was also not kept because it broke the PX4/Gazebo interface.
The only retained behavior is the explicit depth-only option that removes the
unused GStreamer plugin with runtime proof. It does not change vehicle
dynamics, the camera model, rate, resolution, PX4, EKF2, or thresholds.

The latest evidence separates three loads that the preceding campaign mixed
together:

| Rendering state | Engine | Steady camera triggers | RTF | Evidence |
|---|---|---:|---:|---|
| renderer not initialized; PX4 readiness campaign | Ogre2 default path | 0 | 0.9999 median | formal 10/10 readiness pass |
| renderer initialized after five-stream attestation | Ogre2 | 0 | 0.8349 | valid development evidence |
| renderer initialized after five-stream attestation | Ogre2 | 0 | 0.7798 | valid development repeat |
| renderer initialized | Ogre2 | 1 at 10 Hz | 0.7024 | valid development evidence |
| renderer initialized | Ogre2 | 5 at 10 Hz | 0.5135 | valid development evidence; phase p95 also exceeded 8 ms |
| renderer initialized after five-stream attestation | Ogre1 | 0 | 0.7567 | valid development evidence |

All five development trials used the same five PX4 vehicles, no-lockstep PX4
binary, dynamics, world, depth resolution, camera rate, D3D12 NVIDIA adapter,
30 simulation-second window, and 0.95 threshold. The two Ogre2 zero-trigger
repetitions differ by 0.0551, above the 0.03 repeatability limit. Every run
retained five ULogs and reports successful owned-process cleanup and shared-file
restoration.

This isolates a large fixed cost after the Gazebo rendering sensor system is
activated, followed by additional cost for each sustained camera stream. It is
not a learning-policy, weight, loss-function, PX4 flight-control, or EKF2
training failure. Sampled NVIDIA utilization remained 0–3% while Gazebo used
roughly two CPU cores, so the current WSL path is CPU/synchronization limited in
this test; sampled utilization alone does not prove that the GPU is idle at
every instant.

The Ogre1 trial loaded `libgz-rendering8-ogre.so.8.2.3` and produced all five
160 × 120 depth streams at 10 Hz during attestation. It therefore tests a real
Ogre1 depth path rather than only a command-line flag. Gazebo emitted a
segmentation-fault stack during commanded teardown, after the scored window;
the trial still preserved a complete score and clean ownership/restoration
evidence. This is an additional robustness concern and another reason not to
adopt Ogre1.

The result agrees with the upstream Gazebo Sensors implementation: its source
contains a performance TODO explaining that the render-event connection forces
scene-tree updates at the simulation update rate. Camera sensors suppress image
generation without consumers, but that does not remove the initialized Sensors
system's scene-update path. See the upstream
[Gazebo Sensors system](https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/sensors/Sensors.cc),
[CameraSensor](https://github.com/gazebosim/gz-sensors/blob/gz-sensors8/src/CameraSensor.cc),
[DepthCameraSensor](https://github.com/gazebosim/gz-sensors/blob/gz-sensors8/src/DepthCameraSensor.cc),
and [Gazebo rendering troubleshooting](https://github.com/gazebosim/docs/blob/master/harmonic/troubleshooting.md).

An exact-source isolation experiment then tested that TODO against Gazebo Sim
8.15.0 tag commit `446a44335a45b704b4d36dabcc5508ee34eeb3d8`.
The final development plugin kept event updates unthrottled while the world was
paused for camera startup, capped event-only scene refreshes at 10 Hz after
resume, and left pending camera triggers unthrottled. Renderer attestation
proved the exact custom library path and SHA-256 from the Gazebo process map.
A post-run audit recovered the private server config from the owned run
directory and confirmed its exact Sensors entry, but the original runtime
attestation did not bind that config path and hash. The 0.7301 RTF and 98.85
Gazebo CPU seconds are therefore retained as **diagnostic-only**, not
evidence-valid under the amended gate. They provide no reason to adopt naive
event throttling, while the incomplete binding prevents a formal root-cause
claim. Future custom-plugin runs now require attestation to prove the live
Gazebo process's `GZ_SIM_SERVER_CONFIG_PATH`, bind its config hash and exact
Sensors entry, and preserve the config. The reproducible development diff is
[`sensors-render-event-throttle-10hz.patch`](../patches/gz-sim8/sensors-render-event-throttle-10hz.patch).

Three rejected precursors are also retained: fully suppressing event-only
updates prevented triggered-camera service readiness; search-path-only plugin
selection loaded the system library and was rejected by attestation; and
simulation-time throttling during the paused startup phase prevented the
trigger handshake. None produced a score. These failures constrain any future
upstream patch: it must preserve paused-world initialization and triggered
camera discovery as well as real-time performance.

The next admissible work is a native-Linux runtime comparison or profiler-led
work below the Sensors event gate, covering `RenderUtil::Update`, scene
synchronization, and the WSL D3D12 driver path. It must
first reach at least 0.95 RTF with the renderer initialized, zero steady
triggers, and a repeatability range no greater than 0.03. Only then should the
one-camera, five-camera, and frozen 12-slot campaign be repeated. Resolution,
rate, vehicle count, dynamics, and thresholds must remain unchanged while
diagnosing the platform.

The original `first-imu-dt-camera-20260930-01` campaign still completed all 12
slots after the PX4 first-IMU-sample fix. Its historical 0.6032–0.6089
`idle-0` values now mean **zero subscribers with five cameras still being
triggered**, not zero rendering. Its native five-camera values remain
0.5072–0.5087. The campaign remains `non_monotonic_or_inconclusive` and is not
production-integration eligible. See [`PX4_SENSOR_READINESS_REPORT.md`](PX4_SENSOR_READINESS_REPORT.md)
and the [formal compact evidence](results/camera-render-capacity/first-imu-dt-camera-20260930-01).

The report below preserves the preceding `task7-frozen-20260929-234951`
campaign for comparison.

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
