# PX4 Odometry Source Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a fail-closed, prospective, diagnostic-only PX4 v1.17 logger topic file and offline audit that can support a later unarmed DDS/ULog source trial without claiming runtime or workload qualification.

**Architecture:** An exact repository fixture and declaration define one named topic profile. A standard-library auditor checks the exact bytes and provenance, then a small CLI emits a refusal or candidate JSON; it never changes PX4 files. A later plan will bind the fixture into an owned rootfs and check actual ULog/DDS/Agent evidence after resource gates pass.

**Tech Stack:** Python 3.12 standard library, pytest, pinned PX4 v1.17.0 source, existing ULog preflight.

**Spec:** `docs/superpowers/specs/2026-10-10-px4-odometry-source-diagnostic-design.md`

## Global Constraints

- PX4 commit `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`; logger source SHA-256 `33c1cd7c55dc81d4fa53153b7f269401b67c7f6edc929707ec536203096bcfe5`.
- Profile `source-diagnostic-v1`, `SDLOG_PROFILE=0`, exactly ten ordered instance-zero lines; 230 ASCII LF bytes, SHA-256 `0bb9a3d9b57c6a73c73e8fee75569b9e690857654c4631b6f6cd5b6654328994`.
- The candidate never grants runtime selection, source authentication, DDS/ULog parity, fusion, training, unchanged load, capacity, hardware or flight.
- Do not modify a PX4 rootfs, start PX4/Gazebo/Agent, or run a competing container in this plan.

## Review Focus

- A CRLF or missing final LF must refuse even when the visible topic names match; Task 1 tests both.
- Python `bool` must not pass as integer `sdlog_profile`; Task 1 tests it.
- A valid-looking extra topic or duplicate topic must refuse; Task 1 tests both.
- A wrong pinned PX4/logger hash must refuse; Task 1 tests both.
- CLI failure must exit nonzero while retaining structured refusal evidence; Task 2 tests it.

---

### Task 1: Exact diagnostic profile and pure audit

**Files:**
- Modify: `.gitattributes` (pin this fixture's LF checkout bytes)
- Create: `config/px4/source-diagnostic-v1/logger_topics.txt`
- Create: `config/px4/source-diagnostic-v1/profile.json`
- Create: `src/flydrones/connectome_training/px4_logger_diagnostic_profile.py`
- Test: `tests/connectome_training/test_px4_logger_diagnostic_profile.py`

- [x] Write tests for `audit_profile(topics: bytes, declaration: object) -> LoggerProfileAudit`: canonical input yields `logger_file_candidate=True` and all downstream qualifications false. Test visible-name mutation, duplicate/extra line, CRLF, missing final LF, unknown key, wrong PX4/logger/topic SHA, `sdlog_profile=True`, and `diagnostic_only=False`; every mutation refuses with a stable reason.
- [x] Run the new test file and observe the missing implementation failure.
- [x] Add the exact fixture and seven-key declaration from the spec. The auditor first validates the strict declaration schema and exact types, then compares the 230 bytes and SHA, then parses the fixed v1.17 three-field syntax without accepting malformed or duplicate names. Return an immutable audit result with `reason`, `logger_file_candidate`, `runtime_topic_selection_verified`, `dds_ulog_parity_verified`, `source_authenticated`, and `eligible_for_training`.
- [x] Run targeted tests; compare the checked-in fixture SHA with the spec literal and run changed-file Ruff.
- [x] Commit only this task's source, fixtures and tests.

### Task 2: Read-only CLI and old-log refusal regression

**Files:**
- Create: `tools/connectome/audit_px4_logger_diagnostic.py`
- Extend: `tests/connectome_training/test_px4_logger_diagnostic_profile.py`
- Create: `docs/PX4_ODOMETRY_SOURCE_DIAGNOSTIC_REPORT.md`

- [x] Write a CLI test for `main(argv: list[str]) -> int`: a canonical file/declaration prints a JSON candidate and exits 0, a modified file prints structured refusal and exits 1, and absent/unreadable input refuses. CLI success is only the offline file candidate. Avoid importing the whole training package, which requires Torch in WSL.
- [x] Run those tests RED, then implement `--topics` and `--declaration` arguments with a direct isolated import of the pure auditor and strict read errors.
- [x] Run the CLI on the fixed fixture and a separate mutated copy; save outputs and exit codes in a new results directory. Re-run `audit_px4_ulog_odometry.py` on the two old ULogs without starting PX4; both must remain refused because `vehicle_odometry` is absent.
- [x] Run targeted and relevant adjacent tests, changed-file Ruff, `git diff --check`, and an independent review. State any full-suite limit explicitly if a competing task or memory makes it unsafe; do not invent a pass.
- [x] Write a report that separates file candidate, runtime untested, old ULog refusal, and the later Agent/DDS dependencies. Seal source/config/report/results with member hashes and CRC in a new evidence ZIP; commit, push only `personal`, and update draft PR65.

### Task 3: Future owned physical source trial (deferred by explicit gates)

**Files:** A new stage spec/plan after Tasks 1–2 and the synthetic DDS/CDR parity gate.

- [ ] Before implementation, require synthetic typed DDS/CDR field parity, a pinned Agent v2.4.3 executable and resource-qualified isolated launch. Recheck owned rootfs, actual logger topic selection, ULog topic/schema and dropouts, Agent/PX4 identities, clocks, reset, unarmed safety and cleanup.
- [ ] Name one new diagnostic physical study; freeze its changed logging load and do not reuse performance or five-camera RTF thresholds as if unchanged. Preserve every failure. No training or fusion grant follows solely from field parity.
