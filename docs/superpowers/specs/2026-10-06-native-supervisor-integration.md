# Native refusal / recorded supervisor integration

Approved scope: the user's standing authorization and latest heartbeat. This is a bounded integration study, not another process-management feature or a VIO success claim.

## Research and selection

Reuse PR45 supervisor at 85b7000 and PR44 `native-pre-epoch-v1`, with PR43 production native SHA 303b575e29d44bf50850ad03e3d3b865207a225e366418ec5733ed5292cc18ce. Named new study: `native-pre-epoch-recorded-supervisor-v1`. Previous evidence is immutable.

Reviewed fixed CPython 3.12.3 (PSF license, active upstream; installed WSL 3.12.3, distro-patch equivalence unknown), subprocess and os interfaces; Linux waitid/kill/proc official manuals; fixed Gazebo TestFixture 446a44335a45b704b4d36dabcc5508ee34eeb3d8 (Apache-2.0, maintained upstream, installed gz-sim 8.15); pybind 2.11.1 (BSD-3-Clause, exception translation). Source/metadata snapshots from PR44/45 will be referenced by hash, with a fresh official documentation check. WNOWAIT retains the leader for subsequent reap; kill success is dispatch, not proof of exit. Current Python 3.12 online docs describe a later patch version, so fixed source governs the implementation. No new dependency or ROS/Agent installation. Cost: one short WSL/PX4/Gazebo run, lightweight offline journal validation. Reject global descendants tracking or a new orchestration framework as outside this integration question. OpenVINS paper/context remains background only; estimator is not run.

## Frozen study

Keep 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGBD, existing body/gravity, supported-ready-v1 / substep-ready-v1, actual journaled fresh source + unarmed readiness, immutable 200 ms future anchor, 8 s readiness bound. Trigger production native wrong epoch before any force. No native test exports, teleport, ODOMETRY, arming, truth-to-estimator or changed sensor values. At most one prospective run. Launcher snapshots sources, selected binary, models and backend libraries before/after; captures original worker failure, ULog and sibling supervisor journal. Worker 60 s / supervisor 90 s bounds retained.

## Acceptance

Native wrong-epoch refusal, later callback blocked, zero support/lateral/force, all ULog arming_state=1, PX4 exit0, immutable runtime hashes. Preserve worker exit2 and capture_failed. Supervisor disk journal must exactly match in-memory events, including leader identity, unreaped exit2 before cleanup, each signal intent/result, reap2, and final after-reap empty/error-free scan. Report supervisor no-SIGKILL, no-executing and group-absent separately. Any escalation, permission/clock/journal/proc error, missing evidence or mutated input fails this scoped integration. No claim about escaped descendants or uninstrumented child-specific signals. Validate existing ULog retention without overwrite. No-SIGKILL refers to recorded supervisor group signals only.

Offline validator tests must reject missing/mismatching journals, identity mutation, bool/float integer fields, nonfinite/regressed clock, unmatched/foreign/late signals, incomplete cleanup and reap ordering, false summary flags and hidden errors. It must accept a complete no-signal exit and a complete TERM-only exit. No simulator runs for unit tests.

## Next dependency and boundaries

On passing, return to composition of readiness and OpenVINS shadow source consumers, then separately freeze online supported-motion VIO. Current OR dispatch is not composition. PR37 drift, PR39 ground aliasing, PR40 startup failure, PR44 unknown historic signals and five-camera 0.873 RTF remain unchanged. This study cannot qualify VIO or the complete fly policy.
