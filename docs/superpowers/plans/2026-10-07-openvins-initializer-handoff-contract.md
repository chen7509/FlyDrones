# OpenVINS initializer-handoff acknowledgement contract plan

**Goal:** Accept the pinned synchronous OpenVINS handoff diagnostic without granting readiness or weakening malformed-state rejection.

**Spec:** `docs/superpowers/specs/2026-10-07-openvins-initializer-handoff-contract-design.md`

- [x] Preserve and cite the exact immutable `study-v13` acknowledgement and pinned upstream control flow.
- [x] Add a failing regression for a valid pending handoff plus malformed inverse cases.
- [x] Implement the narrow uninitialized acknowledgement alternatives without emitting readiness.
- [x] Run focused readiness and state-diagnostics tests, then justified regression/lint checks.
- [x] Independently audit the immutable physical attempt and classify the first refusal without rerunning it.
- [x] Update the stage report, seal evidence, commit, push and update the draft PR.
