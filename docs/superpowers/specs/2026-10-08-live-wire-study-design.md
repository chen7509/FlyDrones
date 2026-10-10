# Prospective unarmed live wire study

## Intent, status and authority

The user wants a credible sensor/VIO/PX4 path supporting the complete fruit-fly
policy and a fair upstream comparison. This package prepares the missing actual
communication evidence after the installed startup-only check. It must not
substitute another protocol mock for the real capture path, or turn infrastructure
validation into a claim about learning, formation performance or flight.

This is an architectural study-design package: offline preparation, an auditor,
tests and a review are within the existing preapproval. Actual UDP/PX4/Gazebo/
OpenVINS execution remains a separate activation gate under the current explicit
restriction. No launch is authorized merely by committing this spec. All future
network traffic described here is confined to unarmed SITL, with no ODOMETRY,
EKF2 parameter changes, setpoints, mode changes or arming. The phrase wire-only
describes the permitted outgoing traffic, not a reduced sensor/physical workload.

Installed preflight at `600ada0` passed only resource/startup checks. Its unused
clock origins 0/0 did not measure synchronization. Archive
`evidence/installed-wire-startup-dev-1701.zip` SHA256
`b9c25ae47336904033c9d557b04e66bf9b57dae70e6eb837ce4c85af8b0092de`
is local; remote PR65 still lacks subsequent commits after `e4312ed`. Publication
and runtime qualification are independent, and both remain accurately reported.

## Research and choices

