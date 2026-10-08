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

- Bind the continuation through OwnedBootstrap/OwnedWire/ObservedWire, retaining
  the same decoder/receive owner and unchanged legacy behavior.
- Integrate the explicit maintenance transport/cancellation with the owned runner
  and add segmented retention; the current core keeps bounded in-memory evidence
  and is not the journal design.
- Implement the nonblocking stream-interval exchange and restoration-only failure
  path, then actual capture registration and injected end-to-end runner tests.
- Independent whole-change review, final regression/evidence and PR publication.

Neither this implementation nor a boolean in its progress grants network,
delivery, live convergence or fusion qualification. Full fruit-fly learning,
division, fair comparison and swarm/hardware/flight evidence remain incomplete.
