# Serial TIMESYNC status observation: offline contract

## Scope and evidence

Prepare the missing pre-publication observation component without opening a
socket, starting PX4, changing stream rates or granting receiver/fusion authority.
The current request authorizes design and offline validation, not live injection.
The parent receiver plan remains reopened at Task 4.

Nine installed source files were compared byte-for-byte with PX4
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4` and match. Evidence is under
`results/openvins-timesync-observer-dev-1701`. This is selected source equivalence,
not proof of a clean checkout, complete reproducible binary or actual transport.

Pinned listener prints a consumption ordinal, not the uORB generation. Installed
generated `timesync_status` metadata has queue depth one. Ordinary continuous
publication can overwrite unread state; a listener count cannot prove completeness.
`TimesyncStatus` has no convergence field. The pinned MAVLink wrapper constructs
`Timesync _timesync{}`; its default source is UNKNOWN (0), not MAVLINK (1).
The installed generated TIMESYNC dialect has targeting extensions, but the
pinned receive handler does not enforce request/sender matching. The observer
cannot infer channel identity from protocol enum or targeting extensions.

## Choice

Model a stop-and-wait companion: reserve one real reply identity, then require
the matching status before another reservation. This avoids overwriting our own
unobserved update *under a single controlled producer assumption*. A missing
status closes the gate at 2 s; it is never counted as an accepted exchange.
The existing verifier receives the reconstructed PX4 receive instant:
`request_us + round_trip_time_us`. Publication timestamp is only checked to be
at or after receive time, never used as that receive instant. Match the entire
observed filter output including its integer-microsecond estimated offset.

Reject interpreting listener ordinal as publication count. Reject granting live
authority from the following pure class. A native diagnostic module exposing
generation/convergence is a fallback requiring a changed PX4 binary and new
provenance; do not build one before the existing-tool candidate is evaluated.

## State and interface

`SerialTimesyncObserver(session_id: str, topic_instance: int)` owns one
`BoundedTimesyncVerifier`, one pending `(request_ns, response_ns, reserved_at_ns)`
and a permanent fault latch. It consumes a fresh epoch with modeled zero initial
filter state. `reserve_reply(request_ns: int, response_ns: int, now_ns: int)`
records intent only; caller must journal before any future transport send.
`observe_status(status: dict, now_ns: int) -> dict` consumes exactly these keys:
`instance`, `ordinal`, `timestamp`, `remote_timestamp`, `observed_offset`,
`estimated_offset`, `round_trip_time`, `source_protocol`. Units follow pinned
status microseconds; request/reply identities are positive, integer-microsecond
aligned signed-int64 nanoseconds. Source protocol must equal the pinned 0.

`check(now_ns: int)` checks local monotonic time and a 2,000,000,000 ns inclusive
pending deadline. Equal local times are allowed; regression latches failure.
Every protocol/type/range/identity/time/filter mismatch latches failure. A second
reservation while pending also latches: integration must wait, not overwrite.
Use exact dict keys, strict ints (no bool), uint64 timestamps/local clock,
uint32 RTT/ordinal, uint8 instance/protocol and int64 offsets. Instance range is
0..255 here, a representability check only; runtime must validate actual uORB
instance bounds. Request and response identities increase strictly per session.
Ordinal begins at one and increases once per observed status; it detects gaps
in the observation record, not hidden uORB generation loss. Even equal local
timestamps cannot revive an expired or failed session.

For matched status, predict with a cloned verifier and compare integer-us
offsets before committing. RTT >=10 ms is a recorded filter rejection, not a
transport fault, and never increments accepted count. A filter clock-jump reset
is a permanent observer refusal. No in-place session reset: create a new object
and separately prove a new PX4 clock/filter session. Do not relabel the old
filter as cold after only replacing the companion.

Outputs name the counter `modeled_accepted_samples` and flag
`observed_model_converged`; `live_convergence_qualified`, `network_authorized`
and `fusion_qualified` are always false. No boolean from a caller can grant them.

The shared verifier exposes `estimated_offset_us` by directly truncating its
microsecond estimate, before any nanosecond scaling. Its observed-offset
numerator uses sign-aware integer division, avoiding float rounding at large
valid timestamps. Neither change alters pinned PX4 code or filter constants.

## Required runtime proof still missing

Before live qualification, bind PX4 process/channel, clock session, native
listener process, exact wire/request records and status topic instance. Bootstrap
requires one controlled reply because listener refuses an unpublished topic;
identify its status instance without assuming zero, and retain any listener
restart/baseline observation without double counting. Prove no uncontrolled
positive-TIMESYNC updates on that filter, no hidden reset, and complete output
framing. A matching ordinal alone does not prove these assumptions.

The POSIX source supports `px4-listener --instance 8 ...` as a client dispatch;
topic `-i` has a different meaning. This command was not invoked. Evaluate its
stdout formatting/backpressure and startup semantics before implementing a live
adapter. Stream rate change, cold-start proof, listener bootstrap and real-time
500-accepted timing remain separate unresolved gates. No added warmup, relaxed
8 s readiness, 25 s duration, 200 ms force anchor or 2 s source watchdog.

## Validation

Offline fixtures cover matched/rejected RTT, 500 accepted statuses, missing/
duplicate/foreign/partial status, in-flight overlap, exact timeout, local/PX4/
remote clock regression, malformed types/ranges, offset mismatch, reset and
post-failure refusal. Synthetic tests demonstrate only state-machine behavior.
Do not repeat prior physical VIO runs or claim live listener reliability.
