# PX4 diagnostic logger runtime staging (2026-10-12)

The previously offline `source-diagnostic-v1` logger list is now an **opt-in implementation path** in the owned unarmed capture. It has not been run with PX4. Old physical ULogs still contain zero `vehicle_odometry` samples, and no PX4/Agent/DDS source has been authenticated by this change.

The new worker option is admitted only with a declared execution contract, runtime binding, wire configuration and fixed owned Agent. The contract pins the canonical file and declaration SHA-256. The capture copies the exact 230-byte topic file into its independent runtime at `etc/logging/logger_topics.txt` before PX4 construction and passes `PX4_PARAM_SDLOG_PROFILE=0` in the PX4 child environment. The PX4 SITL root path is `.`; fixed `rcS` applies that environment override before its default profile. The capture checks the source and copy again after PX4 stops. A missing/changed/linked or already present file fails the run. The previous profile has no new option, file, or environment override.

This stage reuses the fixed PX4/Agent/ROS versions and licensing documented in [the source diagnostic](PX4_ODOMETRY_SOURCE_DIAGNOSTIC_REPORT.md), [Agent integration](OWNED_AGENT_CAPTURE_INTEGRATION_REPORT.md), and [typed XRCE diagnostic](XRCE_TYPED_ODOMETRY_DIAGNOSTIC_REPORT.md). No new dependency was installed. The source file is a prospectively selected diagnostic input; its added logging work is not the original capacity-test workload. The existing `live-wire-study-v2` manifest rejects this option, so a new declared study and resource-qualified physical episode are still required.

During TDD, the first test import failed because the module was missing; the contract test failed for the missing declaration field; the capture test failed for the missing staging function; and a linked-parent test failed until the post-check rejected it. Independent review found that the topic file could change between validation and copying. A new fault-injection test failed on that window; the final stage now compares the actual bytes used for the copy with the declared hash before any PX4 launch. One focused and adjacent selection reported **108 passed, 2 skipped**. A fresh final selection covering the logger, capture contract, runtime runner and wire lifecycle reported **82 passed, 3 skipped**. The first final command named a nonexistent test file and ran no tests; its failure is retained alongside the successful rerun. Changed-file Ruff and `git diff --check` passed. This report does not infer a full-suite pass. No PX4/Gazebo/OpenVINS process or Docker container was launched for this stage.

| Scope | Status |
| --- | --- |
| Verified | Canonical bytes, exclusive runtime copy, pre/post mutation refusal, declared opt-in, and adjacent Python regression. |
| Implemented only | PX4 child environment and owned runtime integration; actual PX4 logger selection is not observed. |
| Untested | New physical ULog with `vehicle_odometry`, same-episode Agent↔PX4↔ROS typed CDR provenance, calibrated camera/VIO→EKF2 and flight. |
| Still failed or blocked | Old ULogs lack odometry; v10 first TIMESYNC exceeded its two-second gate; five-camera 0.873 RTF remains below 0.95; current free host memory is below the 4 GiB physical gate. |

This stage never grants source, fusion, training, performance or flight qualification. Preserve all earlier results and failure attempts.

Sealed stage evidence: `evidence/px4-owned-logger-runtime-dev-1701.zip`, SHA-256 `a699e22bc0a30fb7f991f8da58427725f5b9b91c40d86e64ac91291d044c4564` (15 listed files plus a member-hash manifest; the report in the ZIP is the pre-hash snapshot). The failing command log is included so the rerun cannot be mistaken for an uninterrupted first attempt.
