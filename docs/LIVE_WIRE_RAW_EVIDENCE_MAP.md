# Live wire raw-evidence map (implementation in progress)

Task 2 of the reviewed live-wire plan is incomplete. This map records the current
producer contracts to avoid inventing a new transport or accepting summary-only
success. The segmented record reader and the raw protocol consistency helper are
implemented. `audit_live_wire_study(study_path)` now composes the available checks
as a read-only entry with structured refusals and an explicit unverified list.
Its final qualification gates are incomplete; no real communication is qualified.

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

The subsequent `audit_wire_interval_records` helper checks normal baseline GET,
optional SET/readback, bootstrap, restoration SET/readback and final GET against
actual pinned decoded command/ACK/interval messages. It checks original pending
deadlines, shared outgoing sequence and maintenance ordering; no-mutation baseline
10000 us still requires final GET. Twelve missing/corrupt evidence cases refuse.
Failure-time restoration remains separate and unqualified.

`audit_owned_listener_records` joins all four connection/owner/peer observations
and exact command bytes/returns to daemon raw response envelopes, parsed EOF or
maintenance cancellation and cold/maintenance consumer records. Every listener
event must match its owned transport mirror with command index and order; both
status mirrors must remain exact. It uses the existing production parsers.
Sixteen independent negative cases refuse; bool-as-int transport command index
acceptance was reproduced then fixed. Normal 500-record bootstrap plus three
maintenance records (one boundary, two new responses) passes only consistency.

The listener retains no per-operation kernel descriptor ID and does not log every
owner recheck. SO_PEERCRED observations are not fresh-launch or non-transfer proof.
The cancellation wrapper time is the last checked cleanup clock; socket close
return is not daemon exit. Full workload, runtime binding and owned cleanup must
still substantiate an actual capture independently. All live/fusion flags remain
false, and these tests are fake-I/O producer fixtures rather than actual captures.

## Runtime, ULog and source/native increments

`audit_live_wire_runtime.audit_runtime_mapping_records` re-parses retained raw
maps and compares device/inode/executable and registered PID/session/start ticks
against declared pre/post files. It checks generated copies, baseline continuity,
declared map roles/stages and observation budget. A claimed successful mapping
summary alone is insufficient. Required resource-graph semantics and final
study/dispatch identity joins remain outside this helper; runtime closure stays
false. Final synthetic regressions reject disguising an owned map as a self map
and exceeding the declared observation budget. The existing normal development
capture was checked with the earlier helper, before those two guards; it was not
recaptured or silently re-audited with a different producer.

`native_supervisor_integration.audit_supervisor` now accepts the explicitly named
`normal-capture-v1` profile (completed/exit0/300s). Its default epoch-fault profile
is unchanged (failed/exit2/90s). Both reuse the original group-identity, WNOWAIT,
signals, journal and reap checks. Normal evidence is not rewritten to resemble a
fault. Qualified original-group cleanup does not cover escaped descendants.

`audit_live_wire_ulog.audit_unarmed_ulog` validates immutable whole-stream bytes,
manifest identity and pinned pyulog1.2.4 decoding. Optional counts in the existing
ULog framing validator join each raw data topic to decoded samples; the default
validator return contract is unchanged. Truncation, dropout, missing topic,
non-monotonic time, armed state and decoder sample omission refuse. Its observed
unarmed samples are not a proof of unlogged intervals or exact 25s coverage.

`audit_live_wire_workload.audit_source_native_records` reuses `CausalInput` and
`encode_packet` without constructing a native client. It joins exact source
sequences, FLU/FRD transforms, sample cadence, RGB/CameraInfo payload hashes,
two fan-out journal records, ordered consumer returns, causal releases, complete
encoded request length/hash, native ack clocks and the camera state file. Source
processing and native ack limits remain 2s. A single retained terminal camera at
25s may remain unavailable for `later_imu_missing`; removing this record refuses.
Motion-intent request/ack semantics are checked, but authority from the original
motion log/anchor must still be joined by the full adapter. Raw depth records
retain dimensions and cadence; the original producer did not retain depth pixels,
so this cannot attest depth image content.

The shared callback `observed_sim_ns` is distinct from a sensor's `sample_ns`.
The fixed development log has 107 IMU callbacks observing the preceding 1ms
PostUpdate clock. The first new auditor wrongly imposed sample<=observation and
refused; that outcome is retained. A synthetic regression reproduced it, and the
auditor now preserves both timestamps and replays the existing causal watermark
rules. No runtime clock, sensor, watchdog or acceptance threshold changed.

The new fixed-input workload audit matches 6251 IMU + 250 camera native actions,
one motion intent and 222 public camera states, with all 251 RGB/info/depth source
records and 24 heartbeats retained. This is a new offline join on old development
input, not a new estimator replay or a live-wire run. It grants no VIO accuracy,
health/watchdog, motion authority, runtime or fusion qualification. Payload paths
and source/native runtime provenance still require the full adapter.

