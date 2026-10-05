# OpenVINS native online shadow implementation plan

Spec: docs/superpowers/specs/2026-10-06-openvins-online-shadow.md

## Global constraints

User has authorized continuous implementation, tests, evidence and draft PR publication. Use the existing isolated codex/openvins-online-shadow branch. Preserve all evidence and failures; no new task, competing processes, truth input, flight commands, network ODOMETRY or relaxed initialization. Keep the work ledger for reproducibility despite the skill's generic cleanup advice.

### Task 1: Native transport and process contract

Interfaces: new openvins_online_shadow.py encodes bounded packets and guards sources; new openvins_online_probe.cpp consumes bytes and returns acknowledgements. Existing native library and fast helper stay pinned.

1. Record upstream API/noise/threading research and source hashes; freeze the named development configuration.
2. Write Python unit tests and a WSL synthetic parser/timeout test driver; run RED before implementation.
3. Implement bounded protocol, worker lifecycle, source watchdog, native diagnostics and fresh propagation. Compile against the pinned library, run GREEN including malformed data, byte ownership, path/clock and blocked-child cases.
4. Commit transport and tests with the observed evidence.

### Task 2: Causal recorder handoff and online capture

Interfaces: CaptureWriter optional post-record hook feeds ShadowInput; capture_disarmed_sensors optional native arguments are forwarded through its supervisor. Default sensor-only behavior stays intact.

1. Write failing tests for causal image handoff, retained raw evidence on consumer failure and source silence.
2. Implement hook, client integration and cleanup; retain failure without losing raw capture evidence. Add capture hashes and result scope.
3. Run focused tests, source/process preflight and one new 25-second requested disarmed online shadow with frozen configuration. Preserve a failed or shortened run; don't rerun to hide it.
4. Audit input/ack counts, timing, initialization, predictions, disarmed ULog and released processes. Commit integration.

### Task 3: Evidence, independent review and publication

Interfaces: raw capture and targeted/full test logs feed an explicitly scoped report and exclusive evidence archive.

1. Run applicable regression, archive code/config/version/input/output/failure hashes and state the four statuses (verified, implemented, untested, failed).
2. One fresh-context independent branch review; one RED→GREEN fix pass for valid findings, preserve review and fixes. No repeated completed estimator experiment unless a material fix requires a newly named run.
3. Seal evidence, commit and publish a draft stacked PR against PR35; attach it and record closure. Update the existing heartbeat with actual next dependency and unresolved gates.
