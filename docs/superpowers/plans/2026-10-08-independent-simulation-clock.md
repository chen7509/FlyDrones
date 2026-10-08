# Independent simulation clock implementation plan

> Use superpowers:executing-plans inline, TDD, and one independent final review.

**Goal:** Preserve independent simulation sample/arrival/journal clocks for future PX4 composition.
**Architecture:** Serialized writer, committed immutable observations, concurrent reader of previous committed state, no transport factory.
**Tech Stack:** Python3.12 stdlib; current Gazebo UpdateInfo shape; no new dependency.
**Spec:** docs/superpowers/specs/2026-10-08-independent-simulation-clock-design.md

## Global constraints
- Offline only, no physics/UDP/PX4/ODOMETRY/new training; all qualification flags false.
- Exact zero-origin25s,1ms steps,25000samples,2s freshness; no bootstrap8s/500 relaxation.
- Preserve all historical evidence and failures; publish only personal PR65.

## Review focus
- An old callback cannot become fresh when journal finally returns.
- Pending/partially journaled observation cannot be selected.
- Reader before later failure is not a retrospective safety guarantee.
- Concurrent writer and callback reentry cannot publish after fault.
- Request timestamp must not select or manufacture simulation time.

### Task 1: Journaled callback lane and evidence
Files: tools/benchmark/openvins_simulation_clock.py; tests/benchmark/test_openvins_simulation_clock.py.
Interfaces: JournaledSimulationClock.post_update(info, ecm=None), snapshot(received_ns), check(), evidence; frozen ClockObservation and ClockSelection.
- [x] Add normal/failure tests and record initial RED.
- [x] Implement the spec and pass targeted tests, including actual RemoteMonotonicClock composition.
- [x] Independent read-only review; one necessary Critical/Important fix pass with counterexamples.
- [x] Run targeted dependency regressions and changed Ruff/diff; broaden only for a demonstrated concern.
- [x] Save report/research/test/evidence hashes, commit and push personal; verify existing draft PR65.

Ruling: Existing user preapproval replaces repeated plan approval. This package does not hook the lane into a historical producer or repeat physical tests. Targeted verification is proportionate to an opt-in unconnected module; it is not a fresh whole-repository pass.
