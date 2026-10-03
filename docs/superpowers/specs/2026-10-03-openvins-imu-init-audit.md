# Frozen OpenVINS IMU feed and initialization audit

The clone-motion audit found a large translation discrepancy but did not identify
its cause. Audit the existing textured development flight without another PX4,
Gazebo, OpenVINS replay, training run, or parameter change. The result is an
input and initialization diagnosis, not a VIO pass or a flight gate.

Use the frozen PX4 ULog, exported `sensor_combined` CSV, OpenVINS runner source,
configuration, successful replay log and state CSV. Pin SHA-256 for each input.
Compare every exported timestamp and six IMU values to the ULog in order; do
not use a sampled spot-check. Account for the PX4
[SensorCombined](https://docs.px4.io/main/en/msg_docs/SensorCombined) contract:
FRD body angular rate in rad/s, FRD body acceleration in m/s², gyro timestamp
in microseconds and accelerometer relative timestamp. Report any clipping,
invalid offsets, non-monotonic times or export mismatch. The pinned runner
passes CSV fields to OpenVINS `ImuData.wm` and `.am` unchanged. The
[OpenVINS IMU model](https://docs.openvins.com/propagation.html) uses local
angular rate and specific force. Review the identity `T_i_b` and gravity
configuration but do not infer a measured calibration from a provisional YAML.

Extract the first initialized frame and the static initializer's logged
orientation, gyro bias, acceleration bias and zero initial velocity. Score
the 2-second pre-initialization interval and the initialization instant using
PX4 `vehicle_local_position` velocity as an **offline EKF2 estimate**, subject
to its validity flags, reset counters and maximum 20 ms interpolation gap.
Retain all velocity samples in a CSV and report speed distributions. A moving
EKF2 estimate can falsify a stationary assumption on this simulated episode,
but EKF2 is not independent ground truth and cannot establish the unique cause
of the ensuing drift. Keep simulated Gazebo truth out of estimator input.

The audit must be deterministic and fail closed on changed input hashes,
missing fields, mismatched values, invalid flags or reset/gap crossings.
Preserve raw inputs by hash reference to prior evidence, the new per-sample
velocity CSV, summary JSON, source, tests, report and an indexed,
non-overwriting archive. Unit tests cover a normal mapping, one changed IMU
value, timestamp mismatch, invalid EKF2 interval, and moving-vs-stationary
classification. The report names remaining time-offset, dynamic calibration,
visual-update, PX4 EKF2 fusion and multi-aircraft gates as unverified.
