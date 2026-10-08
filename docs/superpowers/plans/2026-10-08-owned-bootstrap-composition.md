# Owned bootstrap composition implementation plan

> Use superpowers:executing-plans inline, with TDD and independent final review.

Goal: bind existing cold bootstrap to actual owned read-only listener I/O.
Architecture: one coordinator; original clock window; three owned connections;
one persistent stream; reply intents remain explicitly unproven.
Stack: Python3.12, existing LinuxBackend/ReadOnlyListener/ColdTimesyncBootstrap.
Spec: ../specs/2026-10-08-owned-bootstrap-composition-design.md

## Global constraints

- Ordinary private fixtures only; no PX4/MAVLink/ODOMETRY/parameters/physics.
- Original8s total and2s progress/frame/pending,500 accepted modeled samples.
- Same registered owner on actual sockets; all live/fusion authority false.
- Preserve every failure; push only personal and update existing draftPR65.

## Review focus

Check hidden callback/reentry fault propagation, last completion after deadline,
partially constructed transport evidence, owner drift between socket lifetimes,
and provisional stream results escaping as final readiness. Cover in Task1 tests.

## Task1: coordinator and targeted tests

Files: tools/benchmark/openvins_owned_bootstrap.py,
tests/benchmark/test_openvins_owned_bootstrap.py.

- [x] Retain fixed upstream/API and existing interface research; write failing
      normal/fault tests. Expected: new interface unavailable, clearly label this
      initial failure; later behavioral counterexamples must fail assertions.
- [x] Implement poll/reserve_reply/close/progress/evidence with copied journal
      envelopes and shared clock/owner gates. No actual reply sender.
- [x] Run tests and adjacent bootstrap/transport regressions, Ruff/diff; expected
      no failures. Commit implementation and tests.

## Task2: actual private fixture and publication

File: tests/benchmark/check_openvins_owned_bootstrap.py.

- [x] Freeze explicit normal500 and fault cases, command/control payloads and
      selected hashes; run one private-server matrix, preserve all outcomes.
- [x] Independent code/evidence review; behavioral RED/GREEN for material fixes;
      full regression expected green. Do not claim real PX4 convergence.
- [x] Update report and verified/implemented/unverified/failed boundaries; seal
      new archive with SHA/member hashes/CRC; preserve previous archive.
- [x] Commit/push personal, update and verifyPR65. Keep overall goal active.
