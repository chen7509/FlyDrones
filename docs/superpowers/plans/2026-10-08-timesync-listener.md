# TIMESYNC listener boundary implementation plan

> Use superpowers:executing-plans inline.

**Goal:** Convert pinned non-PTY listener bytes into strict serial observer inputs.
**Architecture:** Bounded incremental decoder, reused observer, separate synthetic
daemon-client buffering probe; no live launcher or network authority.
**Tech stack:** Python stdlib/pytest; installed C++/coreutils for offline probe.
**Spec:** `docs/superpowers/specs/2026-10-08-timesync-listener-design.md`.

## Constraints and review focus

No PX4/physics/ODOMETRY; private synthetic AF_UNIX only for native client test.
Message widths/order fixed; raw output cannot be sanitized into a valid frame.
Readiness8s/total25s unchanged; decoder first/complete-frame silence2s.
Partial data must not keep a blocked source healthy.
Do not let exit0 hide listener diagnostics or truncated frames.
Do not count consuming lines as observing uORB generations.
Native stub source/method boundary and installed-client limitations explicit.

## Task 1: Source/probe and decoder

- [x] Probe unchanged fixed daemon client with isolated socket, retain default
  buffer failure, unbuffered result, trailer/EOF outcomes and hashes.
- [x] Write failing tests in `tests/benchmark/test_openvins_timesync_listener.py`.
- [x] Implement `tools/benchmark/openvins_timesync_listener.py` per spec.
- [x] Run focused suite and observer integration over actual fixture byte captures:
  409 cases passed; four captures retain requested count2 and all incomplete
  streams refuse. First unbuffered complete frame matches numerical observer.

## Task 2: Review and seal

- [x] Independent bounded review; fix important findings with retained RED/GREEN:
  trailing non-LF bytes after expected count,2 behavioral cases corrected.
- [x] Full current-tree pytest:2440 passed/3 skipped/2 existing warnings in329.64s;
  changed Ruff and diff checks passed.
- [x] Report in `docs/OPENVINS_TIMESYNC_LISTENER_REPORT.md`, archive member hashes/CRC:
  72 members/142944bytes, SHA256
  `999eef9ccca35343fcec547a6e0fbefe70401221846eadc62bc9cd2dbae3dc40`.
- [x] Commit/push personal, update PR65; retain remaining live gates explicitly.
  Implementation/seal `3163044`; these publication marks are recorded afterward
  and do not alter the archive's pre-publication plan snapshot.
