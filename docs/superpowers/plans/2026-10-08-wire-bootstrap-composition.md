# Wire bootstrap composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Use TDD; retain every failure.

**Goal:** Make byte responder and owned listener startup share one fail-closed completion result.
**Architecture:** Reuse actual OwnedBootstrap and TimesyncWireResponder, one clock and reservation callback; no filter rewrite or UDP backend.
**Tech Stack:** Python3.12.3, pymavlink2.4.49, WSL unittest/private AF_UNIX and pipes, Windows pytest.
**Spec:** docs/superpowers/specs/2026-10-08-wire-bootstrap-composition-design.md

## Global Constraints
- No PX4/Gazebo/OpenVINS/UDP/ODOMETRY/parameter or stream change, arming or training.
- Original8s/2s/500 gates, selected-source hashes, no skipped failure/overwrite.
- Use personal remote and existing draftPR65; no task/worktree creation.

## Review Focus
- Failure after a sink returns must suppress outer completion while retaining returned bytes.
- Reentrant journal callback must not lead to an actual subsequent sink write.
- Inner bootstrap completion alone cannot bypass wire state or send count.
- Idle checks must enforce deadlines without opening a new listener or consuming bytes.
- Private fixture must decode real reply bytes before emitting matching modeled status.

### Task 1: Receive clocks and non-consuming health checks
**Files:** tools/benchmark/openvins_timesync_wire.py, openvins_owned_bootstrap.py; corresponding tests.
**Interfaces:** consumes existing failure latches; produces wire.check(), owned.check(), nondecreasingreceived_ns.
- [x] Add receive-regression/tie and check-without-I/O/deadline tests; run them RED.
- [x] Implement preserving current evidence, gates and counters; run relevant WSLunittest and Windowspytest GREEN.
- [x] Commit explicit paths.

### Task 2: Composed production gate and actual byte fixture
**Files:** tools/benchmark/openvins_wire_bootstrap.py; tests/benchmark/test_openvins_wire_bootstrap.py; tests/benchmark/check_openvins_wire_bootstrap.py.
**Interfaces:** consumes Task1 check methods and actualreserve callback; produces OwnedWireBootstrap poll/receive/progress/evidence/close.
- [x] Write real-codec WSL unit cases for every spec invariant; Expected: feature missing then behavioral RED where applicable.
- [x] Implement and pass cases without permissive fake reserve or liveauthority.
- [x] Build one explicit four-case process harness with fixed cases/expected outcomes and real child byte decode; compile/lint before execution, no blind reruns.
- [x] Independent read-only review; fix Important/Critical once with RED→GREEN.
- [x] Freeze producer/source/dependency hashes and execute new matrix once; Expected:500 matched synthetic responses only in normal case, named faults refuse, all direct-owned children terminate with expected status and retained logs.
- [x] Full Windows regression and WSL targeted suite, changedRuff/diff; Expected: passes with explicit platform skips.
- [ ] Report/archive/hash/CRC, commit/push personal, update/verify/attach PR65.

## Execution ledger
Pre-flight: Task1 adds pure checks consumed by Task2; check must not call poll or reset deadlines. Actualreserve returns false-authority intent dict. Fixture uses rawbytes through pipe, not UDP.
Ruling: existing userpreapproval covers plan execution; no repeated approval prompt. Preserve results and workspace even after publication.
