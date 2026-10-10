# Opt-in depth payload provenance plan

**Spec:** `docs/superpowers/specs/2026-10-10-depth-payload-provenance-design.md`.

1. [x] Write RED tests for execution declaration/worker forwarding, disabled legacy bytes, and opt-in depth callback format/size refusal. Implement only the new declared option and callback copy.
2. [x] Write RED tests for exclusive depth sidecar write, event identity, finish manifest, partial I/O failure and independent verifier. Implement bounded writer and verifier. Keep all old event/source semantics when disabled.
3. [x] Write RED tests for fan-out file/hash verification, tamper/path escape and no depth bytes delivered to native OpenVINS. Implement the opt-in audit path without changing the estimator input.
4. [x] Run focused and adjacent regression, Ruff and diff check, then independently review. Seal source, plan, failures and verification with member hashes/CRC; report actual scope, commit and push only `personal` to draft PR65. Do not run PX4/Gazebo, EGO or training in this stage.

The current worktree is already isolated. Any future physical study requires its own frozen profile and untouched destination; this plan prepares bytes only.

The evidence archive preserves the plan snapshot taken immediately before publication, with item 4 still open; this checkbox records the subsequently verified commit, push and PR update. The archived snapshot is not rewritten.
