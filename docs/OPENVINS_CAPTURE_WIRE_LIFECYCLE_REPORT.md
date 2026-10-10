# Capture wire lifecycle — work in progress

Tasks1-3 are implemented, including opt-in reader selection and the production
runner with injected-service verification. Task4 independent review found five
Important issues, now repaired with counterexample and regression evidence. The sections
below preserve historical checkpoints; later sections supersede earlier pending
implementation statements. No actual network, PX4/Gazebo/OpenVINS, ODOMETRY, EKF2,
arming or training run was started for this lifecycle implementation.

## Implemented core: cold-to-maintenance listener continuation

`ColdTimesyncBootstrap.take_continuation()` transfers the existing serial
observer/filter once, only after successful finite bootstrap completion and
within its original8s deadline. The new internal consumer preserves the filter,
request identities, accepted sample count and clock high-water marks. It requires
one exact boundary snapshot from the next listener before reserving any new reply.
Raw local listener ordinals are retained; their explicit normalized mapping is
separate and is not a uORB generation number. The boundary is not a new sample.

Following statuses must match one pending reply. Wrong/replayed/unsolicited or
missing status, altered epoch/listener, clock reversal, journal error and repeated
transfer refuse subsequent work. Maintenance retains2s progress/freshness checks
and a supplied absolute total deadline bounded by300s from the original start.
The finite4096-record subscription cannot roll over. Cancellation retains partial
bytes and outstanding reservations; it records an intent, **not a stopped daemon
or clean finite subscription exit**. Explicit check() calls remain required on
silence; these classes do not provide a background watchdog.

26 new tests and400 related cold/observer/parser regressions pass (426 total).
74 existing real-codec wire/observed-session/fanout WSL tests pass. Changed Ruff
and diff-check pass. No new full-repository pass is claimed. Tests use actual
parser/filter code with synthetic raw bytes/times, not measured live timing.

Initial17 failures asserted the missing transfer API, not an existing behavioral
bug. A later25-case run exposed3 actual new-implementation cancellation failures:
pending state disappeared from subsequent evidence, preexisting failure was
misreported as a journal error, and a cancel write error left failure unset.
All3 observed REDs were fixed. An additional4096-record boundary test exposed a
consumed reservation incorrectly reported pending at exhaustion; its RED is also
fixed. The final finite-record case preserves4595 modeled accepted samples and
fails closed at the boundary without claiming an unmatched final status.

Logs and initial failures: `results/capture-wire-lifecycle-dev-1701`. No stage
archive or final independent implementation review yet: Task1 is still running.

## Implemented transport prerequisite

ReadOnlyListener now accepts the exact internal continuation for a4096-record
maintenance subscription. Its start and absolute deadline must equal that
continuation's values; legacy callers retain the original8s window. One listener
may claim the context, even if its later connection fails. A second claim faults
the context and the original listener refuses further work. A cancelled/failed
continuation also refuses subsequent reads. This supplies a dependency for the
owned/observed wire composition; it does not install that composition in capture.

Explicit maintenance cancellation retains partial-frame bytes, primary/journal/
close errors and whether the supplied backend's socket close returned. It never
claims daemon exit or clean completion of the finite subscription. Interruption
still runs close and then re-raises. Normal repeat cancellation is idempotent.
The raw-core cancellation and socket cancellation remain separate evidence.

16 new transport cases and96 related transport/core/owned-bootstrap cases passed
(112 total). The first12 failures asserted the absent constructor interface.
Two additional behavioral REDs exposed double attachment before the first record
and reads after context cancellation; both are fixed. Two further interruption/
terminal-journal cases passed as added coverage, not RED fixes. No live socket or
daemon was used; backend, ownership and time are injected. These are intermediate
results, not completion of the whole lifecycle plan.

Final combined focused verification of this partial implementation: **512 passed**,
with selected source hashes identical before/after (`final-v1/before.json` and
`after.json`); installed-codec WSL regression **74 OK**. Changed Ruff/diff pass.
These counts supersede the intermediate subset counts for current source state.

## Still required by this same plan

- Implement the nonblocking stream-interval exchange and restoration-only failure
  path, then actual capture registration and injected end-to-end runner tests.
- Independent whole-change review, final regression/evidence and PR publication.

Neither this implementation nor a boolean in its progress grants network,
delivery, live convergence or fusion qualification. Full fruit-fly learning,
division, fair comparison and swarm/hardware/flight evidence remain incomplete.

## Composed continuation through the observed receiver

The existing OwnedBootstrap, OwnedWireBootstrap and ObservedWireSession now have
an explicit one-time `begin_maintenance(deadline_ns)` transition. It requires the
successful finite500-sample bootstrap and must finish within the original8s,
including journal/owner/descriptor/clock callbacks. It retains the observer,
codec sequence, last request identity, independent simulation-clock lane and
supplied datagram receiver. No new datagram socket or reader is constructed.
The fourth read-only daemon command is a single4096-record maintenance listener;
its first raw snapshot is the previous boundary, not sample501. Ordinary reply
reservation and correlated listener polling then use the transferred context.

