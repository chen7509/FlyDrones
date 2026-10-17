# TIMESYNC wire responder contract

## Intent and authority

Close the byte-level request/reply gap before the future owned PX4 cold-start
study. Reuse installed pymavlink 2.4.49, not a protocol imitation. This stage
performs only in-memory codec and injected sink tests. It supplies no socket,
PX4 launcher, parameter setter, ODOMETRY publisher, or fusion authorization.
The user has preapproved continued design and implementation; no new approval
round is needed. Prior failures and evidence stay intact.

## Research and choice

Fixed PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4 (BSD-3-Clause)
handles tc1=0 by responding and tc1>0 by updating its filter. The inspected
handler has no target-address filtering. Installed pymavlink 2.4.49 common v20
has only tc1/ts1, CRC extra 34; TIMESYNC service v1 is distinct from MAVLink2
framing. Current official TIMESYNC v2 documentation cannot add fields to this
installed schema. See retained research under results/openvins-timesync-wire-dev-1701.

pymavlink v2.4.49 tag resolves to 2a500b8acfb507255d02ed8257b6eb132e5b86d7.
The repository COPYING describes (L)GPLv3 generator and an MIT exception for
generated output; distribution metadata says LGPLv3, GitHub license detection
says Other. Fresh repository metadata is nonarchived, pushed 2026-10-06.
The installed generated common.py SHA is
a7c6b23d908322134d19cb94b937c1ea6b1f5d5ffa9d1b0ad139174bf8d75809.
Reuse costs one existing Python import and bounded packet buffers, with no
installation, estimator or simulation load. Windows lacks this dependency;
actual codec tests run with WSL Python3.12.3 and stdlib unittest.

Alternatives rejected: hand-written payload/CRC decoding duplicates upstream;
upgrading schema hides the deployed-version mismatch; relying on signed flag
without a key falsely claims authentication. Source clock/filter algorithms
and OpenVINS paper are unchanged; no new estimation algorithm is introduced.

## API and composition

New tools/benchmark/openvins_timesync_wire.py provides PinnedCodec and
TimesyncWireResponder. PinnedCodec verifies installed version/source hash and
schema, and refuses CRC bypass. decode_datagram(bytes) accepts complete unsigned
MAVLink1 or MAVLink2 frames, including multiple messages per datagram, using
upstream decode for payload/CRC. Limits: 4096 bytes, 64 frames. Reject incomplete
headers/payload/checksum, garbage, unknown dialect messages, incompat/compat
flags, signature frames and TIMESYNC payloads beyond the fixed 16-byte schema.
No cross-datagram fragment splicing, resynchronization or network receive occurs.
These are a declared bounded datagram profile, not measured PX4 compatibility.

TimesyncWireResponder(remote_clock, reserve_reply, send_sink, journal, now,
start_ns, peer=('127.0.0.1',14588)) reuses RemoteMonotonicClock and an externally
owned serial reservation callback compatible with OwnedBootstrap.reserve_reply.
receive(raw, peer, received_ns, observed_sim_ns) validates the entire datagram
before any reservation/send. All frames must have system9/component1. Other
known message types are recorded and ignored; one TIMESYNC request at most;
unexpected TIMESYNC responses or multiple requests refuse the whole datagram.
Request/response nanoseconds must be positive int64 multiples of1000, strictly
increasing across replies. Request identity is ts1, not the 8-bit header sequence.
Reply tc1 comes from the separate observed-simulation-to-remote clock, never
from the request's timestamp. Clock session replacement refuses this responder.
Reply uses sender254/component191, explicit wrapping send sequence and upstream
pack. Encoding does not imply send/delivery/filter acceptance.

Journal receive bytes/peer/time, decoded headers, reply bytes and reservation
intent before invoking send_sink(bytes, peer). The caller supplies the sink;
this repository stage supplies no network sink. Reservation must return the
exact existing false-authority intent. A send result records actual returned
count before validation; short/noninteger/failed/late returns latch failure,
and a successful count proves only sink acceptance. A failed sink can have
side effects; never claim rollback. Subsequent requests fail after any refusal.
The existing reservation coordinator enforces one pending reply until matched
status; this adapter does not release reservations or invent status samples.

## Safety, clocks and evidence

Original global8s and per-request2s inclusive deadlines remain. All local
clock values are strict uint64 and monotonic; receive time cannot be future
or2s old. Check after synchronous journal/reservation/sink calls and before
send. Blocking calls need outer process supervision; this is not preemption.
Use a nonblocking operation lock; concurrent/reentrant calls latch failure so
an outer call cannot continue to send after callback reentry. Preserve failed
input and partial effects. Maximum8192 regular events plus one refusal.
Journal receives independent copies and must return None. Journal failure is
latched even if a prior send already happened. Evidence remains available after
failure, including a refusal-journal error. Primary KeyboardInterrupt propagates.

Header/source endpoint equality is an observation, not authentication, unique
producer proof or a cold epoch. All network_authorized, delivery_proven,
live_convergence_qualified and fusion_qualified flags remain false.

## Verification and exit

Use real installed codec for valid v1/v2, batched traffic, trimmed payloads,
CRC/signature/unknown/oversized/truncated faults, exact peer/source/schema,
replay/wrap, actual RemoteMonotonicClock, actual SerialTimesyncObserver pending
and status association, sink short/exception/late, reservation and journal
failures, reentry and exact deadlines. Preserve the earlier14-case codec probe
without rerunning it. A Windows skip is not codec verification. Independent
review and targeted adjacent regressions precede sealing/report/PR65 update.
Future work still needs concrete bounded UDP ownership/receive/send integration,
correlated interval ACK/query, cold actual PX4 status/500-sample throughput and
rollback evidence. This stage cannot authorize those live mutations.
