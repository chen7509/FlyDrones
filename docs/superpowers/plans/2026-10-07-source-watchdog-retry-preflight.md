# Source-watchdog retry preflight plan

- [x] Add RED tests for wrong immutable failure evidence, archive/member/script drift, workload drift, positive claims, active resources and an existing destination.
- [x] Implement the minimal prepare-only builder and independent auditor while preserving all workload, timeout and safety fields.
- [ ] Run focused and full regression tests, commit the implementation, then generate and audit a fresh package without invoking its physical command.
- [ ] Run at most one startup-only preflight after the committed package audit; retain all failures and do not start a physical retry.
