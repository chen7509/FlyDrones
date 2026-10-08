# Observed wire session implementation plan

> Use superpowers:executing-plans inline with TDD and final independent review.

**Goal:** Connect independent clock, datagram API and owned wire lifecycle with final pre-send checks.
**Architecture:** One supplied socket, existing actual protocol classes, pinned selected observation through send boundary.
**Tech Stack:** Python3.12 stdlib; pymavlink2.4.49 in WSL; no dependency installation.
**Spec:** docs/superpowers/specs/2026-10-08-observed-wire-session-design.md

## Global constraints
- No new live UDP/PX4/Gazebo/OpenVINS/training; simulated socket/backends only.
- Retain8s/2s/500,127.0.0.1:14548→14588,4096bytes,zero-origin25s/1ms.
- Qualifications false; archive all failures, push personal existing PR65 only.

## Review focus
- A recently committed clock sample cannot refresh an old selected sample.
- A send return cannot disappear because a post-send check raises.
- Guard/journal reentry or close cannot release a reply or commit after refusal.
- Socket/clock/process mismatch cannot be hidden by equality of payload fields.
- Completion500 requires final source/process checks, not only a green old listener.

### Task 1: Compose and verify observed wire session
Files: new tools/benchmark/openvins_observed_wire_session.py, tests/benchmark/test_openvins_observed_wire_session.py; supporting narrow checks in existing receiver/clock modules and tests.
Interfaces: DatagramReceiver.check/progress; JournaledSimulationClock.validate_selection/progress; ObservedWireSession.poll_listener/poll_datagram/close/progress/evidence.
- [x] Unit counterexamples for receiver check and selection validation; implement without changing existing defaults.
- [x] WSL actual-class composition tests first, including normal500 and bounded failures; implement one-socket path.
- [x] Independent whole-change review; reproduce and repair Important/Critical findings in one pass.
- [x] Related Windows and WSL regressions, changed Ruff/diff; retain skipped dependency scope.
- [x] Report/research hashes/sealed evidence; commit/push personal/update and verify draftPR65.

Publication artifacts: report OPENVINS_OBSERVED_WIRE_SESSION_REPORT.md; production a034562; seal 3c6835f. ZIP SHA256 5338b4f98872f6c72dd74051ab2a8349889df7fe871a6dc4157d85e3bf1d36e8 (51 members). Remote publication verification is retained separately in the results directory; the archive intentionally captures the pre-publication checklist.

Ruling: prior explicit user preapproval covers routine stages. Independent review is required by executing-plans. Keep the existing worktree/evidence; do not clean it. Targeted integration/dependency suites are appropriate; no fresh full-repository pass unless a new concern warrants it.
