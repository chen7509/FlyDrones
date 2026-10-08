# Live wire raw-evidence map (implementation in progress)

Task 2 of the reviewed live-wire plan is incomplete. This map records the current
producer contracts to avoid inventing a new transport or accepting summary-only
success. The segmented record reader and the raw protocol consistency helper are
implemented. The full `audit_live_wire_study(study_path)` entry point is not yet
implemented and no real communication is qualified.

| Fact | Existing producer / retained source | Required join and boundary |
| --- | --- | --- |
| Original owner and descriptor | `capture_wire_lifecycle.CaptureWireOwner.bind`, `wire-owner.json` | Owner process identity, descriptor identity/network namespace, exact configuration, start and total deadline. Header identity is not sender authentication. |
| Shared raw history | `openvins_segmented_journal`, `wire-segments/manifest.json` and numbered members | Exact hashes/lengths/member set; global and per-channel ordinals; phases. Index is written during close, so its `complete_retention=false` differs intentionally from successful terminal retention. Neither proves receipt. |
| Terminal retention | `wire-lifecycle.json`, `session.retention` | Must agree with index apart from the documented close-time field/scope. Bind it to captured lifecycle and result; supplied terminal JSON alone is not provenance. |
| Clock entry attempt | `openvins_simulation_clock.record`, `wire-clock.jsonl` | Session, iteration, sim_ns, dt_ns, paused, callback_ns. This callback writes before return, so disk row alone cannot prove commit or journal-return time. |
| Committed clock | `wire-lifecycle.json`, `session.clock.observations` and `attempts` | Join every attempt to final accepted observation and journal_return_ns. Require 25000 exact 1 ms steps and no failure/pending callback. Do not copy a final return time into the historical disk row. |
| Clock selected for a packet | Retention `selection` channel | Exact `session_id`, observation tuple, received_ns and selected_ns join to committed clock and actual datagram receive. Selection is at reply preparation, not PX4 receipt. |
| Actual bytes and local send effect | `openvins_timesync_wire`, retention `wire` channel | `receive` raw_hex/peer/received_ns/observed_sim_ns → pinned decoded frames → reply_prepared request/response/clock_session → reserved → send_attempt → send_return count/start/return. Decode with existing PinnedCodec; never infer delivery from count. |
| Cold epoch/status | `openvins_timesync_bootstrap`, `cold`; `openvins_owned_bootstrap`, `owned` and `listener-*` | Empty pre-reply snapshot, first_status, raw stream chunks and owned listener lifecycle must join. Owner hash is explicitly not cold-epoch proof. Replay exact pinned SerialTimesyncObserver with actual statuses, not model summaries. |
| Legitimate bootstrap replay | `cold.latest_replay` | Must equal first status exactly and `counts_as_new_sample=false`; it does not add an accepted sample. Arbitrary duplicates remain failures. |
| Maintenance handoff | `openvins_timesync_maintenance`, `maintenance` | Boundary raw ordinal normalizes as baseline ordinal + raw ordinal - 1. `boundary_snapshot` must equal baseline and is non-counting. Require at least two subsequently accepted correlated pairs. |
| Interval transaction | Wire interval_send_attempt/return, receive bytes, interval_state | Decode actual GET/SET commands and ACK/readback, including baseline restoration. State booleans cannot replace raw acknowledgments and readbacks. Original deadlines unchanged. |
| Workload and shutdown | Capture source/native/health/reference/ULog logs; runtime pre/post/owned maps; supervisor JSON and sibling JSONL | Native/sensor processing, full callbacks, unarmed status and exact runtime/cleanup evidence remain required. Reuse existing gauge/health auditors without creating a new accuracy pass from this map. |

Source anchors are the committed producer implementations, not evidence of a new
run. The existing lifecycle tests inject socket/process I/O. They are suitable
for positive/negative audit fixtures, but fixture mode must always keep live
qualification false. Startup-only installed results must also remain unqualified.

## Implemented reader boundary

`read_segmented_wire_records(directory, terminal)` verifies local real files
using the existing producer's member schema, quotas and channel set. It rejects
unlisted/missing members, hash or length changes, incomplete/failed/unsealed
retention, duplicate JSON keys, nonfinite values including numeric overflow,
ordinal gaps, phase regressions and unknown rows/channels. It rechecks file
identities and the member set after reading. Original directory text remains
bound between index and terminal, while extraction location may differ.

This is an ordinary local drift check, not an atomic snapshot or protection
against hostile same-UID replacement. The returned records have no independent
kernel provenance. File integrity is distinct from communication acceptance.

Verification: 19 new reader cases plus existing storage and prospective contract
tests passed (72 total); changed-file Ruff passed. Initial RED was missing API.
A separate `1e999` test failed because standard JSON parsing produced infinity
without invoking parse_constant; finite parse_float now refuses it. Real producer
segmentation at 8192+8 records was verified with synthetic event payloads.

## Protocol consistency helper

`audit_wire_protocol_records` now cross-checks raw receive return, selection,
decoded request, reply preparation, observer reservation, attempted send, returned
byte count and later status. It replays existing ColdTimesyncBootstrap and its
maintenance continuation, which use the pinned SerialTimesyncObserver. It does
not implement an approximate replacement filter or MAVLink decoder. PinnedCodec
enforces installed pymavlink 2.4.49 and the existing dialect source hash.

The clock check requires all 25000 exact 1 ms disk-shaped attempts and committed
observations, matching session/iteration/times and journal-return fields. It does
not promote those records to proven simulator callback provenance. Each selected
sample must match an actual member of the supplied observation list. The owned
context hashes to the expected cold epoch tag; the hash still is not kernel
ownership or fresh-process proof.

The positive fixture runs the existing observed/interval/segmented producer
objects with injected socket and process I/O. It contains 500 accepted cold
samples, two accepted maintenance samples, the exact non-counting latest replay
and maintenance boundary. Its clock disk-shaped attempts are reconstructed from
the synthetic lane's in-memory attempts: they are explicitly not real capture
I/O evidence. It retains the existing fixture's 1 ms remote origin; it is not the
future study's 0/0 clock profile or an installed preparation pass.

Sixteen corruption subcases cover raw request/response/receive changes, short or
missing send return, missing/mismatched status, missing cold snapshot, ordinal,
epoch, clock gap/return/session, foreign selection and the two replay boundaries.
Deletion cases reindex the remaining history so they exercise missing causal
records rather than only ordinal-gap rejection. Initial RED was a missing API.
A separate genuine producer fixture gave two correlated maintenance pairs but
only one accepted sample (the first had excessive RTT); it exposed acceptance
based on correlation count alone. The auditor now also requires at least two
accepted samples. This behavioral RED and subsequent GREEN are retained.

The helper still returns `live_qualified=false`, `fusion_qualified=false`,
`owner_transport_qualified=false`, `interval_qualified=false` and
`workload_qualified=false`. It cannot authorize live communication or accept an
entire study. In particular, a matching modeled status requires later joins to
the original owned listener transport, and interval state summaries require
their own raw command/ACK/readback audit.

Remaining Task 2 work: actual owner/descriptor/listener transport joins, raw
interval apply/readback/restore and cleanup, ULog/source/native/runtime evidence,
startup-only negative fixture, and complete study adapter/structured audit.
The whole-package independent review remains pending after Tasks 2–3. No physical
or network experiment has been run in this implementation step.
