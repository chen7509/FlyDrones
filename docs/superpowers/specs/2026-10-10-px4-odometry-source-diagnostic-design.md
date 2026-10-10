# PX4 odometry source diagnostic design

## Purpose and boundary

An owned, unarmed PX4-to-ROS source trial must be able to compare typed ROS 2 `VehicleOdometry` samples with the **same named PX4 uORB message** in the trial's ULog. Two sealed 25-second physical ULogs have no `vehicle_odometry` dataset. Their attitude, local-position and EKF-status datasets cannot stand in for field-level odometry parity. This design prepares a separate, diagnostic-only logging configuration and its offline admission check. It does not publish ROS odometry, alter EKF2, arm, train MaleCNS, or qualify unchanged physical workload.

## Fixed upstream and choice

| Component | Fixed reference and status | Interface, cost and decision |
| --- | --- | --- |
| PX4 SITL | `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, tag v1.17.0, BSD-3-Clause. `src/modules/logger/logged_topics.cpp` SHA-256 `33c1cd7c55dc81d4fa53153b7f269401b67c7f6edc929707ec536203096bcfe5`. | Its `initialize_logged_topics` uses a nonempty `PX4_STORAGEDIR/etc/logging/logger_topics.txt` **instead of** `SDLOG_PROFILE` defaults. `SDLOG_PROFILE=131` is DEFAULT, ESTIMATOR_REPLAY and VISION_AND_AVOIDANCE, but still omits `vehicle_odometry`. Adopt an isolated, explicitly different diagnostic profile; do not call it the previous workload. |
| ROS type | `PX4/px4_msgs` `148bdb4b8214a4d8de83029777fe8d334c74db6f`, BSD-3-Clause; fixed `VehicleOdometry.msg` SHA-256 `a528b3d0b4c1a9083a71b32c367bad71a900e959efd82b9d03a9eb0e99fe6017`. | Reuse the already built opt-in read-only journal. Its generated-type build passed; a typed DDS callback and independent CDR-to-field parity have **not** passed. |
| XRCE bridge | PX4 client submodule `711aef423edd1820347b866d1e4164832df35d04`, v2 family. Compatible Agent candidate is [eProsima v2.4.3](https://github.com/eProsima/Micro-XRCE-DDS-Agent/releases/tag/v2.4.3), commit `73622810d984349b80bbac0ef55fc0b694d62222`, [Apache-2.0](https://github.com/eProsima/Micro-XRCE-DDS-Agent/blob/v2.4.3/LICENSE), released 2024-03-20. | [PX4 v1.17 documentation](https://docs.px4.io/v1.17/en/middleware/uxrce_dds) names v2.4.3 and warns that v3 Agent is incompatible with its v2 client. Agent v3 releases show ongoing upstream work, not maintained v2 compatibility. The v2.4.3 build pulls Fast DDS/Fast CDR dependencies; no installed Agent or local resource-qualified build exists. Do not substitute current v3 or assume ROS Humble dependency compatibility. |
| Logger documentation | [PX4 v1.18 release notes](https://docs.px4.io/v1.18/en/releases/1.18) say later versions append custom topics to defaults. | Reject a v1.18 upgrade merely to gain append semantics: it changes the fixed flight stack and invalidates comparison to the existing v1.17 evidence. The pinned v1.17 source is authoritative for this trial. |

The next trial uses a *new, named* `source-diagnostic-v1` profile: `SDLOG_PROFILE=0` and this exact, nonempty `logger_topics.txt`, with one LF-terminated line per entry and no header:

```text
vehicle_odometry 0 0
vehicle_status 100 0
vehicle_attitude 20 0
vehicle_local_position 20 0
estimator_status 20 0
estimator_selector_status 100 0
sensor_combined 0 0
timesync_status 1000 0
logger_status 100 0
failsafe_flags 100 0
```

It requests full-rate odometry and IMU, while other diagnostic topics have explicit minimum intervals. The file is only an offline candidate until the actual PX4 logger startup message and post-run ULog show its selected topics, sample counts and retained health evidence. The added/different logger workload must be measured and labeled; it cannot pass an unchanged-load, five-camera RTF, VIO accuracy or fair-baseline gate.
The ASCII file is 230 bytes with SHA-256 `0bb9a3d9b57c6a73c73e8fee75569b9e690857654c4631b6f6cd5b6654328994`. The declaration has exactly these keys and types: `schema="flydrones.px4_logger_diagnostic.v1"`, `profile_id="source-diagnostic-v1"`, `px4_commit` and `logger_source_sha256` equal to the fixed values above, `sdlog_profile=0` as an integer, `diagnostic_only=true` as a boolean, and `topics_sha256` equal to the file hash. Any extra key or altered value refuses.

## Offline contract and evidence

Store the canonical file as an immutable repository fixture. A standard-library validator accepts only its exact LF bytes, exact topic/interval/instance order, the fixed PX4 commit/source hash, `SDLOG_PROFILE=0`, and an explicitly `diagnostic_only=true` declaration. It refuses missing/extra/duplicate topics, malformed intervals or instances, CRLF/partial lines, wrong version/hash/profile, unknown declaration fields and modified bytes. Parsing the fixed v1.17 syntax is a guard against a silently ineffective file, not proof the runtime subscribed. Its result must say `logger_file_candidate=true`, `runtime_topic_selection_verified=false`, `dds_ulog_parity_verified=false`, `source_authenticated=false`, and `eligible_for_training=false`.

A future launcher must copy the validated file into its **owned** PX4 rootfs before logger start, bind the copied bytes and `SDLOG_PROFILE=0` in a prospective execution manifest, and recheck after the run. An existing or non-owned rootfs is a refusal; no shared PX4 checkout or prior result is modified. A fresh diagnostic run must preserve the actual logger startup message, `logger_status`/dropout evidence, full original ULog and SHA, ROS CDR/decoded journal, Agent/PX4 process identities and endpoints, clock epoch, reset events, source health and all failures. Exact timestamp-and-field comparison is a later gate after generated-type synthetic DDS parity; a nearest-neighbor position match is insufficient. A matching DDS/ULog row alone still does not authenticate PX4 because the Agent creates DDS writers on the client's behalf. No online truth enters the source or estimator.

## Rejection and staged exit

First validate the offline file and declaration with normal, mutated, duplicate, unsupported-version and truncated cases. Then re-run the previously failed ULog preflight to confirm old logs remain rejected. Do not launch an Agent or physical study while another task is active or host resources are below existing gates. Only after synthetic callback/CDR parity and a pinned, resource-qualified Agent are available may a single new unarmed source diagnostic run be planned. It succeeds only as **source evidence** if the actual ULog contains a complete instance-zero `vehicle_odometry`, the ROS journal passes field/epoch comparison, owned process and transport evidence is continuous, PX4 remains unarmed and healthy, logger loss is bounded, and all files/hashes survive cleanup. Failure keeps every trace and grants no fusion or training eligibility.
