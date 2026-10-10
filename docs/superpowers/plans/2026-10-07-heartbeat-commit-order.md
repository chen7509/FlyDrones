# Heartbeat/IMU commit-order plan

- [x] Add a fixed-evidence auditor for immutable `study-v19` and RED tests for a heartbeat ahead of committed IMU with an older valid heartbeat.
- [x] Retain bounded monotonic heartbeat history and select only the newest causally eligible heartbeat without changing any freshness limit.
- [x] Run focused and full regressions; update the physical diagnosis report and seal the immutable failure/correction evidence.
- [ ] Do not rerun `study-v19`; create a later retry package only after the correction is committed.
