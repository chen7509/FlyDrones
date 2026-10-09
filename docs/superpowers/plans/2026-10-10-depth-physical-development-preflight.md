# Raw-depth physical development preflight implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Produce one immutable, runnable unarmed development study with exact raw-depth capture enabled and the prior physical load unchanged.

**Architecture:** Reuse the qualified source-study loader, runtime binding snapshot and one-attempt executor. A small new preparer emits the binding, execution contract and manifest into an exclusive destination; it never launches the simulator. A later resource check and separate execution produce physical evidence.

**Tech Stack:** Python 3.12, existing PX4/Gazebo/OpenVINS harness, `pytest`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-10-10-depth-physical-development-preflight.md`.

## Global constraints

Single new development seed and destination; no held-out scenario, training or simulator launch during preparation. Preserve 25 s / 1 ms / 250 Hz / 10 Hz 160×120, source health, safety limits, unarmed state and all original failures. The only new capture option is `record_depth_payload=true`; the existing health-enabled estimator/profile and fresh seed also differ from the qualified source study, so a lone run cannot measure the depth option's causal performance impact. Preexisting outputs and source drift are refused. Host memory and competing process status must be rechecked independently at dispatch.

## Review focus

Source audit is attached to the wrong study or source contract has changed; binding snapshot silently uses stale code or an arbitrary script/interpreter; an option fails to reach the worker; a partial destination is overwritten; preparation or tests accidentally start physical processes.

---

### Task 1: Prospective single-run declaration

**Files:** Create `tools/benchmark/prepare_depth_physical_development.py`; test in `tests/benchmark/test_prepare_depth_physical_development.py`.

- [x] Write failing tests for source qualification, exact unchanged workload, depth flag in both contract and declared command, fresh destination, retained partial failure and no launch.
- [x] Implement `prepare(...)` using the existing fixed source loader, runtime snapshot and manifest writers. Bind the updated capture/writer/fan-out sources, the old physical audit and a new seed.
- [x] Run focused tests and adjacent physical-preflight/executor tests. Verify no simulator process was started.

### Task 2: Independent review and publication

- [x] Run changed-file Ruff and `git diff --check`; independently review the source, declaration and limits.
- [x] Seal source/spec/plan/RED-GREEN/test output in a SHA/CRC-checked archive, report verified/only prepared/unrun/failed status, commit and push only `personal` to draft PR65.
- [x] Do not dispatch while host memory is below the frozen reserve or any competing run exists. A later real attempt needs its own resource snapshot and must preserve all failures.
