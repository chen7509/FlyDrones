# Reversible TIMESYNC interval: offline contract

Continue the receiver-startup prerequisite, not the overall flight qualification.
The user approved routine plans in advance; this stage remains offline-only.
No socket, PX4 invocation, parameter change, physical run or ODOMETRY publication.

## Source-grounded choice

Reuse the existing parameter transaction's attempt-before-write and independent
restore verification pattern, but give stream intervals their own strict contract.
PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4 (BSD-3-Clause),
`mavlink_receiver.cpp` set/get_message_interval and `mavlink_main.cpp`
configure_stream/threadsafe are retained under
`results/openvins-timesync-interval-dev-1701`. Official wire definitions:
https://mavlink.io/en/messages/common.html#MAV_CMD_SET_MESSAGE_INTERVAL
https://mavlink.io/en/messages/common.html#MESSAGE_INTERVAL

SET takes a float32 interval, converts to float32 rate; configure_stream converts
back to float32 interval and truncates to int. Require exact wire representation
AND exact pinned roundtrip before mutation. A queried -1 may mean no stream or
an unlimited stream; queried 0 cannot be restored via SET 0 (which selects the
default). Refuse both. This narrow profile accepts only positive signed-int32
intervals with an exact roundtrip; it does not invent disabled/default restoration.
Candidate TIMESYNC message111 interval10000us remains a proposed 100Hz setting.

configure_stream_threadsafe waits for processing unless exiting; the ACK is not
necessarily emitted before application. Nevertheless the receiver's found-id
success does not report configure_stream outcome. Require separate exact readback.
Configured interval does not prove achieved transmission or filter acceptance rate.

Use stdlib only. No new dependency or service. Current PX4/pymavlink maintenance
and license observations are reused from the startup study, not freshly claimed.
Installed pymavlink2.4.49 remains the future wire adapter candidate. Alternatives:
blind SET/default restoration is rejected; modifying PX4 or building a generic
command framework is unnecessary here. No estimation algorithm or paper-derived
noise model changes; existing OpenVINS references remain unchanged.

## API and lifecycle

`TimesyncIntervalTransaction(transport).run(body)` is single-use, single-owner.
Transport exposes bounded read_interval(111) -> exactly one dict with message_id
and interval_us, and set_interval(111, interval_us) -> literal bool True only on
accepted acknowledgement. The future adapter must prove endpoint/channel,
freshness and correlation; mocks do not prove those. MAVLink supplies no local
transaction nonce; this abstraction must never be called wire correlation proof.

Validate baseline before writes; use fixed10000us candidate. Record attempted
ownership before calling set, verify ACK and separate readback, then call body.
Body must return literal True to declare its modeled checks passed. It runs while
the candidate is applied; the transaction does not claim continuous rate checks.
On every mutation-phase exception, including cancellation, try original-baseline
restoration. Restore readback runs independently even if write/ACK failed. Final
readback is distinct. Preserve primary failure and all restoration errors.
Re-raise KeyboardInterrupt/SystemExit after storing last_result and cleanup.
If already at candidate, do not write; final drift fails without overwriting an
unowned external change. A second/reentrant call fails before transport access.

Events are memory evidence, not durable intents. No synchronous Python helper
can bound a transport which never returns or survive SIGKILL. Future live adapter
needs watchdog, durable journal, exclusive ownership and a process-level exit path.
Do not imply these are implemented here. All network_authorized,
live_rate_qualified and fusion_qualified remain false. modeled_transaction_pass
only covers the supplied transport/body observations.

## Validation

Normal apply/body/restore; already-candidate; ambiguous/malformed/duplicate
baselines; float precision/reciprocal drift; lost apply ACK after mutation;
wrong readback; timeout/cancellation/body failure; failed restore ACK/readback;
final drift; reused transaction. Retain every failure. Native float-expression
and in-memory pymavlink encoding checks support arithmetic/wire compatibility,
not a real PX4 execution. Then focused regression, independent review, full suite,
changed Ruff/diff, report and sealed evidence. Parent live gates remain open.
