# EGO bridge input gate design

## Purpose and evidence

The fixed EGO-Swarm checkout is `23a8d5a191711dd65633df689bd00f55d4dea8f9` (GPL-3.0); its ROS 2 `ego_replan_fsm.cpp` reads `Odometry.twist.twist.linear` directly as planner velocity. The existing FlyDrones `ego_node.py` accepts bounded packet length and a depth shape but publishes unvalidated times, navigation vectors, camera pose, and decoded depth to ROS. Python JSON also accepts NaN/Infinity by default. This can contaminate the reference baseline before any controller safety gate. The repository's pinned image and ROS topic smoke prove startup and one synthetic reference, not qualified observations. The bridge uses NumPy and the already-mounted `/benchmark` directory; no new runtime dependency is needed. The fixed upstream planner remains unmodified.

The ROS 2 `nav_msgs/Odometry` definition says pose uses `header.frame_id` and twist uses `child_frame_id`. The current bridge labels the child `base_link` but passes ENU/world velocity because fixed upstream treats it as world velocity. This semantic mismatch is recorded for a separate interface decision; silently rotating to body velocity would change the planner's input meaning. A received `PositionCommand` is stamped with the most recent observation's sim time by the bridge, while its upstream header stamp is wall time. Arrival ordering alone does not prove which observation caused that command. Neither this change nor synthetic smoke may qualify a same-frame teacher training corpus.

## Contract

Create a pure, container-importable decoder for the exact existing `Observation` JSON schema. Reject malformed UTF-8/JSON, duplicate fields, NaN/Infinity literals, negative or noninteger times, future or >100 ms stale frame timestamps, malformed or oversized image buffers, nonfinite/bool/string state components, a nonunit camera quaternion, and invalid depth (Infinity, nonpositive finite values, or no positive finite pixel). Keep NaN as an explicit missing-depth pixel and preserve valid RGB-D bytes. Require the benchmark's 120×160 depth and 120×160×3 RGB geometry; the existing sender already uses these dimensions. The parser must have no ROS, PX4, Docker, Gazebo, or truth-state import.

A separate small sequence guard accepts strictly increasing observation sim times; image timestamps may repeat between 10 Hz camera frames but cannot decrease or exceed the observation time. It is reset only by the explicit bridge reset handshake. `ego_node` validates a complete packet and the sequence before publishing `/clock`, odometry, camera pose, or depth. Rejection closes the client request without silently substituting a previous frame or old EGO command. Keep old synthetic smoke files and failures intact; update the future development smoke fixture to send a correctly encoded RGB image.

This is input-format integrity, not live-source attestation. It does not add PX4 EKF2, calibrated camera pose, a causal upstream command ID, EGO training data, or a physical fair comparison. A new formal freeze and development validation will be required before using the changed bridge in comparison runs.

## Validation

Test valid repeated-camera/advancing-state input and each malformed class before implementation (RED), then GREEN against the pure decoder and sequence guard. Verify that the bridge invokes the gate before any publish, that the synthetic fixture follows the same wire contract, and that adjacent sensor/EGO adapter tests still pass. Record the fixed upstream version/license and the remaining frame/causality ambiguity in a report; retain failure outputs and do not run memory-heavy containers or physics while host memory is below the existing gate.
