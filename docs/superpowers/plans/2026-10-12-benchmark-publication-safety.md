# Benchmark publication safety Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; independent review before publication. User has approved continued plans.

**Goal:** Stop benchmark motion/physics after command/source/publisher failures while preserving SI/frame/limits and evidence.
**Architecture:** Existing shared facade/native backend, numeric contract helpers, latched condition state, serialized MAVLink callbacks, explicit failure/cleanup records.
**Tech:** Python/threading/math/NumPy, existingMavlinkDrone/pymavlink interface, pytest fakes; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-12-benchmark-publication-safety-design.md

## Constraints/review

LOCAL_NED/mask/SI and configured limits unchanged; source policy0.5s unchanged/unqualified; no truth-as-VIO/source grant, hardware/physics/network/test restart, force-disarm or unrelated process termination. Review swallowed background errors/false ack, pending close/timeouts, source read race and LAND errors, in-flight send/step boundary, malformed/numeric state.

- [x] Inspect current code/resource/source reports and primary official protocol before spec.
- [ ] Add meaningful failing tests in tests/benchmark/test_publication_safety.py; preserve actual RED against currentgateway.
- [ ] Implement strict numeric/shaping and facade refusal; native source check/stop/condition/lock/error propagation in gateway.py; no normalized-body rerouting.
- [ ] Test valid/source/transport/cleanup/concurrency/step/regression behavior and preserve all failures; changedRuff/diff.
- [ ] Independent read-only review; fix findings with RED/GREEN, record software/physical boundaries, seal report/config/source/hash/evidence.
- [ ] Commit/push personal and update PR65/automation; keep full goal active and source/physical/model gaps unresolved.
