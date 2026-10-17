# TIMESYNC channel ownership feasibility

Date: 2026-10-08. Parent:1287aca. Research only; no production launch change.

## Decision

Use a private loopback-only network namespace as the next candidate for the
owned study, rather than treating PX4's selected UDP partner as an ingress ACL.
The installed WSL supports this using the normal user and existing tools. One
bounded ordinary-UDP probe passed namespace separation. This neither qualifies
PX4 channel ownership nor replaces the cold-start/first-status bootstrap.

No PX4, Gazebo, OpenVINS, training, MAVLink traffic, ODOMETRY, parameter or stream
change was run. `fusion_qualified=false`; actual isolated-study compatibility,
listener startup and 500 accepted updates within the existing budget are untested.

## Findings that change the next action

Eight selected installed files match fixed PX4
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4` byte-for-byte (BSD-3-Clause).
`sources.json` retains original paths, primary URLs, both copies and hashes.
This is not proof of whole-build equivalence or an actual receiver experiment.

- [Receiver](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/mavlink/mavlink_receiver.cpp):
  UDP uses `recvfrom`. Once partner initialization is true, this path parses
  incoming bytes without comparing each packet's IP/port to that partner.
  Normal-mode `handle_message` calls the TIMESYNC handler after its switch.
- [TIMESYNC handler](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/mavlink/mavlink_timesync.cpp):
  a positive `tc1` is passed to the filter, without matching an outstanding
  request or filtering sysid/compid in that handler. A targeted companion reply
  or source_protocol0 therefore does not establish exclusive ownership.
- [Startup](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/ROMFS/px4fmu_common/init.d-posix/px4-rc.mavlink):
  ordinary SITL configures GCS/API/payload/gimbal channels, with forwarding flags.
  For instance8 the API ports are14588/14548. Each normal receiver has its own
  MavlinkTimesync member. Forwarding is queued for outbound `resend_message`,
  not shown by this path to directly update another receiver's filter. No claim
  that every forwarded packet contaminates every filter is made.
- [PublicationMulti](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/common/uORB/PublicationMulti.hpp)
  advertises lazily, initially requesting0. DeviceMaster selects an available
  multi-instance. The Timesync member is a PublicationMulti; consequently a
  MAVLink channel index is not a guaranteed `timesync_status` instance number.
  Cold lifecycle and the first reserved reply must establish that association;
  do not select a convenient later status or infer it from source_protocol.

## Candidate comparison and provenance

|Candidate|Decision and cost|
|---|---|
|UDP partner/sysid filtering alone|Rejected: selected source does not supply the required inbound isolation.|
|Host firewall or PX4 receiver patch|Not selected: changes host policy or pinned receiver semantics; requires additional rollback/build equivalence.|
|Private user+network namespace, loopback only|Proceed to a bounded launcher design. No packages, host root or veth needed in this probe. Future runtime binding and Gazebo discovery compatibility remain work.|

[Linux namespace API documentation](https://man7.org/linux/man-pages/man7/network_namespaces.7.html)
describes separate network stacks/ports. The
[unshare interface](https://man7.org/linux/man-pages/man1/unshare.1.html)
supports creating user and network namespaces before executing a child.
Installed util-linux2.39.3-9ubuntu6.6 (`unshare`, GPL-2-or-later, fixed upstream
v2.39.3 source retained) and iproute2 6.1.0-1ubuntu6.2 (`ip`, package copyright
GPL-2) were reused. No new estimator, paper-derived algorithm or noise model was
introduced; this is an OS/protocol integration question. Python3.12.3 and kernel
6.6.87.2-microsoft-standard-WSL2 were recorded. Installed binary hashes are not
claims that Ubuntu patches equal upstream.

Metadata observed2026-10-07 UTC: PX4 and util-linux were nonarchived with last
push2026-10-07T16:06:37Z and2026-10-06T12:24:38Z respectively. These are repository
observations, not support guarantees for the pinned versions. iproute2 upstream
maintenance was not freshly assessed; its installed package was only reused.
Primary reference URLs, responses, copyright files and observation times are
retained. No capacity, throughput, memory or CPU improvement was measured.

## One actual namespace fixture

The prospective `PROBE.md` and throwaway `namespace_probe.py` are retained in
`results/openvins-timesync-channel-dev-1701`. The script is not a production
launcher or a general fault-tested supervisor. All payloads are random ASCII
tokens, not MAVLink. An earlier `unshare ... true` capability check returned0;
only this subsequent socket fixture produced the retained detailed JSON.

Parent UID1000 remained in net namespace4026531840. Child PID396 entered network
namespace4026532229 and user namespace4026532228; child UID0 mapped solely to
host UID1000. Parent and child simultaneously bound127.0.0.1:56202. The child had
only loopback and enabled it inside its own namespace. No external interface,
route, firewall, mount or host network setting was changed by the harness.

The host token returned to its host socket. Two child tokens from distinct ports
45659 and35200 both reached the child socket; neither stack observed an extra
token during its one-second bounded observation. Thus this fixture shows host
separation **and** that two peers inside the namespace still share access.
It is not a stress test, hostile isolation proof or a MAVLink receiver test.

The parent network/user identity, complete recorded link/address/route inventory,
script/unshare/ip/Python hashes matched before/after. Child exit0; no emergency
kill was needed. Readiness has a five-second total bound and64KiB limit; fixed
subcommands and child completion are bounded separately. The report makes no
production cleanup or crash-injection qualification from this success.

## Remaining launch gates

The next implementation should be one narrow owned-launch boundary, tested with
ordinary subprocess/socket fixtures before any PX4 launch. Require fresh network
and user identities; loopback-only topology; no inherited network FDs; explicit
child ownership and original-group cleanup; declared `unshare`/`ip` runtime inputs.
Reuse existing supervisor evidence rather than creating global process governance.
All study networking participants must belong to the chosen namespace; any
external proxy or bridge would invalidate this narrow isolation argument.

This does not isolate filesystem UNIX socket paths, ensure a fresh PX4 filter,
or prevent an administrator/hostile process joining the namespace. Keep explicit
PX4 lifecycle and socket-path ownership checks. Gazebo discovery, rendering and
existing UID-dependent environment behavior have not been exercised here.

Once that offline launcher boundary is tested, compose a first-reply bootstrap
with the existing decoder/observer and reversible interval transaction. Establish
uORB instance association from the controlled cold lifecycle, first reserved
reply and its status; withhold subsequent replies until it matches. Missing,
ambiguous, extra or stale status must refuse. Do not invent a protocol nonce or
uORB generation. Still retain25s total,8s readiness,2s watchdogs and500 accepted
samples;100Hz configured output is not evidence of accepted throughput.

## Verification status

- Verified here: eight selected source comparisons, one real namespace/socket
  fixture, recorded binary/script and parent-topology stability.
- Source-supported, not executed in PX4: ingress and multi-instance semantics.
- Designed next, not implemented: production owned isolated launcher/bootstrap.
- Untested: PX4/Gazebo in that namespace, live listener, synchronization rate,
  receiver delivery, EKF2 fusion and closed-loop policy control.
- Historical failures unchanged: old VIO drift/startup/capture failures and
  five-aircraft0.873RTF below0.95. Nothing in this probe repairs or invalidates them.

No production or test-suite source changed. The prior2440-test result remains
historical; it was not rerun for this documentation/research-only stage. Evidence
verification recomputed all eight source pairs and five primary-reference hashes,
checked fixture consistency and confirmed the probe script matches its runtime
hash. Independent read-only review found no actionable Important or Minor issue.
Git whitespace checks passed; no test-suite or full-repository lint pass is claimed.
The filtered process scan found no matching simulator/estimator/test/probe process;
it is not an exhaustive escaped-process proof. The archive is
`evidence/openvins-timesync-channel-dev-1701.zip`; its external manifest records
the SHA-256 and verified member hashes/CRC without rewriting prior evidence.
