# Pinned PX4 listener wire-format correction

Date:2026-10-08. Base:d88f394; design:fdcc640; implementation:598017a;
binary fixture checkout protection:ca5cd98.

Evidence: `evidence/openvins-listener-wire-format-dev-1701.zip`, SHA256
`2b6ee4dc97668336c511b7903c79edc754e953a27b0e3a038b85d48ccb9ac117`.
43 members,52050 bytes; CRC and member hashes verified. Prior listener and owned
launch archives remain unchanged. The archived report/plan precedes this ZIP
publication note and final publication checkbox; external manifest pins the ZIP.

## Result

Source review during cold first-status bootstrap exposed a real compatibility
gap: pinned PX4's explicit multi-record listener writes an eight-byte clear-screen
and cursor-home prefix before every frame, even on a non-PTY stream. The prior
strict decoder rejected these bytes. Its hand-authored multi-record fixture
omitted them, so the old tests did not establish actual multi-record framing.
This does not invalidate the old byte-parser refusal results or prove anything
about physical VIO accuracy; it reopens the listener integration claim explicitly.

The decoder now has opt-in `output_profile='px4-d6f12ad-multi-v1'`. It accepts only
the exact fixed prefix at a frame boundary and requires at least two records.
It rejects arbitrary ANSI, misplaced/duplicate/truncated prefixes, diagnostics,
wrong fields or ordinal, trailing bytes, bad exit and timeouts. Prefix bytes
count against the unchanged raw byte limits; incomplete data never refreshes
the two-second complete-frame deadline. Historical default `plain-v1` remains
strict and still rejects all control bytes. There is no autodetection/sanitizer.

The field parser and serial numerical observer remain unchanged. All live
listener/network/fusion authority flags remain false. The parser is synchronous:
the future process harness must call `check()` during silence. Raw source bytes
must still be retained by that harness.

## Source and probe evidence

- Fixed PX4 commit:d6f12ad1c4f70ad3230afd7d86e971421e02fef4, BSD-3-Clause.
- [Pinned listener implementation](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/systemcmds/topic_listener/listener_main.cpp)
  SHA256 a33b4bfcefaf836ee8595d3f7ba4cac12c383a27866f6722eaa31314701a5f83.
  Current installed file matched the sealed source byte-for-byte before compilation.
- Prior listener archive SHA256
  999eef9ccca35343fcec547a6e0fbefe70401221846eadc62bc9cd2dbae3dc40
  was checked; the consumed member equals the new compiled source exactly.
- PX4 maintenance observation is reused from the preceding channel research:
  non-archived, last-pushed2026-10-07T16:06:37Z. This is not a new metadata fetch
  or proof all installed patches match the pin.
- Current [MAVLink protocol guide](https://mavlink.io/en/services/timesync.html)
  and [PX4 uORB guide](https://docs.px4.io/main/en/middleware/uorb) were consulted.
  The current guide's targeted v2 responses do not change the older pinned
  receiver behavior. Pinned source remains authoritative.

One native build/run set compiled the unchanged listener_main.cpp against
explicit fake uORB subscriptions, a pollable pipe and a handwritten field printer.
The fixture selects unbuffered stdout with setvbuf; it is not a real PX4 command
daemon, native uORB publisher, field renderer, socket, buffering or latency test.
The real listener code supplies its control bytes, record headers and count logic.
Compiler identity/version/flags, source inputs and compiled binary SHA are retained;
inputs matched after all three bounded invocations. Runtime dependency closure is
not claimed by this compilation record. No installation or simulator was needed.

|Probe|Exit|Raw bytes|Meaning|
|---|---:|---:|---|
|explicit instance0,2 records|0|484|Both native prefixes and headers observed; stub fields.|
|explicit instance0,1 record|0|234|No multi prefix; existing plain framing.|
|implicit instance,1 record|0|220|Different unnumbered header; remains unsupported by this decoder.|

The retained two-record fixture SHA256 is
e3b3453862a2a4e219f3c5b96c717a82e5de37e9bd0df7f452764ac64cc854f9.
Its exact484 bytes equal the Git blob. A nested `.gitattributes` marks `.bin`
binary so Windows checkout cannot normalize its LF/control bytes. The initial
Git warning and attribute before/after records are retained; no evidence bytes
were rewritten. The new profile adds a bounded cursor/per-byte parsing cost,
without a dependency. Live throughput and resource capacity remain unmeasured.

## Tests and scope

Focused decoder/observer/interval suite:914 passed. New profile tests cover all
483 split points of the native capture, byte-by-byte delivery, malformed/control
placement, EOF/deadline, field/count/exit refusal and byte limits. The recorded
two frames feed the serial observer; a separate analytical500-record chain
reaches modeled convergence with all live authority false. No synthetic timing
or500-record count is claimed as measured PX4 throughput.

Initial523 failures were missing-keyword TypeErrors, not523 behavioral bugs;
one old-default rejection test already passed. The first GREEN attempt found
one faulty synthetic500-case expectation: a hand-fixed -1000 offset estimate
does not account for double-filter/truncation arithmetic. It was replaced by
an exact zero-offset analytical chain. The recorded native two-frame input and
production filter were not changed, and the failed attempt remains available.
Changed Ruff passed. Whole-repository lint is not claimed.

Final full regression with explicit current-worktree PYTHONPATH:3018 passed,
3 skipped,2 existing warnings in328.93s; the completed process returned exit0.
Fixed-byte adaptation independently retained the old plain-profile rejection,
new native-profile two-record acceptance, explicit one-record plain acceptance,
and implicit-header refusal. These are fixture-format outcomes, not live status
ownership or convergence evidence.

Independent read-only review found no actionable Critical/Important/Minor issue
in the code, framing tests and fixture provenance. The reviewer ran no tests or
native workloads. Its existing slot was reused after a fresh spawn hit the agent
thread limit; this is an independent reviewer, not a claim of a new empty session.

## Remaining gate

This corrects a concrete prerequisite, not the cold bootstrap itself. Still
needed: fresh owned PX4 lifecycle and filesystem command socket, exclusive
responder, actual source discovery, first reply/status association, listener
runtime/exit and delivery, capture cwd/resource binding and reversible stream
transaction. Preserve500 accepted samples,8s readiness,25s total and2s watchdogs.
No network ODOMETRY, parameter/stream change, EKF2 injection, arming, training or
swarm expansion occurred. Five-camera0.873RTF<0.95 and prior physical failures
are unchanged. Full fruit-fly learning/division and fair baseline comparison
remain downstream project requirements.
