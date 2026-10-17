# Source watchdog startup-cohort diagnosis and correction

## Evidence boundary

The immutable `study-v18/capture-v1` physical attempt stopped at 10 ms simulation time with `source silence: imu`. It received the first IMU at wall-monotonic 143,738,881,833 ns, the first CameraInfo at 145,553,630,562 ns and the first RGB at 145,818,189,234 ns. The watchdog declared itself ready on that RGB even though the IMU was already more than the unchanged 2 s operational limit old. It latched failure 254,629 ns later; the next IMU arrived only 713,794 ns after failure and would have formed a cohort in which all three required source arrivals were less than 2 s old. The attempt produced no estimator initialization, motion command, ULog, fusion, flight or fruit-fly-policy execution.

## Correction

Keep the 10 s startup limit and 2 s operational limit unchanged. During startup, observing all three source names once is insufficient. Transition to operational readiness only when the latest IMU, RGB and CameraInfo arrivals form a fresh cohort whose wall-clock span is at most the existing 2 s operational limit. If no fresh cohort forms before 10 s, reject with the missing or stale source names. Once ready, retain the existing 2 s source-silence rule without simulation-time substitution.

This changes the state transition, not either timeout. It does not hide sustained stalls: a source that remains stale cannot complete startup, and any source silent for more than 2 s after readiness still fails. It does not alter camera-pair simulation-time causality, queue limits, native processing limits, supervisor timeouts or the physical workload.

## Verification and next boundary

An independent fixed-evidence auditor must reproduce the exact early-readiness/failure ages, prove that the next recorded IMU forms a fresh cohort inside the original startup window, and retain PX4 cleanup and all downstream false claims. Unit tests cover delayed renderer startup, no-fresh-cohort timeout, post-ready silence and clock regression. No physical rerun belongs to this stage. Any later attempt requires a new prepare-only package, startup preflight and separately committed one-shot boundary.
