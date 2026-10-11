# Owned Agent capture integration plan

**Spec:** [owned Agent capture](../specs/2026-10-12-owned-agent-capture-design.md)

- [x] Add RED/GREEN prospective runtime declaration and fixed binary/library identity tests.
- [x] Bind opt-in Agent files into capture execution contract and pre-runtime inventory.
- [x] Add bounded owned Agent launch, PID/UDP proof, liveness and cleanup to the existing capture path; test normal/failure ordering.
- [x] Run adjacent regression, Ruff and diff-check; independently review old-profile behavior and failure retention.
- [ ] Seal report/evidence, push only `personal` and update PR65. Physical PX4/DDS remains unverified until a separately frozen eligible run.
