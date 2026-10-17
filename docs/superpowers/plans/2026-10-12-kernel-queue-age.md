# Kernel queue-age implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; independent requesting-code-review. Blanket user approval retained.

**Goal:** Reject conditionally old/uncertain generatedRX packets before receiver return, preserving source/clock qualification boundaries.
**Architecture:** ExactpreparedRX prebind interval sampler and single-receiver binding; optional refusal integration in existingreceiver; immutable bounded diagnostics; no newjournal/transportworker.
**Tech:** ExistingPython/socket/int arithmetic, dataclasses/threading and pytestfakes.
**Spec:** docs/superpowers/specs/2026-10-12-kernel-queue-age-design.md

## Constraints/review

2s remains strict, PX4state100ms separate; defaults unchanged, exactRX only, noNS fallback. Noqualifiedclock/source/control/network/physics/model/teacher/training grant. Reviewbefore-bind/sample-domain/clockcallback races, partialrawretention, postjournalage, restoration behavior and eventbudget. An observedconstant-offset model is not continuousclockproof. No new real packet experiment or old evidence rewrite.

- [x] Complete primaryresearch/context/spec before implementation.
- [x] RED tests for interval math/queue backlog and refused bindings in tests/benchmark/test_kernel_queue_age.py; implement tools/benchmark/kernel_queue_age.py.
- [x] RED runtime receiver fake integration for oldqueuedpacket/finaljournal/clockfault/rawretention/EAGAIN/reentry; modify tools/benchmark/openvins_datagram_receive.py with opt-in compatibility and existing eventbudget.
- [x] Focused/affected regression, changedRuff/diff/sourcebefore-after; independent review/corrections. Verify frozen8 saved observations via declaredretrospective interval math, no fabricatedprebind or newpacket.
- [x] Report verified/onlyimplemented/untested/failed and source/clocklimits; seal allfailedlogs/config/versions/hash/CRC; commit/pushpersonal/PR65/automation withnext dependency. Fullgoalactive, no completeclaim.

Publication: implementation/evidence commit8d5d2ce pushed onlypersonal; PR65 description and ACTIVE heartbeat updated after independent final51-member archive review. The immutable archive intentionally retains the pre-publication unchecked plan; this working plan records subsequent completion without rewriting evidence. Windows188/3whole-module skips plus WSL75fixture/codec checks are separate scopes. No network/physics/model qualification granted.
