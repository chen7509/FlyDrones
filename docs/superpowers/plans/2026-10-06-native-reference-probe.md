# Native Reference Probe Implementation Plan

> Inline execution under standing authorization; one independent review at completion.

**Goal:** Prove diagnostic outputs overwritten each physics cycle and fail closed before further force.
**Architecture:** Native pybind extension plus Python TestFixture adapter using existing shared errors and lifecycle. No separate System Stop/IPC implementation.
**Tech Stack:** Existing Python3.12,pybind11 2.11.1,gz-sim8.15,C++17/pytest.
**Spec:** docs/superpowers/specs/2026-10-06-native-reference-probe.md

- [ ] Tests first for adapter refusal/order/logging and native synthetic overwrite behavior.
- [ ] Implement native module, build script and capture adapter/CLI; targeted tests and real production import checks.
- [ ] Freeze binary/source/config; at most one named sensor-only capture and unchanged-input raw/child/parent audit. Preserve all failures.
- [ ] Full regression, one independent code/evidence review, corrections tested, report/ZIP/draftPR and next-step automation.
