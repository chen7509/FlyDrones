# Capture wire lifecycle implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, with TDD and
> one final independent review. Existing user preapproval applies; keep this
> worktree and all historical evidence.

**Goal:** Bind the actual capture runner to a single reader across startup,
maintenance and cleanup, verified in process without executing network/physics.
**Architecture:** Refactor the existing observed wire composition; retain its
codec/identity/clock state. The existing CaptureJournal owns lifecycle cleanup.
**Tech Stack:** existing Python3.12/pymavlink2.4.49, WSL unittest, pytest/Ruff.
**Spec:** `../specs/2026-10-08-capture-wire-lifecycle-design.md`.

## Constraints and file responsibilities

- `capture_disarmed_sensors.py`: select mode and register existing runtime objects
  once; no second reader or hidden real-network default.
- `openvins_observed_wire_session.py`, `openvins_wire_bootstrap.py`,
  `openvins_owned_bootstrap.py`, `openvins_timesync_wire.py`,
  `openvins_datagram_receive.py`: separate transport lifetime from bootstrap
  completion without altering existing bootstrap-only defaults.
- `openvins_timesync_interval.py`: retain rollback semantics; bind its transport
  to the same decoded command stream, no recursive competing recv_match.
- New `capture_wire_lifecycle.py` only if extraction keeps capture registration
  readable; it must orchestrate existing objects, not duplicate their validators.
- Tests in `tests/benchmark/test_capture_wire_lifecycle.py` plus existing wire,
  interval, clock and heartbeat tests. Evidence under a new results directory.

### Task 1: Preserve one transport across bootstrap and maintenance

**Interfaces:** existing session poll_datagram/poll_listener/progress; add one
explicit transition using the declared total deadline, distinct from bootstrap
deadline. Add a one-time internal take_continuation transfer preserving the serial
observer/filter, last identities, codec sequence, clock and failure state. The
maintenance listener's raw ordinal/epoch is separate from accepted sample count;
one exact boundary snapshot is not a new sample. No repeated rollover.

- [x] Trace current completion/deadline/observer dependencies and record the
  exact transition interfaces in the execution ledger before editing.
- [x] Write failing tests for successful bootstrap then heartbeat/TIMESYNC,
  no transition before500/after8s, no cleared fault, expired maintenance and
  unchanged legacy completion rejection. Use actual codec with fake transport.
- [x] Add missing/duplicate/replayed maintenance status, invalid boundary snapshot,
  partial subscription cancellation and repeated-transfer/rollover RED cases.
- [x] Implement the explicit transition and ongoing status-health checks; make
  the tests pass without weakening bootstrap or two-second limits.
- [x] Add the lifecycle-only segmented journal and tests crossing8192 events,
  verifying all hashes/indexes and refusing64-segment/512MiB exhaustion or failed
  close; leave legacy defaults and total4096 datagram bound unchanged.
- [x] Run related observed/wire/observer/clock regressions and commit.

### Task 2: Single-reader interval transaction

**Interfaces:** TimesyncIntervalTransaction read_interval/set_interval receive
correlated decoded rows from the same receiver, while heartbeats keep flowing.
The synchronous class remains an oracle, not a receive-thread callable. Implement
explicit begin/feed/poll exchange phases; body is bootstrap only, and restoration
must finish before MAINTENANCE. Restricted10s cleanup after primary failure allows
only owned-baseline restoration, retaining failure and2s operation bounds.

- [x] Retain fixed codec/PX4 command and interval field evidence; confirm exact
  query command/ACK target semantics before encoding commands.
- [x] Tests first: baseline, apply/readback, body, restore/readback; no second
  reader; heartbeat during waits; missing/wrong/duplicate/late responses; mutation
  with lost ACK; all partial effects and restoration failures retained.
- [x] Implement bounded nonblocking progression in the existing receive owner.
  Do not call a blocking receive recursively from the transaction.
- [x] Compare success/failure/restore outcomes to the existing oracle; verify
  failure-before/after mutation, expired primary deadline, changed owner/descriptor,
  repeat interruption and cleanup deadline cannot permit ordinary traffic.
- [x] Targeted interval/codec regression and commit. Offline flags remain false.

### Task 3: Actual capture registration and cleanup integration

**Interfaces:** actual runner supplies one socket/process/fixture/clock/fanout,
with injected factories in tests. Execution declaration binds the new mode.

- [x] Add failing capture-path tests proving exclusive legacy/new selection,
  single PostUpdate registration, real heartbeat fanout delivery, startup gate,
  two correlated maintenance exchanges across the listener boundary, missing/
  replayed maintenance refusal, and restore-before-owned-PX4-stop ordering.
- [x] Implement registration/health hooks with existing CaptureJournal and
  runtime-binding boundaries; no default behavior or simulation-load change.
- [x] Exercise constructor/registration failure, source loss, process/descriptor
  replacement, shutdown, blocked/failed cleanup and refusal after failure.
- [x] Run actual runner with injected factories only; fail tests if socket,
  Gazebo Server, estimator or PX4 factories escape to real implementations.
- [x] Commit, document remaining actual-runtime evidence gaps.

### Task 4: Review and publish the integrated result

- [x] Independent review of whole change; repair Important/Critical with observed
  RED/GREEN; explicitly document any remaining Minor.
- [x] Focused regressions, changed Ruff and diff-check. Broaden only for uncovered
  behavior or failures; do not claim old full-suite results as current.
- [x] Seal normal/failure in-process evidence, selected source hashes and report;
  update status matrix, push personal only, verify/update draftPR65 and attach it.

## Review focus

No two readers; no renewed8s budget; no completion-as-permanent-health; no command
wait starves heartbeat; no restoration after socket/PX4 teardown; no synthetic
time claimed as online performance. Any missing interface above remains unchecked,
not replaced with a smaller helper-only completion claim.
