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

## Still required by this same plan

- Bind the continuation through OwnedBootstrap/OwnedWire/ObservedWire, retaining
  the same decoder/receive owner and unchanged legacy behavior.
- Add explicit bounded maintenance transport/cancellation and segmented retention;
  the current core keeps bounded in-memory evidence and is not the journal design.
- Implement the nonblocking stream-interval exchange and restoration-only failure
  path, then actual capture registration and injected end-to-end runner tests.
- Independent whole-change review, final regression/evidence and PR publication.

Neither this implementation nor a boolean in its progress grants network,
delivery, live convergence or fusion qualification. Full fruit-fly learning,
division, fair comparison and swarm/hardware/flight evidence remain incomplete.
