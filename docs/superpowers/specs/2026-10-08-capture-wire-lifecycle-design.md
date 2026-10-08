# Capture wire lifecycle: one reader from startup through cleanup

## Intent and authority

The user's objective remains a fruit-fly-inspired autonomous swarm, with actual
PX4/sensor/safety evidence and fair baseline comparison. This change closes a
specific integration dependency before VIO-to-EKF2 testing; it is not a new goal.
User preapproval permits routine design, offline implementation and review.
It does not turn this design into authorization to execute UDP/PX4/physics,
ODOMETRY, EKF2 parameter writes, arming or training. Current validation uses
in-process doubles and real installed codecs/components only.

## Evidence and selected approach

At bd04203, actual capture has one `recv_match(type="HEARTBEAT")` thread, which
consumes other message types. ObservedWireSession receives whole datagrams but
stops at bootstrap completion; its receiver, wire, owned listener and outer
session each enforce an eight-second bootstrap deadline. Merely placing it next
to the old reader, or resetting its start time after completion, is incorrect.
The previous default-10Hz/500-sample timing finding is not new work to repeat.

Select a single receiver and decoder for the entire capture lifetime. Refactor
existing composition to separate bootstrap qualification from ongoing transport,
instead of adding another nested verifier. Keep the legacy mode unchanged.
Reject parallel readers (packet loss/racing), a second socket (channel identity
change), and restarting the bootstrap session (lost sequence/clock/failure state).
No dependency installation, general process manager or new VIO algorithm.