Bootstrap completion is historical (`bootstrap_completed`); maintenance health
is distinct and is false before the first new accepted pair, during a pending
reply, after cancellation or refusal. The supplied absolute deadline remains
bounded by original start+300s. All2s source/progress checks and legacy terminal
defaults remain. Heartbeat dispatch is possible while a maintenance status is
pending; a new TIMESYNC request still cannot replace that outstanding reservation.

Owned cancellation closes only its supplied daemon connection, retains pending
and partial bytes, and leaves the caller-owned datagram socket to its lifecycle
owner. The outer session allows cleanup journals after a failure/close intent
without reopening ordinary receive/send operations. Cleanup journal times are
explicitly last-checked observations, not newly observed cancellation times.
Journal/close/interrupt errors and concurrent-operation primary failures remain
distinct. No daemon-exit proof or clean finite subscription completion is inferred.

New cases:20 owned-layer tests,5 actual-codec wire composition tests and5 observed
composition tests. The main observed case uses one injected receiver for510
datagrams (505 TIMESYNC,5 heartbeat), retains505 accepted modeled samples and
reply sequence244 at request500, and crosses the original8s only after the
successful transition. Missing status, stale source, descriptor change, replay,
late/reentrant transition, partial cancellation and cleanup failures are covered.
These are synthetic clocks/daemon bytes with real parsers and installed codec,
not measured live throughput or PX4 reception/convergence.

Initial missing-interface assertion failures:15 owned,5 wire,5 observed. The first
wire regression also exposed two test-fixture interface errors (`HookedLock`
lacks `locked`) and one overly eager health-call signature change; lock acquisition
and the unchanged default health call were restored, preserving terminal/reentrant
semantics. An added cleanup test initially required a concurrent primary refusal
to also appear as a socket/journal cleanup error. That assertion was corrected to
check the retained primary refusal; it was not a production bug or RED-to-GREEN
fix. The other cleanup additions passed as new coverage.

Current focused verification: **627 pytest passed and130 installed-codec WSL
unittest passed**, with30 selected source/test hashes unchanged before/after.
Changed Ruff and diff-check pass. Raw outputs and hashes are under
`results/capture-wire-lifecycle-dev-1701/composition-final-v1`; initial failures
remain alongside them. No fresh whole-repository pass is claimed. Actual capture
registration remains unchanged; Task1 is still open for segmented retention, and
the plan's interval/restore, runner, final independent review and sealed evidence
tasks remain outstanding. No network/physics/estimator/arming/training run occurred.

## Task1 completed: explicit segmented lifecycle retention

The opt-in `capture-wire-segmented-v1` store is now composed through the same
observed session, owned coordinator, cold/maintenance observer logs, listener
transport, wire decoder and datagram receiver. Ten fixed source channels share
64 segments of8192 events and512MiB of JSONL record bytes. Each row has absolute
and per-source indices, phase and original event fields. Selection count remains
4096. Legacy constructors still use their original lists and limits. The existing
bounded25,000-observation clock table remains protocol state; this change is not
a claim that the whole application has constant memory or bounded external sinks.

Selected implementation: existing Python pathlib/json/hashlib/threading only,
no dependency installation or new simulation algorithm. This continues the fixed
Python3.12/API research recorded by the lifecycle spec and earlier runtime-binding
work. Exclusive creation prevents overwriting a preexisting directory/member.
The writer retains only active buffered output, digest/counters, member references
and at most one in-flight failed row; it does not retain the entire event history
in each layer. Segments are flushed, closed and checked by hash/length before
being marked sealed. Short write, flush/close failure, hash mismatch or quota
exhaustion fails closed; partial files and unpersisted terminal failures remain
explicit. File operations still require the caller's bounded supervision.

Evidence getters return source/member references, plus explicitly unsealed active
metadata; they do not seal a member or read back the whole history. The manifest
is a **member index only**, never a completion grant for its own still-pending
close. Final returned evidence reports complete retention only after every close
has returned without failure. No fsync, atomic durable commit, hostile-ABA defense
or storage-speed qualification is claimed.512MiB covers serialized record members;
small indexes/failure diagnostics are separate metadata, not additional hidden
record segments. Failed capture remains failed even if its retained prefix is valid.

The receiver holds an explicit pending return draft until its clock observation
and publication. This preserves actual received bytes with unknown timestamp on
clock failure, and preserves an unpersisted draft if storage refuses after the
read. It never silently freezes an earlier `received_ns=None` copy as the later
successful return record. Cleanup journals stay distinct from normal operations.

Integration evidence uses real installed codecs/components with injected I/O:
1100 TIMESYNC and600 heartbeat datagrams, same receive owner and1100 accepted
modeled samples, more than8192 wire events with every persisted index/hash checked.
A separate4096-datagram case rejects the4097th before reading it; no cap was raised.
Shared storage failure prevents the next read and still closes the owned listener.
Actual capture registration remains unchanged, and no network/physics/estimator
run was executed. Offline completion does not authorize such a run.

