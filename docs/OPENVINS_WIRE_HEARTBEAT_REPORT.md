# Shared wire heartbeat dispatch

The supplied-socket wire path now optionally forwards validated, unarmed PX4 heartbeats through its existing decoder before replying to TIMESYNC. This removes one missing interface for a future single-reader capture integration. **The actual capture receiver thread is unchanged, and no actual network/physics run was performed.** Production commit: 3944962d3ee6611db9e542179c8579d1b8923337.

## Why this change

The current capture calls `mavutil.recv_match(type="HEARTBEAT")`. Inspection of installed pymavlink2.4.49 confirms that it consumes messages and continues past other message types, while its UDP reader consumes socket datagrams. The separate `DatagramReceiver` therefore cannot safely be added as another reader of that same stream. The wire responder previously retained decoded non-TIMESYNC messages but did not deliver heartbeats to safety/readiness code.

Use the existing `PinnedCodec` once per datagram and propagate an optional `heartbeat_sink` through `TimesyncWireResponder`, `OwnedWireBootstrap` and `ObservedWireSession`. Default None preserves the previous behavior. No extra socket, receiver thread, codec, process supervisor or installed dependency is added. Installed `mavutil.py` and selected method sources are retained with SHA256 da6f010fed963a63d4b819e734a938c0db84293ccf12e6a427882bfd19b8593b.

The research reuses fixed PX4 d6f12ad (BSD3), installed Python3.12.3 (PSF) and pymavlink2.4.49 (generator(L)GPLv3 with generated-output MIT exception; distribution LGPLv3). Retained maintenance metadata is historical, not a new observation. Official [MAVLink time synchronization](https://mavlink.io/en/services/timesync.html), [message interval](https://mavlink.io/en/messages/common.html#MAV_CMD_SET_MESSAGE_INTERVAL) and [Python socket receive](https://docs.python.org/3.12/library/socket.html#socket.socket.recvfrom) references were consulted. Current protocolv2 documentation does not add target fields to the installed old codec. Existing OpenVINS algorithm/calibration/paper assumptions are unchanged. Callback and journal costs are not measured online latency.

## Contract and failure behavior

- Decode and validate the complete bounded datagram, CRC/framing and all system9/component1 headers before dispatch. In this opt-in fixed profile, at most one heartbeat is accepted; require PX4 autopilot12/version3, unarmed base-mode bit and bounded fields. Bad/multiple/armed heartbeats and malformed mixed TIMESYNC requests preserve input evidence but deliver no heartbeat and send no reply.
- Preserve the original userspace receive-return timestamp in the capture-compatible `arrival_monotonic_ns` field; it is not kernel arrival time or a later callback timestamp. The selected independent simulation observation supplies `observed_sim_ns`. The callback receives a copy.
- Record dispatch attempt with frame index, reserve capacity for its return, then invoke the sink. Record whether it returned None before checking later conditions. A callback returning None is not durable journal success or proof that a downstream consumer completed. Exceptions/non-None/journal failure/time expiry/reentry/close/shared-clock failure latch refusal, without retry or pretending partial delivery was undone.
- In the composed session, dispatch runs through the same profile, owner/descriptor, frozen clock and final freshness checks as the existing send boundary. These remain point-in-time checks, not authenticated ownership or atomic external-state guarantees.
- A heartbeat-only packet never reserves/sends a reply or increments TIMESYNC count. Keep all existing 2s/8s/500/4096 limits, endpoints and qualification flags. No new network, delivery, clock-convergence or fusion authority is granted.

## Verification

The initial 17 tests failed because the callback keyword API did not exist; these are API errors, not behavioral assertion REDs. After implementation, all17 passed. Four more boundary tests exposed one real failure: a heartbeat callback could run after the attempt record exhausted event capacity, leaving no slot for its return evidence. That assertion failed and now passes because capacity is checked before the callback.

Final new suite: **21 tests OK**. Related WSL actual pinned-codec wire/bootstrap/session regression: **111 tests OK**. Windows related contracts: **115 passed, 4 codec-suite skips**; WSL covers those codec suites. Changed-file Ruff and diff-check pass. No new whole-repository result is claimed. All I/O, owners, clocks and listener statuses in these tests are synthetic; installed codec and implementation classes are real.

An independent read-only review of the complete diff found no Critical/Important findings and independently reran all21 cases. One **Minor remains deferred**: the test calling the actual `dispatch_heartbeat` currently uses a fake writer and `fanout=None`, exercising only its queued-writer branch. The `JournaledHeartbeatFanout` branch is **not integration-verified by this stage** and must be covered when binding the actual capture mode. This limitation is not presented as a passing fanout or readiness result.

Five predeclared synthetic exports retain original decoded/receive/dispatch evidence, callback deliveries and fake send bytes: mixed heartbeat/TIMESYNC(1 delivery/1 send), existing writer route(1/0), armed refusal(0/0), capacity refusal(0/0), and return-journal failure after delivery(1/0). Selected producer/test/codec hashes match before and after. These exports are not live packets, actual socket delivery or PX4 convergence evidence.

## Status and next steps

**Verified offline:** shared decoder/callback propagation, mixed ordering, existing queued-writer event compatibility, no heartbeat TIMESYNC-count increment, source/framing/armed refusal, bounded partial-delivery records, callback copy, reentry/close/error/deadline refusal and previous default-codec behavior.

**Implemented only:** opt-in heartbeat route usable by a future capture adapter. Actual worker CLI, socket ownership and receive loop have not switched modes.

**Unverified:** independent journaled heartbeat fanout integration; sole-reader actual capture lifecycle, continuous receive after bootstrap, PostUpdate registration/owned socket binding, live rate apply/ACK/readback/rollback and actual PX4 clock convergence/EKF2 fusion. Default10Hz feasibility and proposed100Hz offline transaction were already documented; no old experiment was repeated and no stream rate was changed.

Next complete the missing fanout integration test and design a single-reader capture adapter with explicit mode handover/cleanup. It must not run `recv_match` and `recvmsg` concurrently. Keep the existing health/watchdog/motion gates; do not connect physical/network operation until its frozen study and authorization gates are met. Full fruit-fly learning/division, fair baseline comparison and swarm verification remain downstream. Five-camera0.873RTF remains below0.95; no hardware/HITL/flight qualification is claimed.

Archive: `evidence/openvins-wire-heartbeat-dev-1701.zip`, with external SHA256/member manifest. Historical failures and archives are preserved. Publication is to existing personal draftPR65, without merge.