Remaining Task 2 work: full study/dispatch/owner/descriptor joins, source/native
health and physics/fast-output coverage, payload file/CameraInfo decoding
provenance, restoration on failure, real startup-only negative fixture and the
complete study adapter/structured audit. The new helpers alone cannot qualify
Task 2 or authorize the live study.
The whole-package independent review remains pending after Tasks 2–3. No physical
or network experiment has been run in this implementation step.

## Study entry and cross-file identity joins

`audit_wire_capture_identity` binds terminal/result copies, closed driver, clock
configuration and original descriptor namespace to the PX4 executable device/
inode, PID/start ticks and session/group already checked from raw runtime maps.
It joins that group and process birth ordering to the normal supervisor audit.
Listener path/start/deadline/expected owner must match the wire owner. Failure
fields and cleanup errors cannot disappear behind a successful capture summary.
Inputs named runtime/cleanup are internal results of raw helpers, not arbitrary
external success summaries. No per-packet authentication or FD-transfer exclusion
is inferred.

The entry reads declared inputs, validates the document contract and refuses
startup-only/failed/incomplete capture before loading dispatch, runtime maps,
supervisor journal, lifecycle/segments/clock, source/native and ULog evidence.
It calls existing raw auditors. Failures retain stage/reason and consumed file
identities. Final ordinary drift checks re-read identities. This API creates no
audit file, socket, process or Gazebo object.

Declared symlinks (such as `/usr/bin/python3`) are followed only after matching
the complete frozen lexical/resolved chain. The canonical regular file is hashed
and the original chain checked again, including at return. Capture members still
reject final symlinks/path escapes. A real WSL same-content retarget refused; the
selected binary was only read. Seven manifest files being verified does not mean
the full dependency inventory was read: those flags are separate, and the broad
`files_verified` flag remains false in this partial entry.

Prospective envelope names are `live-wire-study-dispatch-v1` and
`live-wire-study-completion-v1`. They retain the existing one-shot pattern's
manifest identity, command, run/seed/destination, pre/post resource observations,
timestamps and failure semantics. No producer currently emits these envelopes.
Task 3 must adapt/freeze the existing one-shot executor; the health-only executor
cannot directly consume the new manifest. No second general launcher is added.
Executor attestation remains false; a single-attempt field is not independent
proof of uniqueness.

A real installed-startup result is preserved byte-for-byte as a negative test
fixture with original path/SHA. Despite `capture_completed`, it has no estimator
run and is refused under a synthetic valid study manifest. File-routing positives
use explicit leaf doubles, not a full positive raw chain. Watchdog/motion/gauge
joins, resource graph/CameraInfo decode and the full positive integration fixture
remain open. The entry consequently
always returns `record_chain_qualified=false` and lists the unverified gates.

## Raw physical, prediction and derived-health coverage

`audit_live_wire_coverage.py` now joins all 25000 `native-reference.jsonl`
cycles and 50000 old `physics-substeps.jsonl` rows to the protocol-checked
PostUpdate clock observations. It checks exact epochs, stable parent/child
identity, canary flags, finite/unit states, equivalent RPY/quaternion orientation,
existing MotionPolicy abort bounds, callback order and terminal counts/errors.
The actual wrapper calls the clock before the fresh reference and old Link post
trace. Old Link fields retain `component_refresh_verified=false`; numeric equality
with fresh child fields is deliberately not required. Recorded canaries and
loaded backend provenance are not independent authentication of physical truth.

Fast outputs join their `trigger_sequence` to the exact native IMU acknowledgement,
sample, call start/end and most recently processed camera acknowledgement. The
current `align_fast_target_ns` C++ implementation and existing `fast_grid_qualified`
require 1249 absolute 20ms-aligned targets for first IMU=1ms/end=25s. Unavailable
targets must remain null; successful predictions reuse `transform_fast12` numeric/
PSD screening. Neither this check nor `filter_unchanged` proves all upstream cache
members unchanged, calibrated uncertainty, trajectory accuracy or full decision
latency. The old seed27201 producer has 1250 targets starting at 1ms and correctly
refuses this current profile. Its timestamps and historical results are unchanged.

All 250 camera-health records are recomputed with `project_camera_health_row` and
the existing `OpenVinsHealthContract`. The frozen capture constructs profile
`px4-d6f12ad-gate-floor-v1` with `sim_domain_qualified=false`; no terminal claim
can promote it. Native quality/reset remain null, derived single-session reset
remains zero and final health must match both health-result and ShadowInput.
The default source-health input is the producer's default, not independent
watchdog evidence. This normal-run auditor rejects a replacement/failure; the
separate fault study is not reclassified as a normal completed run.

The file entry invokes these checks and records missing/invalid files at
physical_coverage, fast_coverage or health_coverage. Synthetic file-routing tests
still use leaf doubles. Only the standalone health replay and expected legacy
fast-grid refusal were checked against retained seed27201 files in this increment;
there is no old physical wire-clock journal to fabricate for that run.
