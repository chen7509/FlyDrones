# Owned daemon connection implementation plan

Execution: superpowers:executing-plans, inline in existing worktree.
Spec: ../specs/2026-10-08-owned-daemon-connection-design.md
Goal: bind the same command socket to an explicitly owned process before any bytes.
Stack: Python3.12/Linux proc/SO_PEERCRED; no installed dependencies.

## Task1: connection/identity gate

Files: tools/benchmark/owned_daemon_connection.py;
tests/benchmark/test_owned_daemon_connection.py.

- [x] Retain pinned PX4 and primary Linux/Python source/API research with license,
      version, maintenance boundary, reuse decision, resource/adaptation costs.
- [x] Write normal and counterexample tests; preserve initial failure type.
- [x] Implement observe_owner and connect_owned_daemon with strict schema,
      same-descriptor credentials, bounded connect, deadline/identity rechecks,
      journal-before-handover and failure close. Do not send bytes or unlink.
- [x] Run targeted adjacent identity/runtime/bootstrap tests and changed Ruff;
      commit implementation and tests.

## Task2: real kernel fixture, review and seal

File: tests/benchmark/check_owned_daemon_connection.py (explicit manual harness).

- [x] Freeze ordinary AF_UNIX fixture cases/source/runtime hash before execution;
      execute once, record peer credentials, zero application bytes and owned exit.
- [ ] Independently review; fix material findings with RED/GREEN; full pytest.
- [ ] Report verified/implemented/unverified/failures and remaining actual command
      transport binding. Seal new evidence with SHA/member hashes/CRC.
- [ ] Commit/push only personal and update draft PR65. Overall goal remains active.
