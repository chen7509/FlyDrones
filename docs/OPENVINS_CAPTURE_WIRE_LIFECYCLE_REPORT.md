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

- Add segmented retention to the composed lifecycle; the current layers retain
  their bounded in-memory evidence and are not the segmented journal design.
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
