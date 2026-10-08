# Capture wire lifecycle — work in progress

The full lifecycle plan is **not complete**. The actual capture reader, CLI,
socket, process and physics registration remain unchanged. No actual network,
PX4/Gazebo/OpenVINS, ODOMETRY, EKF2, arming or training run was started.

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

### Remaining integration gap — do not enable a physical study yet

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
