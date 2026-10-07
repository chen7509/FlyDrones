# TIMESYNC interval implementation plan

> Use superpowers:executing-plans inline, task by task.

**Goal:** Prove offline restoration semantics before any future TIMESYNC rate change.
**Architecture:** Strict pinned float conversion plus single-use transport transaction;
separate modeled outcome from all live authority.
**Tech stack:** Python stdlib/pytest, installed C++ and pymavlink for offline probes.
**Spec:** `docs/superpowers/specs/2026-10-08-timesync-interval-design.md`.

## Constraints and review focus

No network/PX4/physics. Message111/candidate10000us only; preserve failures.
Positive int32 baseline must be exactly wire/reciprocal representable.
Lost ACK can follow an applied write; cancellation must attempt restoration.
Restore ACK and readback are independent; never promote mock success to live proof.
Missing/duplicate/wrong-message baseline must fail before writes.
Already-candidate drift must not cause an unowned write.
Timeout guarantees require a future bounded adapter, not a synchronous wrapper.

## Task 1: Offline implementation

- [x] Add `tests/benchmark/test_openvins_timesync_interval.py`, retain initial RED.
- [x] Implement `tools/benchmark/openvins_timesync_interval.py` per spec.
- [x] Run targeted tests and existing observer/preflight regressions:123 passed.
  Receiver regression is included in the full suite.
- [x] Compare native float expressions and installed pymavlink in-memory encoding:
  100005 arithmetic cases without disagreements; five wire roundtrips.

## Task 2: Review and publication

- [x] Independent bounded code review; retain and repair important counterexamples:
  exception formatting cleanup bypass, four behavioral RED-to-GREEN cases.
- [x] Full pytest with current-tree PYTHONPATH:2154 passed/3 skipped/2 existing
  warnings in329.43s; changed Ruff and diff checks passed.
- [x] Add `docs/OPENVINS_TIMESYNC_INTERVAL_REPORT.md`, seal evidence with hashes/CRC:
  38 members, SHA256 `ffd12ba00a70f5ea32ae2724a8603009dd47dba4d08dfe088dbe2bfd56d26629`.
- [x] Commit/push personal and update PR65 without marking live gates complete.
  Implementation/seal `43a309e`. These completion marks record publication after
  sealing; the ZIP retains the pre-publication plan. First PR-body construction
  failed on CRLF matching, made no edit, and succeeded after newline normalization;
  the original attempt note is retained outside the already sealed archive.
