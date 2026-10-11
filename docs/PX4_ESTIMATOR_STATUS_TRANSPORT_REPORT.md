# PX4 estimator-status transport prerequisite

## Finding

The checked student-capture gate now requires
`EstimatorStatus.filter_fault_flags` and an independently fresh status time.
Pinned PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` publishes
`/fmu/out/vehicle_local_position` and `/fmu/out/estimator_status_flags` in its
uXRCE-DDS topic list, but **does not publish**
`/fmu/out/estimator_status`. The flags topic lacks the required filter-fault
field. The existing ROS odometry collector therefore cannot obtain that
checked-capture evidence directly from this pinned firmware build. This is a
transport prerequisite failure, not a fruit-fly learning or VIO-accuracy
failure.

The fixed [PX4 topic list](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/uxrce_dds_client/dds_topics.yaml)
has SHA-256
`7e9c730d45b22af92acfebbb81cb5de4e4a69ac0ca46b012b71ed8fa5c89cbc0`;
its [`EstimatorStatus.msg`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/EstimatorStatus.msg)
has SHA-256
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`.
The local checkout is at that exact commit and those two files are clean.
[PX4's official uXRCE-DDS guide](https://docs.px4.io/v1.15/en/middleware/uxrce_dds)
says the YAML controls which topics are compiled into the client and that the
ROS interface definitions must match firmware. Adding a YAML line without a
new build and runtime check cannot change the current binary.

## Candidate and independent ROS interface gap

`configs/px4/estimator-status-dds-candidate.yaml` is a prospective source
candidate. It changes the fixed YAML by one publication only:
`/fmu/out/estimator_status`, type `px4_msgs::msg::EstimatorStatus`, rate limit
20 Hz. The chosen limit corresponds to a 50 ms nominal interval in the pinned
client generator and is frozen before any physical experiment; transport
jitter, age at the 10 Hz RGB frames, CPU and RTF impact have not been measured.
The original local-position publication stays at 50 Hz and the frozen camera/
physics workload is untouched. The installed PX4 checkout and binary were not
modified or rebuilt.

An earlier `upstream-px4_msgs` snapshot used in the repository has
`EstimatorStatus.msg` SHA-256
`acb1ef1f13d82763e3982d5a649af3a772b59662ad3a7f1a011330c17368a822`:
it includes one extra GPS-check constant and is not byte-identical to the
pinned PX4 message. The preflight correctly refuses that snapshot. The
positive candidate check instead supplies an exact **test fixture copy** of
the pinned PX4 message; it does not establish that an installed ROS workspace
contains that copy or that the compiled ROS type support matches.

PX4-Autopilot is BSD-3-Clause and was not archived at the repository metadata
check on 2026-10-12; GitHub reported its latest push as 2026-10-11.
PX4/px4_msgs was likewise unarchived with a latest push of 2026-10-07.
These are maintenance observations, not guarantees of local binary
compatibility. Existing PyYAML 6 is declared by this project; no dependency
was installed. Adaptation requires a dedicated PX4 build, exact pinned
`px4_msgs` synchronization/build, an owned Agent/ROS status collector,
timestamp/identity binding and runtime bandwidth/RTF measurement. The added
status stream has an unmeasured resource cost.

## Verification and limits

The source-only preflight reads the pinned files and rejects a changed base,
wrong status type/rate, duplicate YAML key or topic, modified status field and
the newer ROS message snapshot. It always returns
`firmware_compiled_verified=false`, `live_source_authenticated=false`,
`camera_calibration_qualified=false`, `fusion_qualified=false` and
`training_eligible=false`, even for the exact candidate. The actual local
source-path check reported `base_status_published=false` and
`source_candidate_ready=true` only with the exact fixture copy; the existing
ROS snapshot produced `ros_estimator_message_mismatch` and exit 1.

Initial behavior tests failed because the preflight module did not exist.
Independent review found that an unhashable YAML mapping key escaped the
structured-refusal path; its new test failed before the fix and all **10**
targeted cases passed afterward. The complete `tests/connectome_training`
regression passed **582 tests, 2 skipped** with two existing PyTorch warnings
before that narrow error-path fix; the affected suite was rerun afterward.
Changed Ruff passed. The byte-exact source snapshots and candidate retain
upstream whitespace; their Git attributes exclude whitespace normalization
and whitespace warnings. The staged diff check passed with those declared
byte-exact exceptions.
Final independent read-only review confirmed the malformed-key fix and found
no remaining Critical or Important issue. The full regression preceded only
that narrow refusal-path fix; the final affected suite is the post-fix check.

| Status | Evidence |
| --- | --- |
| Verified offline | Pinned source topic omission, exact one-topic source candidate, exact-message refusal, permanent non-authorizing result. |
| Implemented only | Candidate YAML and source preflight. |
| Untested | New PX4 build, actual ROS status topic, causal age/packet loss, Agent/PX4 identity, CPU/RTF effect, calibrated camera, EGO collection. |
| Failed or still closed | Existing ROS message snapshot mismatch; prior PX4 TIMESYNC/startup failures, old ULogs without `vehicle_odometry`, and five-camera 0.873 RTF below 0.95. |

The next real dependency is to build an isolated pinned PX4 candidate with
the new topic and a matching ROS interface, then run an unarmed source-only
receipt test with frozen load when the existing resource gate permits. That
test must keep the original startup and failure evidence. It does not by
itself authorize student capture: sustained PX4 heading health, external
vision fusion, calibrated camera, authenticated teacher and safety gates
remain separate.
