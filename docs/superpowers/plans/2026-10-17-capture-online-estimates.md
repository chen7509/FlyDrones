# Capture online estimates implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Human authorized continued software, no staged approvals. Preserve evidence workspace.

**Goal:** Consume the actual owned native fast output during disarmed capture, before subsequent source delivery.

**Architecture:** Managed NativeClient subclass drains only its fresh fast file after each acknowledgement. Existing capture factory selects it; existing ShadowInput latches delivery failure and CaptureJournal owns cleanup. Worker argv and exact declaration bind the opt-in.

**Tech Stack:** Existing Python/NumPy/pytest, no new dependency/native build.

**Spec:** docs/superpowers/specs/2026-10-17-capture-online-estimates-design.md

## Global constraints

No native launch/resource polling/old consumed execution. Original4GiB gates and330/315/360/300s budgets remain. No truth, quality/reset/covariance fabrication, new flight eligibility or new wire sender. Retain complete failures/source before-after/owned fixtures prospectively. Only personal/PR65. Complete source/calibration/fusion/controller mission remains downstream.

## Review focus

- A file from an old capture must be rejected before a child can start.
- Native partial/extra/missing/mismatched output must fail before another input reaches the native client.
- Camera health and50Hz predictions must remain separate; no repeated camera output credited as propagation.
- Failure during parent cleanup must still close additional descriptors/journal and preserve primary error.
- CLI/worker/declaration selection must agree, so an old declaration cannot silently enable new workload.

### Task1: Connect the actual disarmed capture client

Files: new tools/benchmark/capture_online_estimates.py; existing capture_disarmed_sensors.py/capture_contract.py; new tests/benchmark/test_capture_online_estimates.py.

Consumes: NativeClient.send(action,pixels) acknowledgements and fresh flushed fast.jsonl; same child PID. Produces: LiveEstimateNativeClient.send/finish and online-estimates.jsonl; make_capture_native_client selection in existing create_client path. No controller snapshot authority.

- [x] Add failing tests exercising factory selection, real file drain/IMU-camera joins, rejection/latching, partial cleanup, argv/declaration mismatch and inert child/network boundaries.
- [x] Record new tests RED; distinguish missing API from genuine behavior failures. Implement minimal live client and actual capture selection/worker/declaration forwarding.
- [x] Verify new tests and necessary capture-contract neighbors with retained basetemp; Ruff/dedicated diff. No whole old suite/native execution.
- [x] One fresh source review, retain original grades; executor rules every exclusion and performs one bounded fix pass with genuine RED→GREEN where required.
- [ ] Report exact scope/failures, preserve current source/native boundaries, publish only personal/PR65 and carry next real-source dependencies forward.
