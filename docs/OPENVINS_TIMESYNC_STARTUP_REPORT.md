# PX4 receiver startup feasibility and preflight correction

Date: 2026-10-08

## Decision

The existing receiver preflight is **not yet launch-ready**. Its pure clock
filter and parameter rollback checks remain valid within their tested scope,
but the earlier Task 4 completion statement did not establish a feasible live
startup schedule or a live observation of PX4 convergence before first ODOMETRY.
The corresponding plan checkbox is reopened. Historical archives are retained
unchanged; their completion flags are not permission to launch.

This stage performs source inspection and seven synthetic budget cases only.
It starts no PX4, simulator, estimator, training or network publisher and changes
no live parameter or stream rate. Receiver and fusion qualification remain false.

## Sources and reuse

The new source bundle is `results/openvins-timesync-startup-design-dev-1701`.
`source-manifest.json` and `source-supplement.json` preserve URLs, hashes and
retrieval failures. The stream `TIMESYNC.hpp` and library `Timesync.hpp` collided
on the Windows case-insensitive filesystem: the failed exclusive write remains
recorded, and the library header was retrieved as `library-Timesync.hpp`.
No original file was overwritten. A web lookup of the guessed
`src/systemcmds/topic_listener/listener.cpp` returned 404; this work makes no
claim about that listener's installed capabilities.

- Reuse fixed PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, BSD-3-Clause.
  Saved repository metadata reports non-archived, last push
  `2026-10-07T16:06:37Z`; this is a repository observation, not installed binary
  equivalence or a reason to upgrade the pinned receiver.
- Reuse installed pymavlink 2.4.49, whose LGPL package provenance was recorded
  in the earlier preflight. New repository metadata reports non-archived and
  last push `2026-10-06T23:56:46Z`, but its license field is `NOASSERTION`; that
  API field is not substituted for the retained package license.
