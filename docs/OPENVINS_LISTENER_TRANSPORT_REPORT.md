# Owned read-only listener byte transport

The adapter now sends a strictly allowlisted listener command and reads its
response on the same Linux socket whose peer was checked against an owned
process. The private ordinary-process fixture completed three normal cases and
refused four faults. No actual PX4 daemon, MAVLink responder, simulator, estimator,
ODOMETRY output, parameter mutation or new training study was started.

Design98cc705, first implementationbf2c9dd, return-evidence fixes2f8f77b,
concurrent-refusal capacity fixa8790ce, frozen kernel-fixture producerd593a8b.
Spec/plan are under `superpowers/specs/2026-10-08-readonly-listener-transport-design.md`
and `superpowers/plans/2026-10-08-readonly-listener-transport.md`.

## Protocol source and reuse

Retained BSD-3-Clause PX4 source is pinned to
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4`:
[client.cpp](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/posix/src/px4/common/px4_daemon/client.cpp)
joins argv with spaces and appends the isatty byte;
[server.cpp](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/posix/src/px4/common/px4_daemon/server.cpp)
waits for that terminal byte, then returns stdout, a NUL/one-byte status trailer,
and shuts down the connection. This implementation does not require client
half-close, despite the older header prose. Non-PTY byte0 is used here.

Only `listener timesync_status -n 1` and
`listener timesync_status -i 0 -n COUNT` (literal count2..4096) are allowed.
This is a Python adapter derived from the inspected protocol, not a claim that
the unchanged upstream client ran. Existing same-connection peer checks, strict
snapshot/multi decoders and sealed native output fixtures are reused. General
shell commands and reconnecting after checking another socket are rejected.

The installed Python3.12.3 socket API (PSF license) and Linux SO_PEERCRED are reused;
no dependencies were installed. Sources/API references and hashes are in
`results/openvins-listener-transport-dev-1701/research.json`. Maintenance metadata
is reused from the prior source study: PX4 nonarchived, last push observed
2026-10-07T16:06:37Z; this is not a new maintenance query. No new VIO algorithm or
paper result is claimed by this protocol work.

One nonblocking stream socket is used, with response limited to4MiB+2, chunks to
4096 bytes, snapshot to1024 bytes and regular journal events to65536 plus one
independent refusal record. A single owner polls. The global window remains8s
and complete-frame timeout2s; connect/send time does not reset that frame budget.
Filesystem, process observations and journal callbacks remain synchronous and
require outer supervision. These checks are not asynchronous interruption or a
live throughput qualification.

## Independent review and error evidence

The initial RED was a missing-module import error, followed by31 passing tests.
Three subsequent behavioral REDs exposed a late-entry frame clock and loss of
actual I/O returns after crossing a deadline. Those were corrected before34 pass.

Independent review found three Important issues: the first returned clock could
be ignored, event capacity could exhaust after I/O, and a secondary journal error
could mask a clock interrupt. Five behavioral REDs preceded the fixes. A further
review exposed concurrent refusal consuming capacity reserved for a pending I/O
return; both send and receive counterexamples failed before the independent
refusal slot fix. Final interface suite:41 passed. Read-only re-review reported
no remaining Critical/Important/Minor findings.

The actual returned clock is retained and validated, even if a later reading
looks valid. Regular capacity is reserved before I/O; the terminal refusal does
not consume it. Completed I/O evidence survives a concurrent refusal. Primary
interrupts and secondary journal/close errors are retained independently. A
currently executing operation may still finish; no retroactive rollback is
claimed. Parsed stream rows are provisional until valid zero trailer, actual
EOF, decoder completion and final ownership/time/journal checks.

## Real local fixture results

`kernel-v1` prospectively fixed seven cases, a1ms polling cadence,2ms fragmented
write cadence, source/fixture/Python executable hashes and the existing timing
bounds. Private `/tmp/fly-listener-*` sockets were used. The220-byte implicit and
484-byte multi outputs originated from the previously sealed pinned native
listener fixture with stub uORB/field printer; they are not live PX4 output.

|Case|Actual result|
|---|---|
|Single snapshot|Complete, exact30-byte command and220-byte stdout.|
|Never-published snapshot|Complete, exact30-byte command and16-byte stdout.|
|Fragmented two-record stream|Complete, exact35-byte command and484-byte stdout.|
|Missing exit trailer|Refused at EOF.|
|Nonzero exit trailer|Refused.|
|Silent peer|Refused on complete-frame timeout.|
|Journal error before send|Refused; server received zero command bytes.|

All seven direct owned servers recorded client EOF and exited0 without TERM or
KILL. There are no descendants in this fixture; no global cleanup claim is made.
Selected hashes match before/after, and journal records match in-memory evidence.
Write boundaries are not assumed to equal socket read boundaries. All adapter
fusion/network/live-listener qualification flags remain false. Initial harness
Ruff found one import-order issue, corrected before execution; it was not a
failed runtime case. No blind rerun was performed.

Full regression completed with exit0:3166 passed,3 skipped,2 existing warnings
in336.46s. Changed-file Ruff and Git diff checks passed; no full-repository lint
pass is claimed. The suite includes existing temporary CLI smoke fixtures, not
a newly authorized training study. Independent read-only runtime evidence/report
review found no material overclaim or unresolved issue.

Selected producer source and fixture copies were exported from Git after the run
and matched to recorded pre/post hashes. They are post-run exports, not claimed
contemporaneous source copies. The sibling archive manifest records SHA256,
member hashes and CRC. The archive retains its pre-publication plan snapshot;
publication checkboxes are finalized afterward.

## Remaining gates

Implemented and locally verified: actual bounded command/response byte I/O,
same-descriptor owner checks, strict framing and controlled failure evidence.
Unverified: a real cold PX4 epoch and empty-to-first-to500 accepted update chain,
exclusive TIMESYNC channel/responder ownership, live source discovery, measured
accepted rate and interval restoration. The adapter does not implement a
MAVLink responder or authorize any live command/parameter experiment.

Next compose this transport with the existing cold-bootstrap state machine in a
prospectively fixed ordinary fixture, retaining one pending reply and one latest
replay counted once. Establish which actual transport observations support each
state transition. Do not equate a listener consumption ordinal with uORB
generation or a supplied identity tag with kernel-observed ownership. Live
integration remains behind its separate authorization and preflight gate.

The broader goal remains incomplete: VIO-to-EKF2 flight-control fusion, complete
fruit-fly learning/decision/division in that loop, fair upstream baseline
comparison and5/20-aircraft qualification remain downstream. Existing physical
VIO and simulation covariance results do not establish hardware calibration.
Five-camera0.873RTF remains below0.95; no load or acceptance threshold changed.
All historical failed evidence remains retained.
