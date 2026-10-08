# Wire heartbeat dispatch implementation plan

> Execute inline with superpowers:executing-plans, TDD and one final independent review. User preapproval applies; retain this existing worktree/evidence.

**Goal:** Preserve safety heartbeat delivery through the same actual decoder/socket path without introducing a competing reader.
**Spec:** docs/superpowers/specs/2026-10-08-wire-heartbeat-dispatch-design.md
**Technology:** existing Python3.12/pymavlink2.4.49, WSL unittest, no install or live network/physics.

### Task 1: Add opt-in shared-decoder heartbeat dispatch
Files: tools/benchmark/openvins_timesync_wire.py, openvins_wire_bootstrap.py, openvins_observed_wire_session.py; tests/benchmark/test_openvins_wire_heartbeat.py; docs/OPENVINS_WIRE_HEARTBEAT_REPORT.md.
- [x] Inspect and retain installed mavutil receive/filter source and source hashes; use existing upstream metadata, no duplicate inventory or default-rate experiment.
- [x] Write actual-codec tests for HB-only/mixed and failure boundaries; observe RED.
- [x] Add the optional callback through existing classes, validate before side effects, preserve delivery attempts/returns and existing defaults; GREEN.
- [x] Independent whole-change review; fix Important/Critical with deterministic RED→GREEN in one pass.
- [ ] Related Windows/WSL tests, changed Ruff/diff, report, immutable evidence, commit/push personal and verify PR65.

No actual capture CLI/network changes. No concurrent reading through mavutil and recvmsg. Do not present synthetic receive times as measured latency. Existing100Hz interval transaction is an offline model, not a qualified applied setting. Full objective stays active.