- The [MAVLink timesync service](https://mavlink.io/en/services/timesync.html)
  and [command service](https://mavlink.io/en/services/command.html) are current
  documentation. The timesync page describes v2 targeting extensions; future
  transport must verify the installed generated dialect and pinned receiver
  rather than assume those extensions isolate replies.
- Use the existing pure `BoundedTimesyncVerifier` for synthetic predictions.
  No dependencies are installed. ROS/DDS is not introduced for this feasibility
  check. An observer through existing PX4 facilities is preferred over a new
  patched flight-controller binary, but no observer is qualified here.

This is protocol/startup work; it changes no OpenVINS algorithm or paper-derived
model. The existing OpenVINS research and uncalibrated raw-IMU limitations remain.

## Source-backed findings

The pinned [stream configuration](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/mavlink/mavlink_main.cpp)
sets onboard TIMESYNC to 10 Hz. The
[filter header](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/lib/timesync/Timesync.hpp)
requires 500 accepted exchanges, with RTT strictly below 10 ms. At exactly the
nominal rate, first-to-500th request spacing is 49.9 seconds. This is a nominal
scheduling calculation, not a measured minimum: stream scheduling, link rate
scaling and rejected exchanges affect actual timing. It does not support the
existing 8-second readiness window or 25-second total study as written.

`mavlink_receiver.cpp::set_message_interval` supports a temporary interval via
`MAV_CMD_SET_MESSAGE_INTERVAL`, and `get_message_interval` reports the configured
interval. Configuration crosses the stream thread: command acknowledgement is
not sufficient proof of applied or achieved rate. `mavlink_stream.cpp` can scale
nonconstant streams by the link rate multiplier. No change is applied here.

`mavlink_timesync.cpp` handles positive `tc1` replies by updating its filter; the
reviewed function itself does not correlate sender or outstanding request.
Transport identity, channel isolation and request/reply evidence must therefore
be separately established. Do not assume current protocol docs enforce them.

The [TimesyncStatus schema](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/TimesyncStatus.msg)
contains offset, remote time, RTT and source protocol, but neither accepted
sample count nor a convergence flag. The library publishes through
`PublicationMulti`: the correct instance must be identified, not assumed to
be instance zero. Status is published for rejected RTT samples too. Its
publication timestamp is a separate `hrt_absolute_time()` call, so it must not
be substituted for the receive instant in the filter. With an unambiguously
matched original request, the reported RTT gives the filter's receive time at
microsecond precision. Completeness and identity still need proof.

Thus 500 replies sent by the companion, 500 status rows, a stable offset, or a
post-run ULog alone do not satisfy the required **live pre-publication** gate.
The current pure verifier requires receive-time data unavailable merely from a
companion send log. Using the companion wall clock instead would not fix this.

## Executed offline budget probe

`probe_budget.py` uses the unchanged production verifier, denies socket creation,
hashes itself and the consumed module, and writes exclusively to `budget-v2.json`.
The original `budget-v1.json` and exact probe source are retained. Review noticed
that the late-start time was computed but lacked an explicit equality assertion;
v2 adds that assertion without changing any scenario or expected result.
All exchanges are synthetic with a slope-one remote clock, a constant offset,
and either 2 ms accepted RTT or exactly 10 ms rejected RTT. No actual scheduler
or transport throughput is measured.

|Synthetic case|Accepted|First modeled convergence (sim s)|Ready by 8 s|
|---|---:|---:|---|
|10 Hz, first request 0.1 s, 250 requests|250|None|No|
|10 Hz, first request 0.1 s, 500 requests|500|50.002|No|
|100 Hz, first request 2 s, 500 requests|500|6.992|Yes, model only|
|100 Hz, first request 4 s, 500 requests|500|8.992|No|
|100 Hz, all 500 RTTs at rejection boundary|0|None|No|
|100 Hz, 500 requests, every fifth rejected|400|None|No|
|100 Hz, 625 requests, first request 2 s, every fifth rejected|500|8.232|No|

All seven expected outcomes and exact listed convergence times were asserted.
The one passing synthetic budget is **not** a demonstrated startup solution.
The previous full suite (2050 passed) belongs to receiver parity; it was not
rerun or relabeled as verification of this source-only investigation.

## Next implementation decision and exit requirements

Prefer investigating a reversible 100 Hz TIMESYNC candidate within the existing
study over silently adding a 50-second warmup. Extra message/observation work is
additional load, not capacity optimization. The 100 Hz choice is a candidate,
not a qualified runtime profile, and adds a command side effect beyond the old
EV_CTRL-only declaration. Do not dispatch it under the old preflight.

Before a replacement launch declaration can be qualified:

1. Establish a read-only, bounded live convergence observer for the exact PX4
   instance/channel. Prove complete status delivery and request matching, or
   obtain a source-backed direct convergence observation. Any dropped, ambiguous,
   foreign, stale or reset observation closes the gate. Do not write an adapter
   that labels unobservable fields as known. If installed facilities cannot
   supply this, document the specific required instrumentation and changed
   binary provenance before choosing it. A post-run audit cannot replace this.
2. Implement a stream-interval transaction with original interval snapshot,
   command intent recorded before send, acknowledgement plus readback, actual
   request timing evidence, and restoration of every attempted change even on
   lost ACK or cancellation. Refuse an unknown original interval; do not restore
   a guessed 100000 us. One command in flight; unmatched or delayed responses
   cannot advance its phase. Restoring interval is separate from parameter
   rollback and both outcomes must survive failure.
3. Bind the observer, scheduling candidate and rollback to a new immutable
   preflight. Define clock-session start and gate placement against the existing
   estimator-aware readiness/immutable force anchor. Do not reset the force
   anchor, restart a 25-second timer, pause lockstep, or waive the 8-second limit
   to make the candidate fit. The 200 ms future anchor and all 2-second source
   watchdogs remain. Failure to observe convergence by the deadline is a retained
   startup failure with zero ODOMETRY, not permission to extend the deadline.
   The old plan's "before the study timer" warmup wording conflicts with the
   unchanged total-duration/readiness condition. That requirement must be
   explicitly reconciled in the replacement design; this report does not claim
   that an in-window candidate has already satisfied the old wording.
4. Cover missing/lost/late acknowledgements, rate readback mismatch, foreign or
   duplicate replies, partial status coverage, process/session replacement,
   RTT rejection, deadline expiry, log/close failure and cleanup with synthetic
   transport tests before any newly authorized unarmed physical trial.

An extended warmup is a rejected *implicit* workaround, not inherently invalid
research. It would need a separately named condition, full-load evidence and a
new discussion of readiness and covariance applicability. Lowering the 500
window, increasing RTT tolerance, repeating samples, or assuming delivery are
rejected because they change or bypass the pinned gate.

The next concrete action is the read-only installed-observer capability check,
not another ordinary 25-second VIO run. Physical ODOMETRY, parameter/stream
changes, EKF2 fusion and arming remain outside this stage's authorization.

## Status

|Status|Scope|
|---|---|
|Verified|Pinned source semantics; seven synthetic scheduling/RTT cases; recorded preflight gap.|
|Implemented previously|Pure clock/filter and parameter transaction; offline receiver field comparator.|
|Unverified|Actual convergence observer, rate apply/restore, timing budget on WSL2, receiver delivery, EKF2 fusion.|
|Preserved failures|All historical physical failures; original source filename collision and failed listener lookup; modeled deadline/RTT failures.|

No claim about fruit-fly learning performance follows from this protocol gap.
The complete policy, fair baseline comparison, closed-loop flight and 5/20-aircraft
validation remain downstream; hardware and flight qualification remain absent.

## Review and evidence

Independent read-only review confirmed the pinned-source interpretation and
identified the timer-wording conflict and missing late-start equality assertion.
Both were corrected and rechecked with no unresolved findings. These are
documentation/experiment-coverage corrections, not production bug fixes.
The probe's Ruff check and Git whitespace check passed. No full regression was
needed for this documentation-only change and standalone offline experiment.

The source/probe/results/review bundle is sealed as
`evidence/openvins-timesync-startup-design-dev-1701.zip`; its companion manifest
records the archive SHA-256 and the member hashes. No historical ZIP is modified.
