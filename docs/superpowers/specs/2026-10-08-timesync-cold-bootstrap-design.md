# Offline cold snapshot and stream handoff

Goal: compose the existing framing decoder and serial observer into the actual
planned first-reply sequence, without mistaking old latest data for a new accepted
sample. Existing worktree/user preapproval applies to this offline implementation.
No PX4/Gazebo/native estimator, network, parameter/stream mutation or arming.

## Source and approach

Fixed PX4 d6f12ad listener_main.cpp, uORBManager and DeviceNode support this
sequence. Implicit `listener timesync_status -n 1` emits exact `never published\n`
when no instance is advertised. With exactly one advertised instance it prints an
unnumbered header but calls orb_subscribe, which subscribes instance0. This is
source-derived subscription identity, NOT a MAVLink channel index or proof that
the sole producer was the intended receiver. Multiple instances are ambiguous
and refused. A new subscription can replay the latest publication; listener #1
is a consumption ordinal, not a generation or necessarily another filter update.

Choose a narrow transport-neutral state machine. Reuse the strict field parser
by replacing only the exact implicit header with its source-derived explicit0/#1
header in a temporary parsing buffer, while retaining raw bytes/hash separately.
No general text normalization, ANSI stripping, new parser for field numbers or
invented wire nonce. Reject alternatives which assume channel==instance, reset
the filter from observed values, or count the latest-data replay again.

## Contract

`parse_snapshot(raw: bytes, exit_code: int) -> dict`: max1024 original bytes,
exit must literal0. Exact empty or implicit-single format only, strict trailing
bytes/fields. Return kind empty/single, status/None, original byte count and SHA.
The status instance0/#1 is explicitly labeled subscription/consumption identity.

`ColdTimesyncBootstrap(session_id, epoch_token, start_ns, journal,
*, stream_records=500)` is a synchronous single-owner model. IDs are nonempty
bounded ASCII tokens; stream_records500..4096 is prospectively chosen, not adapted
after failures. `journal(event)` must return None only after the caller's chosen
write/flush/close discipline, and failure latches. This module does not implement
durable storage, background watchdogs, process identity verification or transport.
An epoch token is a comparison tag, not evidence of a fresh PX4 process.

Public transitions take keyword-only now_ns and epoch_token:
1. confirm_empty(raw, exit_code): require exact empty snapshot before any reply.
2. reserve_reply(request_ns, response_ns): first intent only; existing observer
   checks integer/microsecond identity. Journal before returning intent. A returned
   intent is not proof of transmission or permission to publish network traffic.
3. confirm_first(raw, exit_code): require exact single snapshot and matching cold
   observer result, including one accepted sample. First high-RTT rejection fails
   this bootstrap; no blind reset/retry.
4. begin_stream(listener_token): bind one listener identity and instantiate the
   explicit multi decoder. No later reply allowed until its #1 exactly repeats
   the first numeric status. Snapshot age text can differ; all status fields must
   match. This replay is journaled but does not advance the observer.
5. feed_stream(data, listener_token): use the pinned multi prefix profile, preserve
   each raw chunk. Later replies/statuses are serial; a second outstanding reply,
   unsolicited/duplicate row, wrong listener/epoch, field drift or reset fails.
   Partial unsolicited bytes also refuse immediately; a completed reserved record
   followed by a partial next record in the same chunk refuses, rather than
   retaining those early bytes across the next reply reservation.
   The first real new status uses listener ordinal2 and observer ordinal2 directly;
   no renumbering or dropped generation is invented. High RTT afterward follows
   the existing observer: preserve rejection, require enough later accepted data.
6. finish_stream(exit_code, listener_token): exact declared count, no pending
   reply, clean complete decoder exit and >=500 modeled accepted samples required.
   Declaring more than500 records allows bounded rejected samples but does not
   alter the acceptance threshold or evidence time window.

Every call validates monotonic uint64 local clock, unchanged epoch token, global
8s readiness limit and2s progress/pending/frame limits, inclusive at deadline.
Partial bytes and mere check() calls do not refresh progress. No startup timer
reset, hidden warmup, schema relaxation, restart or shorter convergence target.
The outer study remains25s; this class only covers its readiness interval.
Use a nonblocking transition lock; concurrent/reentrant calls latch refusal,
including when a journal callback swallows a reentry exception. Retain partial
events, never pretend a failed journal rolled back delivered bytes.
Cap the modeled journal at65536 events (plus at most one terminal refusal), so
empty chunks or a nonadvancing supplied clock cannot grow evidence without bound.
This evidence-size limit changes neither the500-sample threshold nor time gates.

All results retain live_convergence_qualified/network_authorized/fusion_qualified
false. Only successful final closure sets modeled_bootstrap_ready. External
fresh-launch, command-socket/cwd/runtime binding, exclusively controlled responder,
actual send/capture provenance and live delivery are unverified prerequisites,
not boolean inputs that can grant authority to this model.

## Verification

Reuse the sealed native implicit-one capture without recompilation/replay.
Synthetic empty snapshot and two-stage stream must cover startup, exact replay,
499 new accepted rows, retained high-RTT rejection in501-record profile, early/late
snapshot, process tags, stale/duplicate/unsolicited statuses, prefix fragments,
stderr/diagnostic equivalents in stdout, nonzero exit, journal failure and reentry.
Refuse incomplete500 and exact2s/8s edges. File-only failure matrix retains all
cases and authorityfalse. Independent review and regression precede sealing.
