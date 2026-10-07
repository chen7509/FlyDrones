# Serial TIMESYNC Observer Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` inline, with TDD and
> one independent final review. No live PX4, listener or network execution.

**Goal:** Validate a serial request/status matching contract needed by the
receiver startup gate while retaining false live/fusion qualification.

**Architecture:** A pure state machine reserves one reply, matches typed PX4
status to it and commits a cloned existing verifier only after parity checks.
It has no transport, subprocess, session reset or authority-granting interface.

**Tech Stack:** Python standard library, existing PX4 filter model, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-timesync-observer-design.md`

## Global constraints

- Pin PX4 d6f12ad, strict 500 accepted / RTT <10 ms filter; preserve all old evidence.
- Local pending deadline 2,000,000,000 ns, inclusive; fail closed on malformed input.
- Runtime assumptions are unproven; every live/fusion authorization flag stays false.
- No physical/estimator/network execution, stream changes or new dependencies.
- Push only personal on PR65 branch; only explicitly changed files are staged.

## Review focus

- Publication timestamp confused with receive time: reconstruct from request and RTT.
- Source enum 1 accepted despite pinned default 0: explicit refusal fixture.
- Missing status hidden by second reservation: overlap latches instead of replacing.
- Late/malformed record advances filter before validation: clone then commit.
- New companion object mistaken for reset PX4 filter: document cold-epoch premise.

## Task 1: Implement the pure serial observer

**Files:** Create `tools/benchmark/openvins_timesync_observer.py` and
`tests/benchmark/test_openvins_timesync_observer.py`; extend the existing
`tools/benchmark/openvins_ekf2_disarmed_preflight.py` with integer-us output and
the reviewed exact integer-division correction.

**Interfaces:** `SerialTimesyncObserver(session_id, topic_instance)`;
`reserve_reply(request_ns, response_ns, now_ns)`; `observe_status(status, now_ns)`;
`check(now_ns)`. Consume the existing `BoundedTimesyncVerifier` and
`TimesyncExchange`, do not duplicate filter math.

- [x] Write failing tests for first match (protocol0), 500 modeled acceptances,
  RTT exactly10000us rejected, publication time distinct from receive time and
  the complete fault matrix in the spec. Assert all authority fields false.
- [x] Run `python -m pytest tests/benchmark/test_openvins_timesync_observer.py -q`
  and preserve the missing-module RED separately from behavioral failures.
- [x] Implement exact keys/ranges, one pending identity, deadline/failure lock,
  cloned prediction parity and no in-place session reset.
- [x] Run the focused suite and existing preflight/receiver tests. Inspect all
  failures, Ruff and diff; commit only after final review corrections.

## Task 2: Review, regression and evidence

**Files:** Add `docs/OPENVINS_TIMESYNC_OBSERVER_REPORT.md`, sealed evidence and
update parent plan with the offline-only status.

- [x] Request independent bounded review of source assumptions and implementation.
- [x] Correct any important findings with retained RED/GREEN cases as applicable.
- [x] Run full pytest once after final implementation, changed Ruff and diff checks.
  Initial wrong-install-path collection failure preserved; explicit current-tree
  PYTHONPATH retry passed 2102/3 skipped. Final targeted checks:142 passed.
- [x] Seal source comparisons, test outputs and files; verify CRC/member hashes.
- [ ] Commit/push personal, update PR65. Leave all live Task4/5 gates incomplete.
