# Read-only listener transport implementation plan

Execution: superpowers:executing-plans inline in existing worktree.
Spec: ../specs/2026-10-08-readonly-listener-transport-design.md
Goal: actual bounded protocol I/O on same verified connection, ordinary fixtures.
Stack: Python3.12/Linux socket, existing peer/snapshot/multi decoders.

## Task1: framing and poll adapter

Files: tools/benchmark/openvins_listener_transport.py;
tests/benchmark/test_openvins_listener_transport.py.

- [x] Retain source-derived protocol/selected API research and reuse reasons.
- [x] Write failing command/envelope/adapter tests including native fixture bytes.
- [x] Implement strict allowlist, bounded envelope and nonblocking poll; retain
      partial I/O and all refusal/close evidence. No live authority.
- [x] Run focused regressions/Ruff/diff; commit implementation/tests.

## Task2: ordinary protocol fixture, review and publication

File: tests/benchmark/check_openvins_listener_transport.py.

- [x] Freeze then run one private-server normal/fault matrix, exact commands and
      native fixture membership/hashes, no real PX4 or MAVLink.
- [x] Independent review and RED/GREEN repairs; full regression.
- [x] Update report with actual versus synthetic/final-hardening boundaries;
      seal new ZIP/hash/CRC without overwriting old evidence.
- [ ] Commit/push personal, update draft PR65; retain full goal and live gates.
