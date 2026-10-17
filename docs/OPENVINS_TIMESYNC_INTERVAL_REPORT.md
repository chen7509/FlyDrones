# Offline reversible TIMESYNC interval

Date: 2026-10-08

## Decision

Implemented a single-use interval transaction for the future receiver startup
study. It reads an unambiguous restorable baseline, attempts the proposed10000us
TIMESYNC interval, verifies it independently, runs a supplied observation body,
and restores/verifies the original baseline even after a lost acknowledgement.
This stage supplies no network adapter and made no live stream or parameter change.
`network_authorized`, `live_rate_qualified`, and `fusion_qualified` always remain
false. Task4 launch readiness and Task5 live authorization remain open.

## Source semantics and reuse

Pinned PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4 is BSD-3-Clause. The four
retained source files are copied from the previous startup study, with original
URL/hash provenance verified again; no whole-checkout equivalence is asserted.
PX4/pymavlink maintenance observations are explicitly reused from that study.
Installed pymavlink2.4.49 uses the retained LGPL package provenance, not a guessed
license from GitHub's NOASSERTION field. No packages were installed.

- The pinned [receiver](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/mavlink/mavlink_receiver.cpp)
  converts requested interval to float rate. Its get handler returns -1 for a
  missing stream, but the stream implementation also uses -1 for unlimited rate.
  SET zero selects default rate; it cannot restore a queried zero literally.
- [configure_stream](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/mavlink/mavlink_main.cpp)
  converts the rate back to a float interval and truncates to int.
  configure_stream_threadsafe waits for processing unless exiting. It is wrong
  to describe this as always acknowledging before application. The receiver's
  found-id outcome still does not propagate the actual configure result.
- The [wire command](https://mavlink.io/en/messages/common.html#MAV_CMD_SET_MESSAGE_INTERVAL)
  carries float parameters. A signed-int32 MESSAGE_INTERVAL response can contain
  positive values that cannot be sent back without losing float precision.

Adopt the existing parameter transaction's attempted-write ownership pattern.
Refuse negative/zero/ambiguous baselines and positive values that cannot survive
both wire representation and the pinned reciprocal conversion. This avoids
inventing a disabled/default restoration interpretation. No generic network
framework or PX4 fork is introduced; stdlib-only implementation has low adaptation
cost. Existing OpenVINS algorithm/paper choices and noise assumptions are unchanged.

## Implementation and limits

`tools/benchmark/openvins_timesync_interval.py` restricts the transaction to
TIMESYNC111 and proposed10000us. A strictly shaped single baseline response must
precede mutation. Write ownership is marked before calling the transport, so a
remotely applied command followed by missing ACK still causes restoration.
Body success, ACK success, readback success and final baseline equality are
separate requirements. Literal True is required for ACK/body success.

Baseline already10000us needs no owned write; a later external drift fails final
verification without being overwritten. Reentrant/repeated use is refused.
Cancellation is retained and rethrown only after best-effort restoration and
last_result storage. Primary and restoration errors stay distinct.

The transport/body are caller-supplied synchronous interfaces. This class does
not prove endpoint identity, fresh wire correlation, exclusive stream ownership,
timeouts for calls that never return, or cleanup after process death. Its events
are memory records, not fsync/durable intent. No actual adapter is installed.
Configured interval is not observed transmit rate or accepted filter frequency.
Local call order does not create a MAVLink transaction nonce.

## Evidence and verification

Results: `results/openvins-timesync-interval-dev-1701`.

- Initial missing-module collection failure retained as an implementation RED;
  it is not a behavioral assertion failure. The original suite had48 passing
  cases before review; the final suite has52.
- Independent review found one Important defect: exception `__str__` could itself
  raise and bypass restoration. Four apply/body/restore/readback counterexamples
  failed, then passed after guarded formatting. Reviewer reran all four and
  reported no remaining actionable findings within this offline scope.
- Focused interval/observer/preflight suite:123 passed. Changed-file Ruff passed.
  Full current-tree regression:2154 passed,3 skipped,2 existing warnings in
  329.43s. Explicit PYTHONPATH selected this worktree's src/root. No
  whole-repository lint success is claimed.
- A source-derived standalone C++ arithmetic probe (not a PX4 build) tested
  positive1..100000 plus five larger boundaries:100005 cases,94658 accepted,
  5347 refused, zero acceptance disagreements with the Python predicate.
  This is bounded evidence, not exhaustive proof over every signed-int32 value.
- Five actual installed pymavlink2.4.49 in-memory COMMAND_LONG/MESSAGE_INTERVAL
  roundtrips retained complete bytes. Requested10000/100000 remain exact;
  16777217 becomes16777216 in COMMAND_LONG while MESSAGE_INTERVAL preserves it.
  Intervals49/61 are wire-exact but rejected for pinned reciprocal drift.
- Compiler identity/version/flags, expression source, helper, codec file and
  selected source hashes were recorded before/after the native experiment.
  Helper snapshot belongs to the pre-review producer; final change only guards
  exception rendering and was verified separately, not called a native rerun.

## Status and next dependency

|Status|Scope|
|---|---|
|Verified offline|Exact restorable-baseline predicate, fault/cancellation restoration, native expression comparison, in-memory wire fields.|
|Implemented|Single-use transaction over an abstract bounded transport/body.|
|Unverified|Live ACK/query correlation, real rate apply/restore, actual throughput, listener bootstrap/framing, cold/exclusive filter identity.|
|Preserved failures|Initial collection failure, four review regressions, all prior physical and protocol evidence.|

Next: finish the source-backed listener bootstrap/framing and exclusive channel
contract, then compose the concrete replacement preflight with bounded live
adapters and all refusal exits. Do not run another ordinary25s VIO study to test
this missing protocol layer. Future actual mutation requires its separate gate.
No ODOMETRY publication, EKF2 injection, arming, training or multi-aircraft run
occurred. Complete fruit-fly learning/division of work and fair baseline evidence
remain downstream. Five-camera0.873RTF remains below0.95; this work is not a
capacity optimization or a conclusion about fruit-fly learning performance.

## Seal

Evidence is sealed in `evidence/openvins-timesync-interval-dev-1701.zip` with an
internal member manifest and an external SHA-256/CRC summary. Source provenance,
initial failure, review RED/GREEN, full/focused tests and native/wire outputs are
included. The pre-review native helper is reconstructed after the run and checked
against its recorded pre/post hash, not presented as a contemporaneous source copy.
Prior startup/observer archives are verified unchanged. The archived plan retains
pending publication marks; later checked marks only record successful publication.
