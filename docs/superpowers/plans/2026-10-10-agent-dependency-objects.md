# XRCE Agent Dependency Objects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the five fixed direct Agent dependency Git objects locally and report remaining closure/build gaps.

**Architecture:** Fetch each exact object into its own bare repository, then inspect raw Git objects without checkout conversion or replacement refs. Write one manifest and an independent read-back audit; do not invoke CMake or PX4.

**Tech Stack:** Git, Python 3.12, pytest, JSON.

**Spec:** [dependency-object provenance design](../specs/2026-10-10-agent-dependency-objects-design.md)

## Task 1: Fixed-object fetch

- [x] Preflight process/memory/disk and record the fixed URL/ID set.
- [x] Fetch each exact ID once into a fresh isolated bare repository; retain unsuccessful attempts.
- [x] Verify `cat-file -t` commit, `rev-parse <ID>^{tree}`, requested ID equality, object availability and bare repository identity.

## Task 2: Source metadata and closure audit

- [x] Read raw LICENSE, `.gitmodules`, gitlinks, CMake ExternalProject/FetchContent declarations and build README at each commit; retain hashes and paths.
- [x] Add rejection tests for wrong object type/ID, missing license, gitlink without recorded source, unexpected direct fetch and incomplete inventory.
- [x] Run an independent manifest-to-Git read-back and targeted regression; report verified direct sources separately from unresolved transitive/build dependencies.

## Task 3: Publication

- [ ] Seal result, manifest, commands, tests and failures with per-member SHA-256/CRC; run independent review.
- [ ] Commit, push only `personal`, update draft PR65 and the continuing automation. Leave Agent build and PX4 trial unqualified.
