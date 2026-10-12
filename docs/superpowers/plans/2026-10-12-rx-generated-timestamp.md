# Generated RX timestamp Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, task by task; request independent read-only review before qualification/publication. User already approved continued plans.

**Goal:** Decode source-described generated RX metadata without granting unproven source/clock authority.
**Architecture:** Separate exact RX profile, common bounded pre-bind/clock/latch mechanics, strict NEW triple parser; opt-in existing receiver only.
**Tech Stack:** Python3.12 stdlib recvmsg, installed Linux headers/GCC, pytest.
**Spec:** docs/superpowers/specs/2026-10-12-rx-generated-timestamp-design.md

## Global constraints

No bound retrofit or legacy option coexistence/clearing; flags exactly RX_SOFTWARE|SOFTWARE, ts1/2 zero. No source/arrival/clock/fusion/training authority, physics/model startup, old trial rerun, gate change or origin push. ABI probe compile10s; any future socket study is separately frozen/reviewed.

## Review focus

Forbidden-option failure during enable must latch; post-receive conflict must retain raw bytes; strict bool/int layout checks; zero software/nonzero hardware must refuse; caller subclasses cannot supply alternative parsing behavior.

### Task 1: ABI and exact RX profile

- [x] Read latest worktree/resource/failure evidence and fixed official headers/API/source before design.
- [ ] Add tests in tests/benchmark/test_kernel_rx_timestamping.py; bootstrap API failure then behavior RED as applicable.
- [ ] Add tools/benchmark/kernel_rx_timestamping_abi.c; compile once read-only under bounded existing harness with new outputs/hash identity, freeze headers/compiler/ABI. Preserve failure.
- [ ] Refactor only necessary hooks in kernel_datagram_arrival.py, implement kernel_rx_timestamping.py; strict triple/forbidden flags/latch tests GREEN.

### Task 2: Existing receiver integration and review

- [ ] Allow only exact two internal profile types in openvins_datagram_receive.py; use existing raw retention and clock checks; integration RED→GREEN.
- [ ] Run new/NS/legacy/segmented/parity/session adjacent tests, changed Ruff/diff; inspect all results.
- [ ] Independent read-only code/ABI review, fix counterexamples before further activity; seal report/evidence and commit/push personal/PR65/automation.

### Task 3: Later prospective real queue trial

- [ ] Independently declare/freeze exact new RX ABI/code/owned endpoints/run id/timeout/cleanup; test admission and failure evidence, review.
- [ ] Only then one new opaque generated-RX study, preserving missing/failed metadata and close/exit/source hashes. Not authorized by successful parser tests alone.
