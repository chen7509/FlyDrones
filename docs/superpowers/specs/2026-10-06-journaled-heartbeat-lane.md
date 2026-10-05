# Independently journaled heartbeat lane

Standing authorization covers this design and inline execution. This stage addresses the observed PR48 health-commit queue hazard; it does not rerun physics or qualify VIO.

## Selected design
Retain ready-shadow-v1 unchanged. Add explicit ready-shadow-heartbeat-v1 composition. The existing receiver thread validates and writes/flushes an independent heartbeat observation journal before it queues the same original event to CaptureWriter. This journal commits actual received source identity, not simulated receipt or a native acknowledgement. No new receiver, native worker, heartbeat message, or network publishing.

Use the existing fan-out gate RLock. Within it, validate the raw unarmed system9 heartbeat, enforce signed integer monotonic arrival/observation clocks, write/flush its observation, and update JournaledReadiness. A journal/update failure latches the whole gate before releasing the lock. ReadyShadowFanout continues to send each queued event to the single ShadowInput; the heartbeat readiness route reconciles exact original identity in observation order instead of regressing readiness to the old queued heartbeat. Both journals explicitly distinguish observation from reconciliation. At most32 unmatched observations, each requiring reconciliation within the original2s bound. Missing/duplicate/changed/reordered observation, armed/invalid source, clock failure, queue deadline, hidden shadow/readiness failure, journal short-write/flush/close failure all refuse.

IMU/RGB/CameraInfo eligibility still requires successful existing fan-out delivery and original2s freshness. Native per-packet2s and per-source2s bounds remain. A fresh heartbeat cannot rescue expired pending native work or stale/failed sensor processing. Steps already executing before failure latch may finish; no later gated step is permitted. Holding a gate across filesystem I/O does not provide real-time guarantees or make flush equivalent to fsync.

Rejecting the alternatives: increasing TTL hides a clock/load problem; prioritizing the raw queue silently reorders sources; moving all readiness ahead of native masks failures. The new lane only separates heartbeat observation from estimator work while explicitly preserving downstream health gates.

## Scope and physical gate
Implement the opt-in integration and synthetic concurrent/clock/source/log/cleanup tests. Use sealed PR48 clocks to demonstrate the queue scenario with a virtual clock and fake native sink; not estimator replay or online latency. Source snapshots establish clock semantics, not equivalence of missing historical runtime hashes. No PX4/Gazebo/native estimator process in this stage.

Future physical capture remains blocked on prospective enforced-timeout agreement, complete declared runtime snapshot coverage, and independently selected post-initialization comparison semantics. PR48 full freeze and origin failures stay false. Original25s/1ms/250Hz/10Hz160x120RGBD, body/gravity/forces/readyanchor and all geometry/health thresholds stay unchanged. No ODOMETRY, arming, truth initialization, reset/quality/covariance fabrication or fusion qualification.

## Verification
Test blocked native with fresh independently journaled HB and prior fresh processed sensors; same case must reject at pending2s, source2s and armed/new failure. Test journal failure atomicity against a waiting force thread, hidden native failure, reconciliation identity/order/duplicate/missing,32capacity, source clock regression/future/bool/overflow, close and constructor cleanup, CLI old/new profile constraints and receiver helper event equality. Preserve partial delivery and all failed identities. Full regression and one independent read-only review precede sealing/draft PR.
