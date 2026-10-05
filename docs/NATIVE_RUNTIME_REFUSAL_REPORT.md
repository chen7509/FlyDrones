# Native runtime refusal development study

**The production native epoch error reached the recorder, blocked the next callback and allowed owned PX4 to exit normally. Full descendant cleanup qualification remains unproven.** One short `native-pre-epoch-v1` sensor-only experiment was run; the original `capture_failed` and incomplete trace/reference flags are retained. No estimator, training, ODOMETRY or EKF2 was run.

## Design and sources

An explicit development profile delegates to the unchanged production native binary. After fresh journaled sensor/unarmed readiness and before the immutable support anchor, it submits a deliberately incorrect epoch to the native pre method. It does not edit physical state, sensor timestamps, local pose or force policy, and uses no synthetic mutation exports. The ordinary recorder catches the actual native exception; the existing force gate handles later callbacks.

Fixed gz-sim `446a44335a45b704b4d36dabcc5508ee34eeb3d8` TestFixture/binding and WrapCallbacks source were reviewed (Apache2 project; wrapper contains separately credited BSD3-derived code). Installed pybind11 `2.11.1` BSD3 exception documentation was fetched at that version; [official exception documentation](https://pybind11.readthedocs.io/en/stable/advanced/exceptions.html) describes C++ to Python translation. Repository maintenance metadata and source hashes are retained in `sources/`; neither repository is archived. [OpenVINS ICRA2020](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf) is estimator context, not cleanup evidence. Existing interfaces required no installation, native rebuild or estimator workload. A separate System/Stop implementation or injected process kill would exercise different paths and was not adopted.

## One frozen physical run

Producer `dc23e19`, unchanged native binary SHA256 `303b575e29d44bf50850ad03e3d3b865207a225e366418ec5733ed5292cc18ce`. All frozen source/runtime hashes match before and after. Preserve 1ms physics,250Hz raw IMU,10Hz160x120 RGBD, original body/gravity and ready/force gates. The prospective limit was8s simulation,60s worker wall and90s supervisor. This is an intentionally short fault study, not reduced-load capacity qualification.

- Actual readiness selected1.569s, immutable anchor1.769s.
- At1.579s, the wrapper submitted1.580s to a native state whose last completed epoch was1.578s. Actual exception: `RuntimeError('native pre sequence')`; failed=true,pending=false,last_ns remains1.578s.
- The1.580s callback was blocked. Native completed1578 cycles before the fault; old trace3156 pre/post records. Support/lateral/force calls are all zero, force journal empty.
- 396 IMU,16 each RGB/CameraInfo/depth, one actual unarmed heartbeat, four ULog vehicle-status records all arming_state1. ULog SHA256 `64df927cbd778ead84a44dd8797b31e0103b7b4975dd982504fc915831172da6`.
- Capture ended1.580s /6.9667 wall seconds. Worker exit2 preserves failure; owned PX4 exit0. The filtered post-run resource scan is empty.

The original audit-v1 numeric checks validated the correct native transition in this run, actual readiness records, raw counts, zero force, ULog and unchanged hashes. Its `refusal_cleanup_expectations_pass=true` wording was too broad: the supervisor attempts process-group termination even after worker exit but does not record individual signal outcomes. PX4 exit0 rules out its own terminate/wait fallback to kill; it does not establish the same for other descendants. Preserve audit-v1 and issue an explicitly narrower audit-v2; full descendant cleanup qualification remains false/unknown, rather than backfilling nonexistent signal evidence.

## Review and tests

Initial missing-module RED then13 implementation tests passed; an additional CaptureJournal cleanup-continuation test and related regression gave125 targeted passes. Independent review found two Important issues: checking only exception text/failed flag could misattribute a different native sequence failure, and the unrecorded supervisor signal path prevents the broad cleanup claim. Six new status-mismatch cases failed before correction and passed afterward;131 targeted tests pass. Strict bool/int and before/after epoch/pending checks now latch mismatches. The actual recorded native before/after states are correct; the final hardening was tested synthetically, without recapturing or relabeling its producer. The cleanup finding is addressed by retaining unknown/false qualification and scheduling the missing signal evidence, not by claiming the underlying requirement passed. No Critical or Minor findings. Initial full regression909 passed; final regression915 passed with two existing loader warnings. Changed Ruff passes; whole-repository Ruff retains50 errors in32 unchanged files (evidence/publication checks), not a whole-repository lint pass.

| Status | Scope |
|---|---|
| Verified | Actual production-native epoch exception, later callback blocked, zero fixture force, unarmed heartbeat/ULog, owned PX4 exit0, filtered resource scan empty. |
| Implemented | Explicit development refusal profile and unchanged production binary delegation. |
| Unverified | Supervisor signal outcomes for all descendants; broad no-SIGKILL cleanup requirement; supported-motion online VIO and fusion readiness. |
| Retained failed records | This deliberately incomplete capture; PR37 drift, PR39 ground-contact aliasing, PR40 startup failures, five-camera0.873RTF<0.95. |

Next instrument the existing supervisor's per-signal outcomes and distinguish process-group disappearance from the filtered resource inventory, with synthetic/real bounded subprocess tests before another prospective runtime study. Do not overwrite or rerun this frozen capture. Then address composite readiness/shadow source delivery for an independently frozen supported-motion OpenVINS study. No public initialized, quality/reset/covariance or EKF2 gate is relaxed.