Reuse fixed PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` (BSD-3-Clause),
pymavlink 2.4.49 (retained LGPL package provenance), installed Gazebo Sim 8.15
(Apache-2.0), Python 3.12.3 (PSF) and the existing native OpenVINS binary/config.
`results/live-wire-study-design-dev-1701/research-references.json` binds eleven
retained upstream source/provenance files and prior maintenance observations:
PX4 and Gazebo nonarchived, last pushes 2026-10-07; pymavlink nonarchived, last
push 2026-10-06. These are reused repository observations, not new installed
version claims. Pymavlink's API license field NOASSERTION does not replace its
package license. OpenVINS and raw IMU assumptions are unchanged; no new numerical
method or paper-based estimator capability is introduced.

The [official TIMESYNC service](https://mavlink.io/en/services/timesync.html)
describes request/response offset estimation and filtering. Current v2 targeting
must not be assumed present in the pinned receiver/dialect. The fixed
[GZBridge clock callback](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/simulation/gz_bridge/GZBridge.cpp)
feeds simulation time into the lockstep HRT path; the fixed TIMESYNC handler
consumes positive replies without proving our sender identity. The
[PX4 simulation documentation](https://docs.px4.io/main/en/simulation/) supplies
platform context, not proof of this installed process's clock consumption.

Choices considered:

- Reuse the actual capture runner, one reader, independent PostUpdate clock,
  existing owned daemon listener, interval transaction and fanout. Selected:
  preserves the implemented control and fault paths. Cost is additional listener
  and journal work under the full workload, whose timing is not yet measured.
- Replace the input with wall monotonic time or an echo of the PX4 request.
  Rejected: changes the simulation clock model or destroys independent timing
  evidence. A matching echo is not a measured remote clock.
- Add ROS/MAVROS, another socket reader, or a patched PX4 clock filter. Rejected
  for this gap: new dependencies and behavior would obscure the existing path.
  The inspected MAVROS Offboard example is not adopted and grants no arming scope.

No dependencies are installed. Prospective caps remain 4096 datagrams, 64 journal
segments of 8192 events and 512 MiB total wire evidence; actual CPU/RAM cost and
latency must be measured, not inferred from those caps. No global process manager
or alternative simulator is added.

## Frozen normal study

Use a new unique study/output path and session ID, with development seed 27601.
This seed has already been used for development; it is not a new held-out test.
Do not use held-out trajectories to tune the protocol. Preserve 25 s simulation,
1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGB-D, the selected airframe/gravity,
0.4 m/two-second support profile and original 26 N/1.6 s lateral profile. Retain
the estimator-aware readiness/motion-intent/gauge contracts and full native
workload. Safety gating may refuse before force begins; do not move the force
anchor or omit native processing to obtain a passing communication result.

Use declared_command, execution declaration and runtime binding. Freeze actual
producer commit, input/source/library/model hashes, environment, wire config,
seed, complete command, limits, policy, expected outcome and audit schema before
dispatch. Assert all expected output paths absent. Do not reuse startup's manifest
as a live dispatch. Future pre/post snapshots and required runtime phases must
cover actual owned PX4/OpenVINS and lazy self mappings using the existing binding.

The first normal attempt is exactly one run. Missing resources, live competing
processes, stale hashes or unavailable declared ports refuse launch. Missing or
drifted post evidence makes qualification false. Failure is retained; a retry
requires diagnosis and a separately named prospective study, not overwrite.

## Clock contract

For this zero-origin simulation profile, explicitly define the companion clock
as `remote_ns = sim_ns`, with sim_origin_ns=0 and remote_origin_ns=0. This is a
chosen simulation-domain epoch, not a claim that PX4 HRT or host steady time starts
at zero. Positive reply times come only from committed actual PostUpdate samples
starting at iteration 1 / sim 1 ms. No startup-default UpdateInfo is a sample.

The source lane must retain every actual iteration through 25000, exact 1 ms
increments, unpaused state, callback steady time, journal-return time and selected
sample identity. No interpolation, repeated-frame advancement or synthetic clock
tick. A session replacement, regression, missing iteration, pause, stale sample
or failed write refuses; it cannot silently rebase the origin. Timestamp selection
at reply preparation is not the simulator or PX4 clock at UDP receipt.

At each send, link original datagram bytes/request ts1, receive steady time,
selected clock observation, response tc1, descriptor/process/session identity,
send attempt and actual return. Preserve in-flight effects if a later gate fails.
Link each response to the actual owned PX4 timesync_status record, including its
timestamp, remote_timestamp, RTT, observed and estimated offset. Recompute with
SerialTimesyncObserver and the pinned filter without modifying either to fit data.
Qualify observed behavior of this isolated study only. Matching endpoint/process
observations do not authenticate every UDP sender or prove hostile same-UID
exclusion, and listener ordinal is not a uORB generation number.

Do not require zero measured offset simply because remote origin is zero; the
two asynchronous clock consumers need observation. Conversely, do not invent a
post-run offset or subtract drift to make the status match. Store diagnostic
offset/RTT distributions separately from exact protocol acceptance.

## Startup, maintenance and cleanup

Retain the original 8 s wall startup deadline from the production wire owner,
500 accepted cold-start samples, 2 s operational/source/pending limits and the
original 300 s capture/supervisor budgets. Do not restart the deadline after
renderer or listener setup. The 10 s cold source-readiness bound is a different
existing limit and does not extend the wire's 8 s deadline. Retain the existing
8 s simulation readiness anchor bound and 200 ms future anchor separately.

Only the existing TIMESYNC reply and owned MESSAGE_INTERVAL GET/SET exchange
are allowed: read baseline, apply 10000 us, read back, bootstrap, restore baseline
and verify before maintenance. Current MAVLink documentation is not authority to
send additional commands. With a nominal 100 Hz stream the first-to-500th request
spacing is 4.99 s simulation; it is not a wall-time guarantee. Rejected exchanges,
rate scaling, startup and scheduling can exhaust the unchanged limit. Report the
observed bottleneck; do not call it a fruit-fly learning failure.

Continue the same reader/filter/descriptor across maintenance. Require at least
two accepted, correlated maintenance pairs and healthy progress through the end;
the boundary snapshot is not an extra sample. Preserve all rejected input. Retain
unarmed heartbeat observations and ULog arming state. Unexpected arming stops
ordinary sends and force eligibility; do not send a disarm command from this study.

On failure, preserve capture_failed. Use only the existing 10 s restoration-only
allowance (2 s per operation) before owned PX4 teardown, without clearing failure,
resuming force or granting fusion. An unavailable/changed peer, missing ACK or
readback yields failed restoration. Retain supervisor disk/in-memory events,
individual PX4 exit, ULog, group identity and post-reap result with the current
original-group/escaped-descendant limitations. Do not expand lifecycle governance.

## Offline gates and later fault studies

Before any live dispatch, the new pure study/audit code must reject: reuse of a
startup result as a live pass; absent or fabricated status correlation; send
count without matching PX4 status; clock sample omission/replay/regression;
500 modeled samples with an unproven cold epoch; wrong or changed owner/session;
armed observation; incomplete/failed baseline restoration; declaration drift;
normal success with missing native/sensor/ULog/runtime evidence; and output
overwrite. Use existing retained in-process records as synthetic fixtures only.

After a qualifying normal run, separate prospective fault profiles should cover
withheld status/response, IMU loss and native-session replacement. Fault schedules,
expected capture_failed and cleanup requirements must be frozen before each run;
simulated dropped traffic is distinguished from actual network loss. Existing
source-loss/native-restart profiles are reused where their exact behavior matches.
No fault injection method, seed or dispatch is authorized by this outline alone.
Failure of the normal run blocks these new live cases, not offline diagnosis.

## Completion and downstream boundaries

The auditor consumes raw bytes/clock/status/command journals, source/native logs,
runtime declarations and pre/post evidence, ULogs, supervisor logs and dispatch/
completion, not just result.json. It returns separate preparation, delivery,
observed clock, bootstrap, maintenance, restoration and workload-completeness
results. Missing evidence is false or indeterminate. Offline constants that say
network_authorized=false must remain offline provenance, not be overwritten.

Even a fully passing live study keeps ODOMETRY delivery, EKF2 fusion, flight and
hardware calibration false. It enables preparing the later unarmed receiver
study; it does not execute it. Five-camera 0.873 RTF remains below 0.95. The full
fruit-fly policy, fair baseline, 5/20-aircraft gates and hardware work remain open.
