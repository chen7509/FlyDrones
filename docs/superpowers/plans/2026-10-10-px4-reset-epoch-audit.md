# PX4 reset-epoch audit implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Preserve and reject EKF2 coordinate reset history before any student capture producer can use an observation sequence.

**Architecture:** A small pure audit accepts the pinned ULog topic-array shape, validates source time/counter fields, records every reset transition and chooses nonfuture rows for each original camera time. It never constructs student observations or marks live capture eligible.

**Tech Stack:** Python, NumPy, pytest; existing retained ULog extraction.

**Spec:** `docs/superpowers/specs/2026-10-10-px4-reset-epoch-audit-design.md`

## Global constraints

- Use only development seed 27201; no held-out audit/tuning or new physical run.
- Keep all past failed/success evidence and original `audit_state_sample_times` unchanged.
- No runtime, camera or training eligibility claim from ULog-only input.

## Review focus

Check between-frame transitions, counter wrap, malformed integer/clock arrays, nonfuture selection, permanent failure latch, and absence of an eligibility grant.

## Task 1: Pure audit

- [x] Write focused RED tests for normal, missing, between-frame reset, wrap and malformed input.
- [x] Implement the smallest audit with explicit rows/reasons and permanent epoch refusal.
- [x] Run targeted GREEN and adjacent timing/shadow tests.

## Task 2: Frozen development input

- [x] Check fixed NPZ and its manifest/ULog identity; run the audit on 251 original image times.
- [x] Retain every row and transition, report results without constructing training data.
- [x] Run appropriate regression, Ruff, diff check and read-only review.
- [x] Seal evidence, commit to the existing branch, push only `personal`, update draft PR65.
