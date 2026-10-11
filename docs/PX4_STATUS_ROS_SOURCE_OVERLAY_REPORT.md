# PX4 EstimatorStatus ROS source overlay

The fixed ROS build source was not byte-identical to the pinned PX4
`EstimatorStatus.msg`. Official `PX4/px4_msgs` commit
`148bdb4b8214a4d8de83029777fe8d334c74db6f` has a message SHA-256 of
`dfef1210ff72fea4e37edbf493cce441825048eda460992d981813aa2cd113ea`;
fixed PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` has
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`.
The observed source diff is one extra `GPS_CHECK_FAIL_JAMMED = 11` constant in
the ROS copy. This does not by itself prove a wire incompatibility, but it
fails the project's exact-interface gate.

The existing 260-file unbuilt v2 source tree at
`results/px4-ros2-full-byte-build-dev-1701/source-v1` passed its verifier and
has profile SHA-256
`38746117fe011b1eb2179c163db0be2b01134bacbab8b4b3abd9079b9702e372`.
From it, `source-v2` under `results/px4-status-ros-overlay-dev-1701` was
derived into a new exclusive directory. An independent byte-by-byte audit
confirmed that **only** `src/px4_msgs/msg/EstimatorStatus.msg` changed among
all 260 `src` files. The replacement equals the pinned PX4 fixture byte for
byte. The derived profile SHA-256 is
`fe0bf2e072f0bebb63fe10fe1dc387af664146c768a05e06a5a5eab36efc9654`.
It embeds the exact parent profile and records old/new status hashes. The
original v2 source remains unchanged. A first derived `source-v1` lacked the
embedded parent-manifest cross-check, is retained, and now correctly fails
the strengthened verifier; it is not a qualified build input.

The implementation reuses the existing byte-bound ROS source tool and fixed
official [PX4 uXRCE-DDS guidance](https://docs.px4.io/main/en/middleware/uxrce_dds).
PX4 and `px4_msgs` are BSD-3-Clause; pinned versions, maintenance observation,
ROS Humble/rclcpp Apache-2.0 interface, resource costs and selection reasons
are recorded in the earlier
[source-journal report](PX4_ROS2_SOURCE_JOURNAL_REPORT.md) and
[transport report](PX4_ESTIMATOR_STATUS_TRANSPORT_REPORT.md). No dependency was
installed. This overlay adds one message source file but still uses the old
read-only **odometry** collector: there is no EstimatorStatus subscriber or
compiled status type yet. The existing `MAKEFLAGS=-j1 colcon ...` string in
the derived source profile is a declared prospective build command, not an
executed build; the old v2 runner must not treat this derived tree as an
unmodified official Git source.

Initial tests failed before the derivation API existed. A real Windows
junction-ancestor case and a relabelled, non-status file each reproduced
additional refusal gaps before fixes. Independent review then found that
rehashed parent metadata and linked seal files could be accepted; four new
cases failed before those checks were tightened. Its follow-up found a
combined v2-schema downgrade with a third status-message payload; a separate
RED case reproduced the acceptance. The fixed verifier binds the pinned
official v2 profile to its canonical manifest and rejects linked profile and
seal paths. The reviewer found no remaining defect in this pinned-source
boundary. Final affected build-source and journal regression:
**85 passed, 1 skipped** (direct file symlink creation was unavailable;
directory-junction rejection and simulated seal-link rejection ran).
Changed-file Ruff and working-tree diff checks passed. The real 260-file audit and
source-v2 verifier passed. No Docker,
PX4, Gazebo, Agent, ROS subscriber, trainer or physical simulation was run;
host free memory remained below the existing 4 GiB physical gate.

| Classification | Result |
| --- | --- |
| Verified offline | Exact parent profile and 260 files; one-file overlay; unchanged `VehicleOdometry.msg`; linked/wrong/corrupt source and output tampering refusals. |
| Implemented only | Derived ROS source tree and strict v3 source verifier. |
| Untested | Colcon generation of this derived `px4_msgs`, compiled PX4 with new DDS topic, typed EstimatorStatus subscriber, Agent receipt/identity, clock age, CPU/RTF, EKF2 fusion and student capture. |
| Failed/retained | Original source mismatch, first derived source-v1's missing parent-manifest cross-check, old build/startup/ULog failures and five-camera 0.873 RTF below 0.95. |

The next gate is a separately declared, resource-bounded build of this
derived ROS source and a matching isolated PX4 firmware candidate. Then a
read-only typed status subscriber and unarmed receipt test can measure actual
source identity, loss and time age. None of these source-only checks authorizes
fusion, training or flight.