Source basis: fixed PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4, BSD-3-Clause;
pymavlink2.4.49, generator (L)GPLv3/generated-output exception as recorded in the
wire report; Python3.12.3 PSF; installed Gazebo Sim8.15 Apache2. Reuse retained
source/maintenance observations rather than claiming new release activity.
The installed mavutil source hash and receive implementation are in the prior
wire archive. Current official references consulted on 2026-10-08:
[TIMESYNC](https://mavlink.io/en/services/timesync.html),
[command service](https://mavlink.io/en/services/command.html),
[Python socket](https://docs.python.org/3.12/library/socket.html).
Current protocol-v2 target extensions cannot be assumed in the pinned codec.
Command acknowledgements require separate message-interval readback; neither
proves an achieved rate. No paper-derived estimator/calibration change is proposed;
existing OpenVINS algorithm research remains applicable.

Costs: one existing receiver thread, bounded journals and queues, one native
estimator worker; actual runtime overhead is unknown until a later authorized
study. Source/codec reuse lowers adaptation cost, but lifecycle integration is
still substantive and must not be presented as already tested.

## Lifecycle and invariants

Use explicit PREPARED, BOOTSTRAP, MAINTENANCE, STOPPING, CLOSED/FAILED states.
One non-reentrant owner advances receive/command/listener work. The main Gazebo
thread advances simulation independently; no wait-for-network inside PostUpdate.

PREPARED: validate declaration, runtime binding and mode before side effects;
register cleanup before a resource can escape. Construct no second receiver.
Persist pre-freeze before NativeClient/TestFixture/PX4 as today. At PX4 ownership
availability, bind one descriptor and immutable PID/start/namespace identity.
Identity changes fail; endpoint equality alone is not sender authentication.

BOOTSTRAP: retain the existing cold-listener evidence, eight-second deadline,
500 accepted samples, two-second progress limits and existing clock mapping.
Candidate interval10000us is owned via baseline/apply/ACK/readback/restore,
not a new PX4 parameter. All setup work must fit the existing readiness budget;
no implicit preliminary warm-up or restart of the deadline. The interval
transaction body is bootstrap only, not the whole capture. On successful500,
restore/read back the baseline before entering MAINTENANCE; restoration still
must fit the startup8s gate. STOPPING retries no ambiguous command; it attempts
the owned baseline restore only if the transaction still has an outstanding
mutation. Ambiguous baseline,
stale/duplicate/wrong ACK and lost readback fail. One command at a time; the
pinned protocol has no unique transaction nonce, so record that limitation and
do not retry ambiguous mutations. Keep heartbeat processing during command waits.

MAINTENANCE: a successful bootstrap is immutable historical evidence, not a
permanent healthy flag. Continue heartbeat and TIMESYNC handling on the same
reader/codec/sequence, with process, clock, source and pending-message health
checks. Preserve two-second freshness deadlines. The eight-second *bootstrap*
deadline is not stretched: after its verified transition, total capture is
bounded by the existing declared300s wall and25s simulation budgets. Old helper
constructors/defaults keep their original bootstrap-only behavior. Do not clear
failures, counts, last request identity or monotonic high-water marks at transition.
Runtime health and bootstrap-completed fields are distinct. Implement an explicit
one-time `take_continuation()` transfer after the finite bootstrap listener has
finished successfully and has no pending reply. The internal continuation owns
the existing SerialTimesyncObserver/filter state, last request/response identity,
last status timestamp and codec sequence; it is not a user-supplied success dict.
The bootstrap object remains terminal and cannot consume the transferred state.

Open one maintenance listener on the same owned daemon/path/default topic
instance before resuming replies. Give each listener its own recorded epoch and
raw ordinal. Reset only that listener's ordinal check, never the filter, accepted
sample count, timestamps or replay history. Its initial retained status must
exactly equal the previous accepted status (apart from the new raw listener
ordinal/header); record it as a boundary snapshot, not a new accepted sample.
Only after that snapshot may the next reply be reserved. Subsequent status must
match the single pending reply and advance timestamp/identity as before. Duplicate,
replayed, unsolicited or missing status fails; repeated boundary snapshots fail.
Raw bytes/ordinal and the explicit epoch mapping stay separate from normalized
observer input. No invented uORB generation number.

Use a finite4096-record maintenance subscription. Together with the existing
4096 total datagram limit it cannot legitimately exhaust before capture stops;
unexpected exhaustion fails rather than reopening another listener. At capture
stop, cancellation of this subscription is explicit, with its partial bytes,
record count and close result retained; it is not fabricated as a normal finite
command exit. Prove cancellation handling in the injected daemon tests. A second
maintenance listener or rollover attempt fails in this narrow profile. No ongoing
correlation is optional: it is a required completion gate, not a heartbeat-only
fallback.

PostUpdate: register one wrapper around the existing reference/motion callback,
record the actual callback's iteration/time in JournaledSimulationClock, and keep
its state/failure accessible to the receiver and pre-step safety check. No pose,
velocity or other truth enters a wire/VIO payload. Receiver time remains actual
recvmsg-return monotonic time. Preserve the existing arming and owned-ready mapping
effects using that receive time; dispatch through the tested journaled fanout.

STOPPING: block new ordinary work/force first, perform any outstanding owned interval
restoration while the same sole reader and PX4 are still available, retain each
attempt and ACK/readback error, then join receiver and close descriptor. Owned
PX4 cleanup follows restoration and must remain bounded on missing replies.
Integrate with CaptureJournal priorities rather than a new cleanup framework.
Failed restore is a failed capture even if the process exits. Preserve primary
failure and all cleanup failures; interruption cannot silently skip restoration.
Unavailable/dead PX4 is recorded as inability to restore, never a fabricated ACK.

Do not call synchronous `TimesyncIntervalTransaction.run()` from the receive
thread. Keep it as the existing offline oracle; implement its phases as one
nonblocking exchange advanced by the sole owner: baseline-query, apply,
apply-readback, bootstrap-body, restore, restore-readback, final-readback. Each
`poll()` consumes at most one datagram and advances at most one command effect;
decoded heartbeat/status work stays serviced. At most one command is outstanding.
An absolute two-second bound per command is capped by the shared startup deadline;
there is no retry or new deadline on a partial response. Feed only validated
decoded ACK/interval rows with original receive time; `poll()` never recursively
receives. Parity tests compare outcomes with the existing offline transaction.

If the primary pipeline fails or startup expires with a mutation outstanding,
enter a distinct restoration-only path. Keep primary failure permanently latched;
allow only baseline SET and associated ACK/GET/readback traffic, not ordinary
TIMESYNC replies, estimator output, force or requalification. This path has one
absolute10s cleanup deadline from the first STOPPING transition (repeat calls
cannot renew it), with2s per operation. It still requires unchanged owned process,
descriptor, peer and monotonically valid local time; missing/dead/changed identity
refuses restoration and records why. Decode and retain incoming safety messages;
an armed heartbeat aborts further sends. Failed source/fanout is not erased or
used as a grant. If interruption repeats, preserve the interruption and incomplete
restore, close owned resources and re-raise. Cleanup allowance does not extend
capture or bootstrap success deadlines.

## Bounded retention

Do not enlarge legacy constructors'8192-event/4096-selection defaults. The new
lifecycle profile retains the total4096-datagram limit and the bootstrap8s/500
checks, but uses a declared segmented journal for its longer event history:
at most64 segments of8192 events and512MiB total across that study's wire,
receiver and listener records. This is a prospective resource cap, not a measured
performance result. Every event keeps an absolute index, phase and source;
finalized segments carry exact byte/hash/member metadata. Write/flush/close must
succeed before evicting a completed in-memory segment. Do not drop, truncate,
overwrite or reset sequence counters; quota/I/O failure fails closed. Only the
current segment and bounded protocol state stay in memory; evidence returns
segment references rather than materializing the whole journal. Existing default
evidence APIs remain unchanged. These storage limits are not eligibility/accuracy
thresholds or a load reduction. If actual traffic exceeds4096 datagrams, keep the
failure; do not raise the cap after observing a test run. Capacity tests cross the
old8192-event boundary, validate every retained index/hash and exhaust both the
segment and byte quotas. No claim that a nominal rate guarantees fitting the cap.

## Completion evidence for this implementation

One in-process test must drive the actual capture registration/runner path with
fake socket/process/fixture, real codec/fanout and injected lifecycle services:
startup, command exchange,500 accepted samples, successful baseline restoration,
the maintenance listener boundary snapshot, at least two correlated maintenance
reply/status pairs, post-bootstrap heartbeat and declared stop. Assert the legacy reader is never constructed in the new mode,
one read owner exists, callback registration occurs once, and all resources close.
No actual socket/Server/native estimator may be constructed by this test.

Fault matrix: constructor/registration failure; duplicate reader/reentry; clock
or descriptor/owner replacement; stale heartbeat/source; queue/log failure;
armed packet; malformed mixed datagram; missing/late/wrong ACK/readback; duplicate,
replayed or absent maintenance status; invalid continuation/repeated rollover; completed
bootstrap with later health loss; shutdown during processing; lost restore reply;
cleanup failure. Preserve original received bytes and partial effects.

Independent review, focused codec/readiness/lifecycle regressions, changed Ruff,
diff, report and retained failure/source hashes precede publication. Network,
delivery, live convergence and fusion remain false after offline success.
Next authorized live study requires a separately frozen study and explicit gate;
it is not started automatically by successful tests or a new CLI mode.
