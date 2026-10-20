# Sixth Synthetic DDS Attempt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permit one separately recorded synthetic DDS attempt after the verified v5 memory refusal without changing safety or resource limits.

**Architecture:** Extend only the fail-closed result selector in the existing one-shot harness. The established launch and preflight code remains unchanged, so the selected result directory is the only runtime difference.

**Tech Stack:** Python, pytest, Docker image already pinned by the harness.

**Spec:** [sixth-attempt design](../specs/2026-10-10-px4-synthetic-sixth-attempt-design.md)

## Global Constraints

- Keep `MIN_FREE_KIB=900000`, image/binary/type hashes, CPU/memory/network limits, 60-second timeout and cleanup behavior unchanged.
- Preserve all v1–v5 results and use only a new `-v6` directory.
- Do not infer PX4 publisher identity, fusion or training eligibility from synthetic DDS.

## Review Focus

- A malformed or absent v5 preflight must refuse before creating v6.
- A v5 result that ever launched must refuse even if its status says preflight failure.
- Boolean or noninteger memory values must not masquerade as measured KiB.
- Failed Docker cleanup or unknown container presence must not be a pass.
- A callback with no independent parity file must not be a pass.

## Task 1: Gate the sixth attempt

- [x] Add a pytest case for verified v5 memory refusal and refusal after `launch.json` appears.
- [x] Run it and observe the missing-selector failure. The first command had a `PYTHONPATH` import failure; the corrected run yielded one expected selector failure and four passes.
- [x] Add the minimum `--retry-after-v5-memory-refusal` selector returning `-v6` only for exact unlaunched memory refusal.
- [x] Run targeted and adjacent tests, Ruff, and diff check.

## Task 2: Execute and preserve one attempt

- [x] Check host memory, process and Docker occupancy; run the unchanged harness once if preflight can decide.
- [x] Preserve all preflight, launch, journal, publisher/subscriber, parity and terminal evidence, including failures.
- [x] Independently classify the result, update the report, seal evidence with hashes/CRC, commit and update PR65.
