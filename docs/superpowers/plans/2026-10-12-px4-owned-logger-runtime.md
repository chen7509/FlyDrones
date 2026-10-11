# Owned logger runtime implementation plan

**Spec:** [Owned PX4 diagnostic logger staging](../specs/2026-10-12-px4-owned-logger-runtime-design.md)

- [x] Test missing module and exact byte-bound staging, source tampering, existing/linked target, and post-run mutation refusal before implementation.
- [x] Add an opt-in, declared diagnostic profile to the capture contract and worker command. Require owned Agent wire mode, leave the old command unchanged, and keep runtime/source qualification false.
- [x] Copy the fixed file exclusively into the newly owned PX4 runtime, pass only its `SDLOG_PROFILE=0` environment override to the PX4 child, require source files in the runtime inventory, and register a post-PX4 integrity check.
- [x] Run targeted and adjacent regression, changed-file lint, and independent review; report what cannot be tested without an eligible physical episode.
- [ ] In a separately named future study, extend the strict live-wire manifest to bind this changed-load option and copy, with actual logger topic/ULog/Agent/ROS source evidence. Do not amend sealed v12 or infer qualification from this implementation.
