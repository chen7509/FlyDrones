# Estimator-aware heartbeat routing failure design

## Scope

The immutable `study-v11/capture-v1` physical attempt failed before motion at source sequence 426. The rejected record is the first queued heartbeat. It has heartbeat clock and identity fields, but deliberately has no estimator `sample_ns`. The estimator-aware fan-out nevertheless forwarded every post-shadow record to `EstimatorAwareReadiness.observe_ack_batch`, whose contract requires a sampled sensor source. This stage diagnoses and corrects that routing defect on fixed input only. It does not rerun physics, OpenVINS, training, or control.

## Contract

Heartbeat observation and reconciliation remain owned by `JournaledHeartbeatFanout`. A heartbeat must pass through the shadow route and then reconcile the exact previously journaled heartbeat identity through `_ReceiptReadiness`; it must not be used as the source attribution for native estimator acknowledgements. Sampled IMU, RGB, CameraInfo, and depth records retain the existing estimator acknowledgement validation and causal clock checks.

`EstimatorJournaledHeartbeatFanout._after_shadow` therefore accepts heartbeat only when the shadow reports an empty acknowledgement batch, and returns without invoking `observe_ack_batch`. A non-empty native acknowledgement batch associated with a heartbeat is refused because it has no valid sampled-source attribution. The correction must not invent `sample_ns`, substitute `observed_sim_ns`, weaken heartbeat age/identity checks, alter the two-second deadlines, or relax estimator readiness.

## Evidence and claims

Add a regression reproducing the exact heartbeat shape from source sequence 426, including the independent observation before queued delivery. It must show one observation, one reconciliation, one committed fan-out record, no estimator-readiness failure, and no estimator journal entry. Add the inverse test that a heartbeat carrying native acknowledgements fails before readiness reconciliation. Retain the immutable failed capture and classify it as an estimator-ack routing refusal before motion, not a VIO accuracy, PX4, fruit-fly learning, or training failure.

Seal the fixed-input diagnosis, RED/GREEN evidence, targeted and full regressions, source/capture hashes, and remaining gates. A future physical retry requires a new prepare-only study and startup preflight under a new immutable destination; `study-v11/capture-v1` may never be overwritten or retried.
