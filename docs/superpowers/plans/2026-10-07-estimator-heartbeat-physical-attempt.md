# Estimator-heartbeat corrected physical attempt plan

**Goal:** Run and audit exactly one immutable physical development attempt from the sealed `study-v13` package.

**Spec:** `docs/superpowers/specs/2026-10-07-estimator-heartbeat-physical-attempt-design.md`

- [ ] Commit this execution boundary and re-audit `study-v13` from that committed head.
- [ ] Confirm the startup audit, package audit, exact destination, absent target/evidence files and empty active-resource scan.
- [ ] Record one dispatch and execute the declared production command exactly once at `study-v13/capture-v1`.
- [ ] Record completion and cleanup/resource evidence without retrying or overwriting the target.
- [ ] Independently audit the complete result, retain every failure and keep all unproven downstream claims false.
- [ ] Run focused/full regressions as justified, update the report/PR, seal evidence and set the next dependency.
