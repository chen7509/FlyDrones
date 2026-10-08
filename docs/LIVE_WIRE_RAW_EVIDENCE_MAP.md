# Live wire raw-evidence map (implementation in progress)

Task 2 of the reviewed live-wire plan is incomplete. This map records the current
producer contracts to avoid inventing a new transport or accepting summary-only
success. The only implemented auditor helper so far is the read-only segmented
record reader. The full `audit_live_wire_study(study_path)` entry point is not yet
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

Remaining Task 2 work: the complete synthetic positive communication chain with
the two permitted non-counting replays; independent corruption/refusal matrix;
raw bytes/status/clock/owner joins and pinned observer replay; actual workload,
ULog/runtime/cleanup checks; study-file adapter and structured audit result.
The whole-package independent review remains pending after Tasks 2–3.
