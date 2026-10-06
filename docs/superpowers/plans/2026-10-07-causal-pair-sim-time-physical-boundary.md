# Causal-pair simulation-time physical boundary plan

- [x] Add RED tests for exact-head, archive, live package/startup audit, immutable destination, execution contract, resource and overclaim failures.
- [x] Implement the boundary builder and independent auditor; run focused tests and changed-file lint.
- [x] Commit the boundary implementation, then generate and audit an exact-head boundary with `study-v18/capture-v1` still absent and resources empty.
- [x] Dispatch the declared physical command exactly once, retain all output and failures, and verify resources are released.
- [ ] Audit the physical result without rerunning it, update the stage report, run regression tests and seal immutable evidence.
