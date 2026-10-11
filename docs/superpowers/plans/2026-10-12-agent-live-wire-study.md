# Agent-inclusive Live Wire Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a strict offline declaration for one future Agent-inclusive unarmed PX4/Gazebo study without altering v11.

**Architecture:** Extend the existing pure/file study validator with an explicit v2 branch; keep v1 exact. Prepare v12 from sealed v11 selection plus committed changes and the fixed Agent runtime record. The existing one-shot executor remains separate.

**Tech Stack:** Python 3.12, pytest, existing runtime snapshot and capture contracts.

**Spec:** [Agent-inclusive study design](../specs/2026-10-12-agent-live-wire-study-design.md)

## Global Constraints

- v11 and all failures remain immutable; do not start physics while below the 4 GiB gate.
- The v2 mode requires seed 27602, the original workload/thresholds and an owned `agent` role.
- No Agent listener or offline preparation grants typed DDS provenance, fusion or flight authority.

## Review Focus

- v1 accepted with Agent or v2 accepted without Agent: reject both.
- Missing/mismatched Agent declaration, bundle, binary or library path: reject.
- Missing owned Agent runtime phase, wrong seed or extra command option: reject.
- Selected file changes between preparation and validation: reject without rewriting outputs.
- Nonempty capture/dispatch/completion/audit path: refuse and retain existing evidence.

### Task 1: Validate an Agent-inclusive study

- [ ] Write pure v2 success and rejection tests in `tests/benchmark/test_live_wire_study.py`.
- [ ] Observe RED, then implement the minimal v2 branch in `tools/benchmark/live_wire_study.py`.
- [ ] Run v1 and v2 tests, including file-adapter drift cases.

### Task 2: Prepare one v12 declaration

- [ ] Add a one-off preparer under `results/live-wire-study-dev-1701/` that verifies the sealed v11 source, committed changes and fixed Agent files.
- [ ] Generate fresh v12 input/output paths and negative cases without launching anything.
- [ ] Validate with `validate_live_wire_study_files` and `prepare_live_wire_execution`; independently audit hashes, roles and outputs.

### Task 3: Publish evidence

- [ ] Run targeted regression, changed Ruff and `git diff --check`.
- [ ] Record verified/implemented/untested/failed status, seal evidence and independently check ZIP members.
- [ ] Commit exact files, push `personal` only and update draft PR65.
