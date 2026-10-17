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
- [x] Add tests in tests/benchmark/test_kernel_rx_timestamping.py; bootstrap API failure then behavior RED as applicable.
- [x] Add tools/benchmark/kernel_rx_timestamping_abi.c; compile once read-only under bounded existing harness with new outputs/hash identity, freeze headers/compiler/ABI. Preserve failure.
- [x] Refactor only necessary hooks in kernel_datagram_arrival.py, implement kernel_rx_timestamping.py; strict triple/forbidden flags/latch tests GREEN.

### Task 2: Existing receiver integration and review

- [x] Allow only exact two internal profile types in openvins_datagram_receive.py; use existing raw retention and clock checks; integration RED→GREEN.
- [x] Run new/NS/legacy/segmented/parity/session adjacent tests, changed Ruff/diff; inspect all results.
- [x] Independent code/ABI review and coverage repair; no remaining findings. fb77f53 pushed only personal; PR65 and active automation updated. 57-member ZIP SHA256 a6465dfc0a74a65031c5847208706b6dd3c316410e8087249714924e4e90b537, all hashes/CRC verified. Sealed plan copy retains its pre-publication checkbox state; this bookkeeping does not rerun capability.

### Task 3: Later prospective real queue trial

- [x] Separate study design7c23ac0 declared/froze exact RX inputs/endpoints/timeout/cleanup, tested faults and independent review before dispatch; see rx-generated-queue-study plan/report.
- [x] Exactly one new study attempted and failed on missing first metadata; raw byte/close/exit/hash preserved in d461a34/72-member evidence. Option-drift case was not reached; this completes an attempted study, not an arrival/source qualification. No retry.