Initial failures are retained:10 missing-storage assertions,3 missing-retention
binding assertions; the first composition found two repeat-cleanup errors caused
by reapplying phase changes to a store already closed during refusal. Both passed
after the idempotent cleanup correction. Two additional behavioral REDs exposed
close reentry and a manifest prematurely claiming success before its own close;
both are fixed. Four received-byte/timing cases passed as added coverage, not
RED-to-GREEN fixes.

Full prospective quotas were exercised with real temporary synthetic files:
524,288 records/64 members/59,022,324 bytes, then the next record rejected;
511 approximately1MiB records/535,881,392 bytes, then the next record rejected by
the536,870,912-byte cap. All member hashes and every record/source index were
verified. Temporary bulk fixture data was removed by the test harness; generator,
hashes, metadata and results are retained in `full-capacity-v1` and `v2`. These
are storage tests, not sensor captures or measured runtime performance.

Final current-source verification (`retention-final-v1`): **643 pytest passed,
133 installed-codec WSL unittest passed**, full-capacity-v2 passed,35 selected
source/test hashes unchanged. Changed Ruff/diff-check pass; no new full-repository
pass is claimed. Task1 of the lifecycle plan is complete. Task2 interval/restore,
Task3 actual runner registration and Task4 independent whole-change review/sealed
stage evidence remain open. The full FlyDrones goal and fusion qualification
remain incomplete; hardware and flight evidence are unchanged.

## Task2 checkpoint: pinned commands and nonblocking phase core

The latest implementation adds `PinnedCodec.encode_interval_command` and
`interval_response`, plus `IntervalExchange` in the existing interval module.
The existing synchronous transaction remains unchanged as a comparison oracle.
**Task2 is still incomplete:** the actual Observed/Owned receive owner has not
yet bound this exchange to its shared sender sequence, heartbeat dispatch and
restricted cleanup transport. No actual capture reader or network mode changed.

### Source decision and boundaries

Reuse PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4 (BSD-3-Clause) and installed
pymavlink2.4.49 with the existing LGPL/generated-code provenance. The archived
maintenance observations are reused: neither repository was archived; last pushes
were2026-10-07T16:06:37Z and2026-10-06T23:56:46Z respectively. These are prior
observations, not newly verified activity or installed-whole-checkout equivalence.
No package installation or estimator/algorithm/paper choice changed.

The fixed [PX4 receiver](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/mavlink/mavlink_receiver.cpp)
sends MESSAGE_INTERVAL directly for GET510, while publishing the command ACK
separately. The fixed [sender](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/mavlink/mavlink_main.cpp)
drains ACKs with transmit-buffer and known-target conditions, copying original
sender identity to ACK target fields. The implementation therefore requires both
GET ACK and interval response, accepting either order. SET511 ACK alone never
qualifies readback. Real installed codec schema and both source hashes are retained
in `results/capture-wire-lifecycle-dev-1701/interval-codec-inspection.json`.

