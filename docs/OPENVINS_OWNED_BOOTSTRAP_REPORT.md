# Owned listener and cold bootstrap composition

The existing listener transport is now connected to the cold-bootstrap state
machine. One ordinary local server run completed empty snapshot, first reserved
reply/first snapshot, latest replay counted once,500 modeled accepted samples,
and final zero-status EOF across three owned connections. Five negative cases
refused as intended. This proves a local socket/model composition, not actual
PX4 filter convergence, a transmitted MAVLink reply or VIO-to-EKF2 fusion.

Spec/plan: `superpowers/specs/2026-10-08-owned-bootstrap-composition-design.md`
and `superpowers/plans/2026-10-08-owned-bootstrap-composition.md`.
Designc6c401b, initial implementationaae81cc, final deadline/harness5e8b38a,
test correction and frozen runtime producer1cd6e93.

## Reused sources and design

The fixed PX4 BSD-3-Clause client/server protocol remains
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4`. The retained
[server implementation](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/posix/src/px4/common/px4_daemon/server.cpp)
accepts the terminal isatty byte, writes the return trailer and shuts down the
command connection. It does not require a client half-close. Installed Python
3.12.3/PSF and Linux SO_PEERCRED are reused. No package or new algorithm was added.
The existing listener, modeled filter and bootstrap interfaces were inspected
before design; selected hashes and reuse/rejection reasons are retained in
`results/openvins-owned-bootstrap-dev-1701/research.json` and
`reused-interfaces.json`. Prior PX4 nonarchived/last-push metadata is reused,
not a fresh maintenance observation or a claim about installed upstream patches.

`OwnedBootstrap` holds one immutable registered process identity and socket path.
It creates at most three sequential listener transports, each checking the peer
on its own actual descriptor. One stream stays connected across serialized
reply intents. An owner hash is only a comparison tag; it is not proof of a cold
PX4 epoch, channel ownership or absence of other producers.

The original8s deadline is shared by all commands. Existing2s progress, pending
reply and complete-frame checks remain. A separate final frame deadline stays
active after the internal model reaches done, through terminal logging. Snapshot
confirmation needs complete zero-status EOF. Stream bytes feed the existing
state machine; parsed rows remain provisional until the stream finishes cleanly.
Public readiness is suppressed by any outer coordinator failure, including
failure after the internal model alone has reached done.

`reserve_reply` records an intent, never sends a reply. The production coordinator
does not launch processes, unlink sockets, change parameters or streams, publish
ODOMETRY or implement a MAVLink responder. All live/network/fusion flags remain
false. Synchronous journal and process checks require outer supervision; a poll
timeout is not asynchronous cancellation. Memory/evidence bounds and the one
pending reply rule are inherited rather than relaxed.

## Tests and independent review

Initial RED was a missing-module collection error, not a behavioral assertion.
The first focused suite passed120 tests; additional configuration and terminal
logging coverage brought it to127. Initial test style checks found23 Ruff errors,
corrected before the implementation commit.

Independent read-only review found one remaining Important: entering internal
done bypassed the2s final frame check. Two exact2s assertions failed while their
8s counterparts already refused. Keeping the final frame timestamp through
outer completion fixed both. An early-EOF harness expected-error string was
also corrected against the existing decoder before its first execution; it was
not a failed runtime case. The reviewer reported no other actionable finding.

A broad test-text edit accidentally substituted an undefined variable in the
older late-journal test. Its broad error assertion let an intermediate130-pass
run pass for the wrong reason; Ruff exposed the undefined name. A new specific
refusal-reason assertion failed, then passed after restoring the intended clock
value. That intermediate run is not presented as validation of the late path.
Final focused adjacent suite:130 passed. Final changed Ruff/diff checks passed.

Full regression completed with exit0:3193 passed,3 skipped,2 existing warnings
in334.51s. The suite includes existing temporary CLI smoke fixtures; no new
training study was launched. Final changed-file Ruff and Git whitespace checks
passed; no whole-repository lint pass is claimed.

## One frozen ordinary-process matrix

`kernel-v1` predeclared all six cases, original8s/2s budgets,500 count,1ms client
polling, exact commands and selected source/Python hashes. Each child owns a
private `/tmp/fly-bootstrap-*` socket. The separate stdin pipe carries fixture
indices after reply intents; it is not a MAVLink channel. Status fields use a
frozen synthetic template with monotonically increasing request/remote values,
2ms RTT and zero offsets. Those synthetic remote times are not host elapsed
time or observed PX4 filter clocks.

|Case|Elapsed seconds|Modeled accepted at stop|Outcome|
|---|---:|---:|---|
|normal500|2.280928|500|Complete; latest replay counted once.|
|wrong-replay|0.032168|1|Listener ordinal mismatch refused.|
|early-eof|1.155689|250|Premature EOF refused.|
|nonzero-final|2.287402|499|Nonzero trailer refused; coalesced final row was not committed.|
|silent-mid|2.029057|2|Complete-frame timeout refused.|
|journal-failure|0.009018|0|First reply-intent journal failure refused; no fixture reply sent.|

Normal startup used two exact snapshot commands and one500-record stream command.
All five failures remained false for completion and live/fusion qualifications.
All six direct children received EOF and exited0 without TERM/KILL. The journal
failure case opened only its empty snapshot connection; the other cases opened
three. Disk coordinator journals equal in-memory evidence in every case. The
author's fixed-evidence audit is `runtime-audit.json`; no independent runtime
rerun is claimed.

The2.28s normal result measures this private fixture only. It cannot qualify
actual PX4 accepted sample rate, clock convergence or real flight readiness.
The server's first stream frame was deliberately fragmented; actual read
boundaries are not assumed to equal server write boundaries.

Selected source/Python hashes were stable before/after. Linux scratch logs are
deliberately retained, with explicit paths, even on copy failure; successful
copies to the workspace were hash-compared. No unrelated process was terminated.
The first post-run Git-blob export check refused because the harness working-tree
bytes used CRLF while Git stored LF. This was not a runtime drift: recorded
pre/post/current bytes all match. Exact still-matching selected files were copied
afterward, with Git-versus-working-tree hashes and normalized-content equality
recorded in `source-copy-provenance.json`. They are post-run copies, not claims
of contemporaneous source copies or whole-runtime closure.

## Remaining work and boundaries

Verified here: real ordinary socket framing, owned process/peer association,
three-stage ordering, one counted-once replay, modeled500-sample convergence,
shared deadlines and the named fail-closed cases. Implemented but not verified
against live PX4: the coordinator/transport interfaces.

Still missing: actual cold PX4 epoch evidence, exclusive channel/source and
responder binding, correlation between real TIMESYNC requests, replies and
listener status, selected runtime/stream-interval transaction integration,
measured live accepted throughput and actual VIO-to-EKF2 injection. These need
their concrete staged design/preflight and live authorization; this matrix
does not grant it. The next implementation should address real request/reply
provenance without reimplementing another filter or broad process supervisor.

Physical VIO and health/covariance results retain their limited simulation domain.
No physical study, new training experiment, arming or5/20-aircraft expansion ran.
The complete fruit-fly learning/decision/division and fair upstream baseline
comparison remain project requirements. Five-camera0.873RTF remains below0.95;
neither load nor threshold changed. Native Linux installation is not required
for this stage. All earlier physical/platform/protocol failures remain preserved.

The new sibling evidence manifest records the archive hash and verified member
hashes/CRC. The archive retains its pre-publication plan snapshot; final
publication checkboxes are completed afterward.
