# Offline cold TIMESYNC bootstrap and counted-once handoff

The startup coordinator now distinguishes an empty pre-reply snapshot, the first
matching status, and the latest-status replay at the start of a new listener.
The replay does not increment accepted synchronization samples. This is an
offline protocol prerequisite; it grants no live transport or fusion authority.

Implementation: e091f79 spec/plan,435c0b6 composition,1d92b91 review watchdog fix.
The written plan is `superpowers/plans/2026-10-08-timesync-cold-bootstrap.md`.
No PX4, Gazebo, native estimator, network ODOMETRY, parameter changes, training experiment,
arming or multi-aircraft experiment was started in this stage.

## Source-derived interface and reuse

PX4 is fixed at d6f12ad1c4f70ad3230afd7d86e971421e02fef4, BSD-3-Clause.
The existing fixed listener/DeviceNode source and the newly retained
[uORBManager.hpp](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/common/uORB/uORBManager.hpp)
and `.cpp` establish default instance0 subscription and latest-publication replay.
Both Manager source files matched the installed files byte for byte. Repository
maintenance metadata is reused from the preceding study: nonarchived, observed
last push2026-10-07T16:06:37Z. It is not a fresh maintenance query.

The220-byte implicit-one fixture is reused from sealed listener-wire-format ZIP
2b6ee4dc97668336c511b7903c79edc754e953a27b0e3a038b85d48ccb9ac117,
member `native-v1/implicit-one.stdout` under that study directory. Its SHA256 is
ac6ac202582da1725b491cc0a7d326198edd5683fed475e080088795e2e5cda0.
It was produced by unchanged pinned listener code with stub uORB/field printer,
not actual PX4. No native fixture regeneration occurred here.

Reuse the strict decoder and serial numerical observer; only the exact implicit
header is adapted in temporary parser memory. Original bytes/hash remain separate.
Subscription instance0 is not MAVLink channel identity. Listener ordinal1 is not
an observed uORB generation or proof of an additional filter update. Ambiguous
multi-instance snapshots, unrelated syntax and arbitrary control bytes refuse.
This is protocol composition, with no new estimation algorithm or paper claim.
No packages were added. The bounded model costs one serial parser/filter and up
to65536 events; actual runtime throughput and memory suitability are unmeasured.

## Contract and retained failure evidence

The state machine requires empty snapshot, one reserved reply, a matching first
snapshot, and exact numeric replay as explicit stream record1. That replay is
journaled with `counts_as_new_sample=false`. New status2 is consumed as observer2
without renumbering or resetting the filter. One pending reply at a time and
exact declared stream count are enforced.500 accepted samples remain mandatory;
a prospectively chosen501-record profile can retain one later high-RTT rejection.
First-status rejection fails startup, without automatic reset/retry.

The8s readiness and2s progress/pending/frame deadlines remain inclusive and use
the caller-supplied clock. Partial bytes/check calls do not refresh the deadline.
Unsolicited fragments, including fragments after a complete reserved frame in
the same chunk, cannot cross the next reply gate. Journal failure, reentry,
changed identity tags, nonzero exit or time regression latch refusal.

The first recorded RED was a missing-module collection error, not a behavioral
failure. Two later actual assertion failures exposed the early-fragment cases;
both were fixed without changing input or thresholds. Independent review found
one Important: a new reply reservation could mask a silent decoder's old2s
deadline when only public `check()` was polled. Its exact-boundary assertion
failed before the fix, then passed after checking the active decoder on every
transition. The reviewer rechecked the fix read-only and reported no remaining
Critical/Important/Minor issue. Focused adjacent suite:976 passed in1.80s;
changed-file Ruff and diff checks passed. Whole-repository lint is not claimed.
Final full regression, with explicit current-worktree PYTHONPATH, completed with
exit0:3080 passed,3 skipped,2 existing warnings in339.45s. This includes the
repository's existing temporary CLI training smoke fixtures; no new training
study or physical simulator was launched.

The file-only matrix uses prospectively listed synthetic bodies, virtual clocks
and immutable per-event exclusive JSONL files with checked write/flush/close.
It retains all inputs, disk events, partial memory evidence and refusal errors.
All12 cases matched their predeclared outcomes: normal500 and501 with one
retained high-RTT rejection finished with500 accepted modeled samples; insufficient
499 accepted samples, first mismatch, unsolicited fragment, partial next frame,
silent complete-frame deadline, changed epoch, regressed clock, exact8s boundary,
journal failure and nonzero listener exit were refused. Producer1d92b91 and the
harness/three production-module hashes were saved before execution and checked
unchanged afterward. These inputs are analytical, not a live transport capture.
This does not prove crash durability, bounded blocking I/O or measured latency.
Successful numerical models keep `live_convergence_qualified`,
`network_authorized` and `fusion_qualified` false.

## Status and next dependency

|Scope|Evidence/status|
|---|---|
|Offline parsing, state transitions, replay count, refusal watchdog|Implemented and tested; reviewed.|
|Actual cold PX4 source/channel ownership and500 accepted live updates|Unverified; identity tags alone provide no such proof.|
|Transport/process/filesystem socket and responder binding|Not integrated by this module.|
|Actual VIO to EKF2 injection and closed-loop flight|Not performed or authorized by these offline results.|
|Five-camera capacity|Existing0.873RTF remains below0.95.|
|Complete fruit-fly learning/division and fair upstream comparison|Remain overall project requirements.|

Next bind this coordinator to a concrete owned lifecycle/command transport and
exclusive responder, retaining actual identity, cwd/resource selection, source
discovery, listener exit and send/receive provenance. Compose stream restoration
with the existing interval transaction. Do not assume an opaque epoch tag or
successful journal proves these external facts. Synchronous callback blocking
requires caller-side bounded I/O and actual monotonic polling; this model has no
background timer. Preserve8s/2s/500 and the outer25s physical-study requirement.
No native Linux installation, lower physical load or relaxed safety threshold
is justified by this stage. Historic physical and platform failures are retained.

## Evidence

`evidence/openvins-cold-bootstrap-dev-1701.zip` contains the source research,
unchanged native fixture identity, all RED/GREEN outputs, final regression,
prospective matrix inputs and per-event logs, review record and source snapshots.
The sibling manifest records the archive SHA256 and verified member hashes/CRC.
The prior listener-wire-format archive was checked unchanged. Publication
checkboxes are finalized after sealing; the archive retains its pre-publication
plan snapshot. These are ordinary file-integrity checks, not hostile-ABA or
crash-durable storage guarantees.
