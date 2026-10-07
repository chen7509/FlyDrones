# Offline cold bootstrap implementation plan

Execution: superpowers:executing-plans, inline in existing linked worktree.
Spec: ../specs/2026-10-08-timesync-cold-bootstrap-design.md
Goal: preserve first-state association across the implicit snapshot and explicit
stream without counting a replay as a new synchronization sample.
Stack: Python; existing TimesyncListenerDecoder and SerialTimesyncObserver.

## Global constraints/review focus

No live PX4/Gazebo/estimator/network/parameter changes, arming or training.
8s readiness/2s watchdogs/500 accepted samples unchanged; outer study25s unchanged.
Do not infer actual PX4 identity from opaque epoch/listener tokens. Never count
the initial stream replay twice or reset the numerical filter at handoff.
Journal failure/reentry must prevent returning a new reply intent. Return no
live authority. Keep old capture/probe outputs unchanged and do not rerun them.

## Task1: snapshot framing and serialized handoff

Files: tools/benchmark/openvins_timesync_bootstrap.py;
tests/benchmark/test_openvins_timesync_bootstrap.py; tests/fixtures/timesync/.
Interfaces: parse_snapshot(raw, exit_code); ColdTimesyncBootstrap as specified,
including check(now_ns=..., epoch_token=...) and read-only events/progress copies.

- [x] Write failing snapshot and transition tests, including exact native implicit
      fixture, before implementing the module. Preserve the initial error type.
- [x] Implement strict parsing via the existing decoder and locked, journal-first
      transitions, serial observer and explicit multi framing.
- [x] Cover500-sample chain, counted-once replay,501 with rejected sample, clock,
      wrong identity/phase/field, extra bytes/count, clean exit, journal failure,
      callback mutation/reentry and partial deadline tests; run focused regressions.
- [x] Commit implementation and tests with evidence-linked fixture provenance.

## Task2: file-only audit and closeout

- [x] Run a named fixed-input normal/failure matrix using this state machine and
      a real exclusive JSONL journal; no socket/process/native replays.
- [x] Independent read-only review, material repairs RED/GREEN; full pytest with
      current-tree PYTHONPATH, changed Ruff and diff-check.
- [ ] Report implementation versus live proof, frozen source/fixture identities,
      failures and next actual process/transport binding; seal ZIP/hash/CRC.
- [ ] Update parent plan/PR65, commit/push only personal. Keep overall goal active.
