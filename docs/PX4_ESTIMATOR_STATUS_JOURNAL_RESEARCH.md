# Read-only EstimatorStatus journal: upstream selection

Observed 2026-10-12. This is the implementation input for the
[status-journal design](superpowers/specs/2026-10-12-px4-estimator-status-journal-design.md),
not evidence of a live PX4 topic.

| Candidate | Version, license and maintenance | Interface and resource cost | Decision |
| --- | --- | --- | --- |
| [PX4 fixed source](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/EstimatorStatus.msg) with [fixed DDS topic list](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/uxrce_dds_client/dds_topics.yaml) | Commit `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, BSD-3-Clause. GitHub metadata: unarchived; last push 2026-10-11. | The message has `filter_fault_flags`, validity/fusion flags, PX4 publication/sample times, accuracy, innovation ratios and reset counters. The fixed compiled topic list omits `/fmu/out/estimator_status`; a source-only YAML candidate needs a separate firmware build, Agent and unarmed trial. | Keep this exact message/topic pair as the future live-source target. A type build alone cannot expose the topic. |
| [PX4/px4_msgs](https://github.com/PX4/px4_msgs/tree/148bdb4b8214a4d8de83029777fe8d334c74db6f) | Commit `148bdb4b8214a4d8de83029777fe8d334c74db6f`, BSD-3-Clause in the sealed `LICENSE`. GitHub metadata: unarchived; last push 2026-10-07. | The prior snapshot's `EstimatorStatus.msg` differed from fixed PX4. The sealed 260-file overlay replaces exactly that message; the one-shot build generated matching ROS type support under one CPU, 768 MiB, no network in 2,346.906 s. | Use only the hash-verified overlay and generated type; do not trust the package name alone. |
| [ROS 2 Humble rclcpp](https://docs.ros.org/en/humble/p/rclcpp/) and [serialized-message implementation](https://github.com/ros2/rclcpp/blob/humble/rclcpp/src/rclcpp/serialization.cpp) | Installed image `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a` contains rclcpp 16.0.19 and CycloneDDS RMW 1.3.5; rclcpp source is Apache-2.0. GitHub metadata: unarchived; last push 2026-10-09. | Existing typed `VehicleOdometry` serialized callback already receives `rclcpp::MessageInfo`, RMW GID/sequence/timestamps and CDR without publishing. A second small node can reuse its exclusive JSONL, SHA and terminal-I/O pattern. The ROS type build is the dominant local compile cost. | Build a **separate typed, read-only** `EstimatorStatus` collector and auditor. Keep old odometry collector and historical logs unchanged. |
| Fixed [`EstimatorStatusFlags`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/EstimatorStatusFlags.msg) or generic ROS subscription | Same fixed PX4 source; no new dependency. | `EstimatorStatusFlags` lacks `filter_fault_flags`. Generic subscription adds dynamic type handling without solving missing compiled publication or source authentication. | Reject as substitute for the required full status message. |

The [official PX4 bridge guide](https://docs.px4.io/main/en/middleware/uxrce_dds)
confirms that `dds_topics.yaml` is compiled into the PX4 client and ROS must
use matching message definitions. The [ROS 2 rclcpp source](https://github.com/ros2/rclcpp/blob/humble/rclcpp/src/rclcpp/serialization.cpp)
shows `SerializationBase` dispatching to `rmw_deserialize`; the existing
collector establishes the fixed-image callback and CDR access pattern. These
sources support the chosen interface, not a claim that the currently installed
PX4 firmware publishes status. A GID is local DDS continuity, not an owned
PX4/Agent identity. The separate live stage must correlate firmware binary,
Agent, DDS domain, PX4 sample/publication time and ULog.

The next source-only tests must reject a wrong installed message, malformed
or oversized CDR, duplicate/rollback times or sequences, GID/session change,
unsupported RMW metadata misread as zero, source silence, and failed terminal
writes. EKF2 may emit an unavailable innovation ratio as nonfinite; preserve
the raw CDR and represent that decoded value as JSON `null` with explicit
availability, never as a healthy zero. `timestamp_sample` and `timestamp`
must remain separate. Synthetic subscriber tests cannot establish live PX4
source, physical sensor health, VIO quality or training eligibility.

This stage adds instrumentation rather than a new estimation algorithm; the
existing OpenVINS/visual-inertial papers inform the separate VIO work but do
not determine DDS field or source-identity semantics. No library installation
or simulator load is justified by this research alone.
