# Causal wall-deadline plan

- [x] Reconcile the immutable `study-v8` timing evidence with the original causal-input specification.
- [x] Add a deterministic RED regression for queued later-IMU arrival versus post-processing wall time.
- [x] Remove only the post-processing watermark advance while retaining source-arrival and explicit silent-source expiry.
- [x] Verify stale source arrivals, direct and online idle ticks, latched failures, fan-out and full regression.
- [x] Seal the fixed-input evidence, update the diagnosis report and publish the reviewed commit without a physical rerun.
