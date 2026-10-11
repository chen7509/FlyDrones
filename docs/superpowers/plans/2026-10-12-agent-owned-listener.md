# Agent-only listener diagnosis plan

**Spec:** [bounded owned listener](../specs/2026-10-12-agent-owned-listener-design.md)

- [x] Add strict parser tests for `ss` owner/port rows and reject mismatches.
- [x] Add bounded Agent-only harness using sealed bundle, fresh output and owned group cleanup.
- [x] Check idle port/resources; retain the first parser failure and one new corrected listener diagnosis.
- [x] Independently audit result and source hashes; run targeted regression, Ruff and diff-check.
- [x] Seal report/evidence, commit and push only `personal`; update PR65 without claiming DDS/PX4 integration.
