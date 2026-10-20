# OpenVINS motion-intent physical retry report

## Result

The new `study-v23/capture-v1` run completed the full frozen 25 s disarmed
PX4/Gazebo workload. Before the first support force at the immutable 2.621 s
motion anchor, the safety gate used only the unarmed heartbeat and causal
internal OpenVINS state to send one native motion intent. The pinned OpenVINS
adapter acknowledged `has_moved_since_zupt=true` before that effective time.
Gazebo truth did not enter the estimator, motion gate or origin selector.

The correction removes the demonstrated false stationary update. The new run
contains zero ZUPT-labelled states after initialization and no accelerometer
bias corruption event. The same prospective four-degree-of-freedom gauge,
unit scale and zero time shift produce:

| Metric | Frozen limit | Result |
|---|---:|---:|
| Maximum position error | 0.25 m | **0.078755 m** |
| Terminal position error | 0.25 m | **0.020517 m** |
| Maximum velocity error | 0.25 m/s | **0.082112 m/s** |
| Maximum attitude error | 10 deg | **0.999105 deg** |
| Initial gravity-axis error | 5 deg | **0.004097 deg** |

This is a physical VIO accuracy-screen pass under the existing single-aircraft
development fixture. The earlier immutable `study-v21` result remains a
failure at 47.719487 m maximum/terminal position error and 4.058389 m/s maximum
velocity error. It has not been overwritten or reclassified.

## Completeness and feature evidence

The run retained 25,000 one-millisecond native-reference cycles, 50,000
pre/post physics records, 6,251 raw IMU samples, 251 RGB/CameraInfo/depth
records each, 24 unarmed heartbeats and one valid 7,516,767-byte PX4 ULog.
All 7,028 journaled source records committed to both consumers. OpenVINS
accepted 6,502 messages, including the one motion-intent message, and exited
zero. The original owned process group exited without SIGKILL and no relevant
FlyDrones/PX4/Gazebo/OpenVINS process remained.

OpenVINS produced 226 internal states and 222 public states. Public output
started at 2.8 s and continued through 24.9 s with a 100 ms maximum gap. The
standard upstream log records 222 MSCKF updates, 11 nonzero MSCKF updates using
23 features in total, and 222 SLAM updates, of which 209 were nonzero and used
6,473 features in total. This is markedly healthier than the prior failure
while preserving the frozen estimator thresholds, scene, sensor rates, noise
model, force waveform and camera resolution.

Native camera processing was 2.540 ms median, 3.376 ms P95 and 14.096 ms max.
Dispatch-to-acknowledgement was 3.952 ms median and 5.531 ms P95. The broader
camera callback/source-arrival to acknowledgement interval was 51.821 ms median
and 79.754 ms P95. These measurements exclude rendering and callback-before-
arrival time and are not the fruit-fly policy's decision latency.

## Qualification boundary

The trajectory screens pass, but estimator health remains open because the
current native contract still reports `quality=null`, `reset_counter=null` and
uses uncalibrated covariance/noise assumptions. Therefore fusion eligibility,
ODOMETRY publication, EKF2 injection, arming, flight, training and multi-
aircraft expansion remain false. The next dependency is explicit
quality/reset/covariance health and fault rejection under this passing workload.

The authoritative audit is
`results/estimator-physical-refusal-diagnosis-dev-1701/study-v23/final-audit-v2.json`.
It reports no failures, `physical_execution_qualified=true`,
`vio_accuracy_screens_qualified=true`, `estimator_health_qualified=false` and
`fusion_eligible=false`.

The sealed archive is
`evidence/openvins-motion-intent-physical-retry-dev-1701.zip`. It contains 706
members, is 16,271,317 bytes and has SHA-256
`0467cb57cf632bf540110d5981fc8d8e9778aa4ac9bd3d9f5bda55171f00fb96`.
ZIP CRC, unique member names and every manifest-listed member size/hash verify.