The [MAVLink command protocol](https://mavlink.io/en/services/command.html) distinguishes
acceptance from completed effects and normally uses retries. This narrowly scoped
profile deliberately refuses ambiguous retries. It uses sender254/191,target9/1,
confirmation0, TIMESYNC111, positive exactly-restorable intervals and zero unused
parameters. ACK target/source and result shape are checked; MAVLink1 and missing
target extensions are refused for this profile. MESSAGE_INTERVAL contains no
transaction nonce: one pending command and local arrival-time checks cannot prove
perfect attribution of a delayed response across repeated same-command operations.
Header equality is not authentication. Both limitations remain explicit.

Adopting the existing codec avoids a second blocking `recv_match` reader and
requires no new dependency. The phase core keeps one pending operation, at most
six normal command effects and96 events; it does not consume sensor streams.
Real CPU/memory/transport latency is not measured here. Adaptation cost remains
the actual owner binding and runner integration, not just these helpers.

### Behavior and verification

`poll` advances at most one effect without receiving or running the bootstrap
body. `feed` accepts normalized decoded command replies; the body completes
explicitly. Each operation has2s, normal startup8s, and primary failure can enter
one immutable10s restoration-only window. Writes are owned before calling the
sender, including ambiguous exceptions. Independent restore/final readbacks retain
primary versus restoration failures. Every active entry checks the supplied
identity/safety guard; terminal refusal preserves pending state and one bounded
terminal failure. The outer owner must still implement that guard, keep heartbeats
flowing, interrupt blocked callbacks, and suppress ordinary traffic during cleanup.
This helper alone does not provide any of those actual-runtime guarantees.

Initial6 codec/12 exchange missing-interface assertions were RED. Additional
behavioral REDs exposed missing identity checks while awaiting final readback,
unsolicited post-completion ACK preserving success, unbounded duplicate terminal
failure accumulation, and missing pending evidence on hard refusal. All were
fixed and retained; the pending-evidence test first raised KeyError before it was
rewritten as an explicit failing assertion. Added passing boundary coverage is
not mislabeled as RED-to-GREEN work.

Final `interval-final-v1` verification: **71 pytest and123 installed-codec WSL
unittest passed**,20 selected source/test hashes unchanged before/after, changed
Ruff/diff-check passed. The injected mixed-frame codec loop tests both ACK/interval
orders with interleaved heartbeats and sequential outgoing command IDs. It is not
the actual capture receive loop, online heartbeat availability or performance.
No fresh whole-repository result or independent whole-plan review is claimed.
Network/live/fusion flags remain false. All historical failures are preserved.

## Task2 checkpoint: actual receive composition, normal transaction

`ObservedWireSession`, `OwnedWireBootstrap` and `TimesyncWireResponder` now have
an opt-in `interval_transaction=True` composition. The default remains the old
bootstrap-only behavior. The actual capture CLI/runner still does not select
this new mode. **Task2 remains incomplete for fault-time restricted restoration.**

The normal path uses the existing one DatagramReceiver, one pinned codec and
one outgoing sequence for all commands and TIMESYNC replies. Command polling
never recursively receives; command replies are dispatched from the same decoded
datagram as heartbeat traffic. Commands use the same supplied socket and final
descriptor/owner/source checks, without inventing an inbound packet to send GET.
Only independently read-back candidate configuration enables synchronization
replies. Earlier requests are retained without replying/counting and preserve
their request high-water mark. One pending reply still forbids a second reply.

The500-sample listener completion is recorded separately from overall bootstrap
readiness. Baseline SET, restore readback and final readback must finish inside
the original8s before readiness or maintenance. A regular interval poll during
maintenance is a health-checked no-op, not a second transaction. Heartbeats remain
processable while waiting for the first/stream status, while the existing reply
reservation prevents another TIMESYNC from bypassing that wait.

Command send intent/actual returned count/return time and phase evidence stay in
the wire journal, including short sends or timeouts after a side effect. An
attempted command consumes its shared sequence even when a later check fails.
The phase core exposes scalar progress so repeated safety checks need not copy
its historical events. This is a structural change, not a measured real-time
or simulation-capacity result.

Eight initial composition assertions failed for missing constructor integration.
Two actual integration failures then exposed a heartbeat blocked by the old
listener-phase gate and a normal maintenance poll rejected as a new command.
Both are fixed; the logs retain their actual raised exceptions. Four additional
fault/boundary cases were added as GREEN coverage, not claimed as RED fixes.
The scalar-progress test was initially scheduled as RED but finished after the
implementation and therefore passed; that GREEN output is retained. An explicit
later backout test verified it fails with only the getter absent, and restored
the exact source bytes. It is not described as an initial observed RED.

Final `observed-interval-final-v1`: **72 pytest and153 installed-codec WSL tests
passed**,24 selected production/test hashes unchanged before/after; changed Ruff
and diff-check pass. The normal combined case makes507 actual injected-socket
writes/reads: six interval commands,500 bootstrap replies and one maintenance
reply, with contiguous modulo256 sequence and six heartbeat deliveries. It
retains the same receiver/codec objects, checks restore-before-maintenance,
and leaves the caller-owned socket open. Other cases cover wrong ACK target,
armed mixed datagram, descriptor/owner changes, missing response waiting,
final mismatch, short/late send, and unchanged legacy command prohibition.
No actual UDP, simulator, estimator, training, EKF2 or arming occurred.

### Previous checkpoint gap (resolved below for composition, not capture runner)

The existing fail-closed normal wrappers close listeners and refuse all further
I/O on failure; the observed wrapper also closes retention. The phase helper's
10s cleanup semantics therefore do **not** yet imply owner-bound restoration
after a source failure or expired8s startup. The wire guard intentionally grants
no exception to a failed wire. Do not clear failure flags, reset clocks, reopen
a second receiver, extend8s, or claim all cleanup tests pass.

Next implement an explicit restoration-only lifetime on the same owned
descriptor/codec, deriving its immutable deadline from the first STOPPING event.
Keep source/primary failure latched and ordinary TIMESYNC/fanout/force disabled;
retain incoming safety frames and abort on armed or changed identity. Preserve
2s operation limits and all partial effects before closing receiver/retention,
then owned PX4. Test source loss, expiry, identity/descriptor changes, stale/armed
heartbeat, interruption and journal failure through this actual composition.
Only afterward can Task2 finish and Task3 bind the real capture lifecycle with
injected factories. Task4 review/archive and the larger FlyDrones goal stay open.

## Task2: restricted restoration on the original receive owner

The opt-in observed composition now retains a separate restoration window from
the first observed failure/STOPPING. Its absolute10s deadline cannot be renewed
by a later cleanup call; an earlier exchange cleanup deadline takes precedence.
The normal8s startup deadline, primary/source failure, receiver/codec identity,
sequence and clock high-water marks remain intact. Only the exact bound exchange
can send its owned baseline SET and independent GET/readbacks. Each operation
retains its2s limit and there is no ambiguous write retry.

Cleanup still checks the original process identity, descriptor, fixed peer and
clock/session. A fresh unarmed PX4 heartbeat is required at the final send
boundary. Safety heartbeats are recorded but not delivered to the normal fanout;
TIMESYNC is retained and ignored, never replied to during cleanup. The failed
source is not reopened. An armed frame, changed identity, interruption, deadline,
clock regression or journal failure latches restoration refusal. Repeated refused
entry/poll calls cannot grow terminal evidence or create another attempt.

The same receiver counts all actual recvmsg returns across normal and cleanup
traffic and refuses before a4097th datagram return attempt. Shared segmented
retention remains open while restricted restoration is possible, then seals on
close. The supplied socket remains caller-owned. No claim about actual capture
thread join, socket teardown or PX4 stop ordering is made until Task3 integrates
those owners. A restore result proves only its modeled interval ACK/readbacks;
it never clears the primary failure or grants bootstrap, fusion or arming.

The new24 composition tests cover source loss, expired startup, late/repeated
cleanup entry, owner/descriptor/session changes, clock reversal, stale/armed
heartbeats, ignored TIMESYNC, interruption, journal error, reentrant close,
unknown/already-candidate baseline, ambiguous apply/restore effects, missing ACK,
wrong peer raw retention, shared4096 bound and segmented close. Body failure,
lost apply ACK and short restoration send outcomes are compared with the existing
synchronous oracle; that oracle is never called by the receive owner.

The initial10 missing-entry assertions were RED before restoration implementation.
This continuation additionally observed and fixed three assertion failures:
phase bookkeeping failure skipped listener closure; frequent progress traversed
interval history; repeated refused cleanup grew terminal errors. Logs preserve
each RED and GREEN. Other added cases were GREEN coverage, not claimed as fixes.
Closure now independently attempts phase bookkeeping, listener close and store
close, records all errors and propagates interruptions. Scalar progress avoids
history copies; no measured runtime performance improvement is claimed.

Final `restoration-final-v2` passed128 pytest and177 installed-codec WSL tests,
with selected source hashes unchanged before/after, changed Ruff and diff-check
passing. The first complete run passed the same tests but failed three Ruff B023
checks in the new oracle fixture; binding the scenario explicitly fixed them.
Both runs remain preserved. These are focused affected regressions, not a new
whole-repository result. No actual network, physics, estimator or training ran.

Task2 composition implementation/verification is complete. Task3 actual capture
registration, injected-runner tests, cleanup ordering and Task4 independent
whole-change review/evidence archive are still uncompleted. Do not enable a
physical study from this checkpoint. The broader learning/swarm/comparison goal
and all historical physical failures remain unchanged.

## Task3 checkpoint: actual capture heartbeat effects and interruption cleanup

Task3 is still open. The existing capture reader now invokes the extracted
`dispatch_capture_heartbeat` hook, which preserves the supplied arrival timestamp
for both arming freshness and journal/fanout dispatch. Runtime mapping is observed
once before marking its ready state. Mapping or dispatch failure leaves arming
freshness unset and propagates to the existing capture error path. Armed input
clears freshness and remains refused. This hook is exercised with the real pinned
codec, CaptureWriter, journaled fanout and ShadowInput, with injected network and
native transport. It is not the full new capture reader.

The actual CaptureJournal previously swallowed a body interruption and stopped
remaining cleanups on a callback interruption. It now attempts every registered
cleanup in priority order, retains primary/secondary failures, attempts the
exclusive terminal result, and re-raises the original/first interruption. A
failure while formatting an exception cannot skip the next owner. Terminal file
failure is propagated, marks the in-memory result failed and never overwrites an
existing result file. Ordinary exception-to-capture_failed handling is retained.
This follows Python's [context-manager semantics](https://docs.python.org/3.12/reference/datamodel.html#object.__exit__)
and [interruption hierarchy](https://docs.python.org/3.12/library/exceptions.html#KeyboardInterrupt).
Synchronous callbacks are not preempted by this journal; outer supervision is
still required. This change does not prove real process exits or cleanup latency.

Twelve new hook/journal tests passed: eight existing cleanup counterexamples,
three initially missing hook assertions, and one additional terminal-write status
counterexample. The first RED run was interrupted by a mismatched SystemExit
expectation; the corrected test catches either interruption and asserts object
identity. All failures remain. Three additional actual-codec/fanout cases passed;
their first run had one incorrect assertion about which component records queue
overflow. The existing writer raises synchronously; fanout latches it. The test
was corrected to check the actual failing boundary, with no writer change.

Final `capture-hooks-final-v1`: **271 pytest and70 WSL tests passed**,25 selected
source/test hashes unchanged, changed Ruff/diff-check passed. The scope includes
capture contract, journal, runtime binding, reference refusal, physics-trace
cleanup and source/fanout regressions; it is not a new whole-repository result.
No capture main, real socket/PX4/Gazebo/OpenVINS or training was executed.

The sole-reader selection and driver, one PostUpdate clock registration, startup
gate, maintenance exchanges and actual restoration-before-PX4-stop registration
are still pending. Existing live capture continues selecting the legacy reader.
Task3's complete injected-runner test and Task4 final independent review/archive
are not replaced by these hook tests. Details and source selection are retained
in `results/capture-wire-lifecycle-dev-1701/capture-hooks-research.md`.

## Task3 checkpoint: serial capture driver and managed reader shutdown

`capture_wire_lifecycle.CaptureWireDriver` now advances the supplied actual
ObservedWireSession, owned listener, pinned codec and interval exchange. Each
tick polls at most one datagram and one command effect. It waits for an independent
PostUpdate observation before command traffic, transfers to maintenance only
after the original500/bootstrap/restoration gates, and keeps the original total
deadline. Failure enters STOPPING; subsequent restoration retains the primary
failure and uses the same receiver and bounded cleanup allowance. No deadline is
renewed by repeated stop requests.

`bind_capture_wire`, exported from the capture module, registers one PostUpdate
wrapper and priority15 cleanup (before owned PX4 priority20). The wrapper records
only the independent clock and calls the existing supplied post callback. Either
callback failure stops the driver; new callbacks after STOPPING are refused.
The managed reader restores through its sole polling owner, then cleanup joins
that reader before closing the socket. A join timeout records failure and leaves
the still-live reader's descriptor owned. Blocking user callbacks still require
outer process supervision; a Python join cannot preempt them. Failed thread start
and repeated cleanup are covered. No new dependency or upstream algorithm changed;
the existing fixed-source lifecycle/interval research remains the basis.

Sixteen new cases exercise the real composed protocol classes with injected I/O:
500 startup samples, baseline restoration, two maintenance correlations, missing
status, source loss/restoration, original10s cleanup expiry, callback/registration/
declaration failure, independent clock ordering, managed thread join/timeout,
failed start, stopped callbacks, secondary close errors and concurrent-tick
refusal. The normal managed-thread case uses an actual Python thread with an
injected socket/backend; the blocked-thread case is synthetic. It is not evidence
of a real blocked PX4 process exiting.

The initial five missing-entry assertions failed then passed. Follow-on checks
found callback failure not latching STOPPING, invalid binding leaking its socket,
stop-clock failure interrupting cleanup, command traffic before the first clock
observation, failed-start cleanup, post callbacks after STOPPING and concurrent
tick refusal leaving ordinary work enabled. Their RED/GREEN records are retained.
The first cold-clock test lacked the required heartbeat sink and failed during
construction; the corrected case then observed the premature command assertion.
The socket-close secondary-error case passed on addition and is coverage, not a
claimed bug fix. Two initial import-order lint findings were corrected.

`capture-driver-final-v1` passed **271 pytest and114 WSL tests**, with selected
source/test hashes unchanged before/after and changed Ruff/diff-check passing.
This is focused affected regression evidence, not a new full-repository result.
No actual socket, PX4/Gazebo/OpenVINS, capture main or training ran; fusion and
network authorization remain false.

Task3 remains incomplete: actual main still selects the legacy reader. The new
registration/driver is not yet selected by a declared capture profile. Exclusive
mode selection, actual process/descriptor construction, pre-step health wiring,
startup/maintenance gate integration and the full injected-main test must still
be completed. In particular the driver's `progress.ready` is a protocol snapshot,
not by itself a concurrent pre-step freshness proof. These component tests do not
replace that integration. Task4 independent whole-change review and final stage
archive also remain pending. No live study is enabled from this checkpoint.

## Task3 checkpoint: declared main selection and selected-owner composition

The main now has an opt-in `--wire-config` path. Without it the legacy receiver
remains selected. The new mode requires an execution declaration, runtime binding
and the complete estimator-aware fanout profile. Its small JSON document declares
`capture-wire-v1`, a session ID, simulation origin0 and an explicit remote origin;
the execution contract records its path/resolved identity, bytes, SHA256 and
configuration. Worker forwarding and runtime required-input selection include it.
The selected file is rechecked against the declaration immediately before receiver
construction; it cannot silently change between initial validation and selection.
This is ordinary drift detection, not an atomic or hostile-ABA guarantee.

The actual `prepare_capture_receiver` call selects either the legacy mavutil
receiver or `CaptureWireOwner`. The latter creates one nonblocking datagram socket,
records its descriptor identity/namespace, creates bounded segmented retention
and an independent clock journal, and subsequently binds the owned PX4 process.
The installed fixed daemon path remains `/tmp/px4-sock-8`. Endpoint agreement
still does not authenticate the UDP sender's PID. The prior fixed Python/socket/
proc, pinned PX4 and codec research is reused; no new dependency or calibration
was introduced and no fresh upstream maintenance observation is claimed.

In the new main branch, PostUpdate registration/finalization follows owned-process
binding; the legacy branch retains its earlier ordering. Only the selected
receiver thread starts. The motion readiness wrapper checks wire health in
addition to the existing sensor/native proof, so startup can continue with zero
force while the wire gate is pending. The independent pre-step check detects a
stale reader/source/status even before another receive tick. A currently pending
correlation can retain earlier established health within the original2s window;
it is not automatically an expired source. The original8s bootstrap and original
capture-start300s total bounds remain distinct. This gate is point-in-time and
does not retroactively cancel a step already executing.

The main registers owned-PX4 cleanup before runtime-map registration. Wire owner
cleanup remains priority15, preceding PX4 priority20; it restores through and joins
the sole reader before closing its socket and journals. The ordering is implemented
in main, but the complete main constructor/failure path is not yet exercised with
all factories injected. Normal physical startup or shutdown is not claimed.

New tests cover declaration/forwarding/drift, exclusive factory selection,
pre-step expiry, a pending pair, stopped handoff and selected resource ownership.
The composed case uses the actual main selector, owner, clock wrapper, driver,
codec, interval exchange, CaptureWriter, estimator-aware heartbeat fanout and
ShadowInput. It drives500 startup samples, restores the baseline, checks two
maintenance pairs and reconciles a post-bootstrap heartbeat. Its injected socket
and process backend never call actual network/PX4. Writer draining is deterministic
through the real write method; this is not asynchronous latency evidence. Native
estimator calls are forbidden and asserted absent; no sensor/VIO readiness is
fabricated from transport success.

Observed behavior REDs exposed a STOPPING-to-MAINTENANCE race, a missing owner/socket
network-namespace comparison and configuration drift being accepted before
resource creation. They now pass after correction. Other initial failures were
missing APIs. The first owner composition attempt reused a consumed test backend
and a test-only daemon-path assertion; a fresh backend plus an explicit assertion
of the real fixed path corrected that fixture. Both outputs are preserved, with
no claim of a physical failure or production fix for that setup mistake.

Final `capture-entry-final-v2`: **309 pytest and121 WSL tests passed**,37 selected
source/test hashes stable, changed Ruff/diff-check passed. Version1 passed308/121;
the subsequent observed configuration-drift failure justified version2. All logs
remain in `results/capture-wire-lifecycle-dev-1701`. No full-repository pass,
actual main execution, socket/PX4/Gazebo/OpenVINS or training result is claimed.

Task3 is still open for complete injected-main/runner validation, including actual
registered cleanup order, constructor and shutdown failures, and factory-escape
guards. Those requirements are not replaced by the selector/owner composition
test. Task4 independent whole-change review and stage sealing remain pending.
Do not run a live study merely because the new CLI selection now exists. Fusion,
network authority, swarm qualification and the historical failed gates are unchanged.

## Task3: production runner integration

The existing main lifecycle tail is now `run_capture_runtime`, called by main
with its prepared fixture, writer, native shadow, receiver owner, runtime binding
and original capture clock. It preserves the existing 10-step motion batches,
25s simulation target, original-start300s wall budget and cleanup priorities.
Only process/thread construction and the wall-budget clock have explicit injection
seams; production defaults retain the former services. This extraction does not
claim execution of CLI validation, archive extraction or native/sensor construction.

The new composed test executes that production runner and real CaptureJournal,
selected CaptureWireOwner, codec, interval exchange, independent clock, segmented
journals, CaptureWriter, heartbeat fanout and ShadowInput. A real Python receiver
thread owns each protocol tick. A deterministic test scheduler grants ticks and
an injected peer answers actual encoded commands; it does not replace protocol
state transitions. The injected fixture delivers25,000 sequential1ms callbacks,
500 bootstrap samples, restoration and746 maintenance reply/status pairs. The
test forbids real UDP/PX4 constructors and Gazebo/native constructor imports.
Transport success does not manufacture sensor readiness or call the estimator.
Writer draining and the synthetic wall clock are not online latency evidence.

Seven additional composed cases retain registration failure, source loss after
interval mutation, descriptor and process identity replacement, missing/replayed
maintenance status and a lost restoration reply. Source failure restores the
baseline through the same managed reader before owned-process stop. Changed
identity refuses restoration; a lost reply remains unverified even after the
synthetic peer applies the SET. All cases preserve failure and close/join evidence.
Six orchestration cases also exercise the ordinary25s runner loop, original wall
deadline, constructor/finalize/runtime-map failure and cleanup failure followed by
owned-process cleanup. The blocked-reader mechanics remain covered by the real
driver tests; the orchestration cleanup-error case uses an injected callback and
does not claim a real blocked OS thread.

The initial five tests failed because the runner injection entry was absent.
The first composed attempt exposed test-fixture defects: equal synthetic receive
times and temporary-directory removal before registered cleanup. That failed log
is retained. Distinct per-receive times and correct test-resource lifetime fixed
the fixture; no physical or production repair is claimed for those errors.
Subsequent fault cases were added passing against the existing refusal logic,
not described as observed production REDs.

Final focused verification `capture-runner-final-v1` passed315 pytest and129 WSL
tests, with39 selected source/test hashes unchanged and changed Ruff/diff-check
passing. Eight composed runs retain raw clock, segmented protocol, fanout and
terminal records beneath that directory. This is current affected regression
evidence, not a full-repository test result. No actual UDP, PX4, Gazebo, estimator,
training or fusion ran. Task3 implementation is complete; Task4 independent
whole-plan review and final sealing/publication remain pending. Live activation
still requires the separate prospective study gate.

## Task4: independent review repair and final regression

The independent whole-plan review covered `2c4f044..bd28908`. A fresh reviewer
could not be spawned because of the agent-thread limit, so the completed
independent design-review seat was reused. This was not fresh-context review.
It found no Critical issues, five Important issues and one Minor report issue.
All were accepted after local reproduction and source inspection:

- A correlated but rejected maintenance sample could grant pre-step readiness.
  The gate now requires the latest observer acceptance, including pending pairs.
- Armed-heartbeat refusal retained an earlier unarmed restoration permission.
  It now revokes that permission and latches a restoration safety refusal.
- Interval mode delivered heartbeat before checking a malformed mixed request.
  Request identity/multiplicity/clock/encoding, heartbeat and the whole decoded
  response batch are preflighted before heartbeat/ACK effects. The response preview
  reuses bounded feed state and never sends; actual feed still checks time.
- Terminal segmented flush failures could remain only in component state while
  CaptureJournal reported success. Driver/owner now propagate final component
  and retention failures into capture errors before terminal result selection.
- A byte-quota rejection could lose an executed send's return record. The single
  in-flight failure slot now captures that record before rejecting its byte size;
  quota and persistence qualification are unchanged.

The stale opening status was corrected and earlier text explicitly marked as
historical checkpoints. The original five-test counterexample run had six failing
assertions; an additional duplicate-ACK batch also failed. These RED logs remain.
The first focused repair run passed six tests. Clock-mapping refusal and analogous
heartbeat/listener return-slot coverage were subsequently added GREEN.

Expanded verification v1 retained three WSL import errors because pytest-only
modules were assigned to the unittest environment. An old owner fixture also
reused errors from its deliberately closed preparatory cold session. Tests now
use the installed Windows pytest for those modules and a separate capture result
for the subsequently constructed owner; preparatory failure is retained separately.
This is a fixture/environment correction, not permission to clear a live failure.

Final `capture-review-final-v2`: **413 pytest and198 WSL tests passed**, with53
selected source/test hashes unchanged before/after, changed Ruff and diff-check
passing. This is expanded affected regression, not a new full-repository result.
Nine composed runner cases retain their logs. The added terminal-flush case
reaches25,000 callbacks but correctly remains `capture_failed`. Offline auditing
verified all retained member bytes/hashes and global/per-source record indices;
the intentionally unsealed flush-failure member remains failed even when its
stored bytes match the declared digest. Normal output has500 bootstrap and746
maintenance pairs. The earlier745 report count was an inclusive-endpoint arithmetic
mistake, corrected from raw records without re-running the estimator or physics.

Review exclusions remain unverified: full CLI preparation, actual OS descriptor
and process provenance, ACK timing/rate, PX4 convergence, concurrent live sensors
and native estimation, physics, hardware and flight. The independent review did
not re-review the repair commit; its findings were closed with retained local
counterexamples and current regressions in the prescribed single repair pass.
No actual network, physical capture, ODOMETRY/EKF2, arming or training is authorized
by this result. The stage archive is recorded below; no live study is activated.

## Stage archive

`evidence/capture-wire-lifecycle-dev-1701.zip` contains1209 members (25436935 bytes). SHA256:
`d988bf1bbba27cd2d827b9663cc6e525f5bfc4a549cabb0b3f4485007e588807`. Every member hash and ZIP CRC verified.
The manifest names producer `e4312edd366ad10c8c05a0807e099e629fd99c4c`; the report copy
inside the archive precedes this self-referential archive-hash paragraph. Raw
normal/failed runs, RED/GREEN outputs, expanded regression failure/retry, research,
selected tested-source snapshots and the whole-plan review package remain preserved.
This completes the offline implementation scope; it does not complete the FlyDrones
goal or establish actual capture/PX4/network/fusion qualification.

Publication status: code through `e4312ed` reached draftPR65. Archive commit
`deb78be` is local: repeated HTTPS pushes returned HTTP408 (one retry also failed
TLS handshake), and remote-head checks confirmed no archive publication. A small
code-only fast-forward succeeded. Task4 final publication therefore remains open;
no evidence was deleted or certificate verification disabled.
