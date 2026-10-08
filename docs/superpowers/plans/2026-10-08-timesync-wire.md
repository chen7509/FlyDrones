# TIMESYNC wire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Follow TDD and retain evidence.

**Goal:** Connect real pymavlink request bytes to a bounded, fail-closed reply attempt and honest send accounting.
**Architecture:** Pinned installed codec plus serial adapter, independent remote clock, existing reservation coordinator and injected sink. No network backend.
**Tech Stack:** Python3.12, pymavlink2.4.49, unittest in WSL; pytest for adjacent Windows regressions.
**Spec:** docs/superpowers/specs/2026-10-08-timesync-wire-design.md

## Global Constraints

- No PX4/Gazebo/OpenVINS launch or network packets/parameter/stream mutation.
- Global8s/request2s inclusive budgets;4096-byte/64-frame datagram,8192 events.
- Pinned schema/source; unsigned complete datagram profile; all authority false.
- Preserve failures; push only personal, update existing draft PR65.

## Review Focus

- Bad final frame must prevent an earlier valid request from causing a send.
- Callback reentry/failure must not escape a latched refusal.
- Failed/late sink result must preserve possible side effects without delivery claims.
- Public mutable clock session/CRC configuration cannot silently invalidate the profile.
- Header sequence wrap must not admit reused request timestamps.

### Task 1: Real codec and bounded responder

**Files:** create tools/benchmark/openvins_timesync_wire.py and tests/benchmark/test_openvins_timesync_wire.py.
**Interfaces:** consumes RemoteMonotonicClock.respond_to_px4_request and callback reserve_reply(request_ns,response_ns) returning existing false-authority intent; produces PinnedCodec and TimesyncWireResponder.receive/evidence.

- [x] Write stdlib unittest tests against actual WSL installed pymavlink; first verify missing feature, not a dependency failure. Include all Review Focus boundaries.
- [x] Run `wsl -d Ubuntu --cd <worktree> python3 -m unittest tests.benchmark.test_openvins_timesync_wire -v`; Expected: missing feature failure initially, then all cases pass after implementation. Record import-stage failure accurately.
- [x] Implement the spec with bounded evidence and no socket surface.
- [x] Run Windows adjacent observer/bootstrap/owned-bootstrap pytest and changed Ruff/diff-check; Expected: all pass. WSL actual-codec suite remains separate from Windows skip.
- [x] Commit explicit code/tests/spec/plan paths.

### Task 2: Review, evidence and publication

**Files:** docs/OPENVINS_TIMESYNC_WIRE_REPORT.md; evidence/openvins-timesync-wire-dev-1701.zip and SHA/verification; existing research results.
**Interfaces:** consumes Task1 suite outputs, unchanged historical codec probe and pinned research; produces bounded stage report, archive and next dependency note.

- [x] Independent read-only review of current stage. Fix Important/Critical findings once with behavioral RED→GREEN and regressions.
- [x] Run full Windows pytest once after final changes; Expected: pass with existing skips plus explicit missing-codec skip. Do not claim it replaces WSL codec tests.
- [x] Seal all selected research/test evidence with member hashes/CRC, no old archive overwrite; accurately separate historical probe from final code.
- [x] Commit/push personal and update/attach draft PR65; verify remote head and body.

## Execution ledger

Pre-flight: Task1 produces code/tests consumed by Task2 report/archive; installed codec probe is research only, not final adapter proof.
Ruling: use stdlib unittest in WSL because installed pymavlink exists there but pytest does not; no dependency install. Windows pytest skip is reported separately; cost if wrong is missing Linux test collection, prevented by explicit unittest run.
Ruling: preserve plan workspace and all evidence despite generic cleanup advice, per user's explicit preservation instruction.

Task1 completed789b78e..dacad9e: finalWSL42passed and eight selected file hashes
unchanged; Windowsadjacent141passed/1skip, full3193passed/4skip/2existing warnings.
Task2 evidence54members sealed52dc2f8e459f08d208f5d605c6d3de4b38514562160ab82cef0a9417651c3944.
PR65 head6c2b3f5 and exactbody/draft verified after push to personal; artifact
attached. No actualPX4/UDP/fusion authority. Receivedtimestamp monotonicity is
one deferredMinor, documented explicitly in report and next dependency note.
