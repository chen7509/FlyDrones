# Isolated PX4 EstimatorStatus firmware build plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build one clean, fixed-commit PX4 SITL binary with exactly the frozen `EstimatorStatus` DDS topic addition, without launching a simulator or granting live source authority.

**Architecture:** A source-preparation verifier creates an isolated detached PX4 worktree and binds its commit, submodules, toolchain and single YAML patch. A one-shot, resource-gated build runner records command, output, generated header, binary and cleanup. A separate auditor seals the result and permanently leaves live/capture/training authority false.

**Tech Stack:** WSL2 Ubuntu, fixed PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, GNU Make/CMake/Ninja, Python 3.12/EmPy/PyYAML, FlyDrones Python/pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-px4-estimator-status-firmware-design.md`

## Global constraints

- Never modify or build from the existing dirty `~/PX4-Autopilot` working tree or its September binary.
- Use the external sibling WSL worktree `~/px4-status-worktrees/firmware-v1`; do not add `.worktrees` or change `.gitignore` in upstream PX4.
- Exact base YAML SHA-256 `7e9c730d45b22af92acfebbb81cb5de4e4a69ac0ca46b012b71ed8fa5c89cbc0`; candidate `783247c76b0af04519681d61546756522847590f0758a675154e12bd2d332e8c`.
- Exact generated header candidate SHA-256 `bef5afc679cb23ede466cd1ce22db270d3611492ab2326a1e41ce513cbe1c4fc`.
- Before build, require Windows host free physical memory at least 4 GiB, WSL available memory at least 4 GiB, destination disk at least 15 GiB, no active FlyDrones PX4/Gazebo/OpenVINS/training or unrelated heavy test; one build job, a 90-minute wall limit and a verified systemd user scope with `MemoryMax=4G` and `CPUQuota=100%`. A closed or unenforceable gate produces a read-only refusal, not a build attempt.
- The one-shot result path and worktree name must be declared before execution. Never overwrite or recursively clean a failed result. Record any changed profile under a new name.
- Build only; do not start PX4, Gazebo, Agent, `ODOMETRY`, EKF2 injection, arming, training or the physical study.

## Review focus

- An existing WSL checkout has a modified `VehicleIMU.cpp`; the isolated source must not inherit it.
- Missing or drifting submodule files must refuse rather than trigger unrecorded fetches.
- Generator output alone cannot qualify a firmware binary; verify the actual isolated build dependency and binary identity.
- A build command that launches a simulator must be rejected before dispatch.
- Timeout, low memory, partial log, process/child cleanup ambiguity or changed source must leave compilation qualification false while retaining evidence.

### Task 1: Isolated source and toolchain contract

**Files:** Add a focused verifier in `src/flydrones/connectome_training/px4_status_firmware.py`, tests in `tests/connectome_training/test_px4_status_firmware.py`, and a frozen profile under `configs/px4/`.

- [x] Read the fixed PX4 commit, candidate, submodule manifest and official build rule; specify the one supported isolated worktree and build-only command. The detached worktree, six declared submodules and candidate source now pass the source audit; the build remains pending.
- [x] Write failing tests for wrong commit, dirty inherited file, wrong YAML/namespace, missing submodule, path alias and reused result path.
- [x] Implement source preparation without changing the original checkout. Save before-build hashes and exact toolchain/submodule provenance; rerun focused tests. The six declared SITL submodules and candidate YAML are prepared in the detached worktree; build-discovered dependencies remain a separate fail-closed check.

### Task 2: Bounded one-shot build

**Files:** Add `tools/connectome/run_px4_status_firmware_build.py` and runner tests.

- [ ] Write failing admission tests for Windows/WSL/disk resource limits, competing processes, command mismatch, timeout and ambiguous owned cleanup.
- [ ] Implement a preflight that has no PX4 side effect until all checks pass. Preserve a refusal record if the current gate is closed.
- [x] Interim read-only admission: 20 tests pass for source, resource, command, process and scope refusals; a real snapshot refused at 3.039 GiB Windows memory. No build-dispatch path exists yet. Owned cleanup and the fresh scoped dispatch remain for the full runner.
- [ ] Once resources are truly available, dispatch exactly one build-only `px4_sitl_default` attempt at one job under the frozen wall limit. Record stdout/stderr, process identity, exit and maximum observed resources. If the build fails, retain the exact attempt and stop; do not relabel a repair as the same attempt.

### Task 3: Binary audit and publication

**Files:** Add a separate auditor, `docs/PX4_ESTIMATOR_STATUS_FIRMWARE_REPORT.md` and one-shot evidence archive.

- [ ] Require exit 0, no owned build process left, unchanged selected source/submodules, the pinned generated header hash, compiler/dependency identity and a new binary hash from the isolated tree. Report `firmware_compiled_verified` only for that exact evidence; keep all live/fusion/capture/training flags false.
- [ ] Run focused and adjacent regression, changed Ruff/diff checks and independent review. Seal hashes/CRC and all failed attempts; submit the report and code to draft PR65 using only `personal`.
- [ ] If build qualification passes, write a **separate** frozen unarmed live-receipt plan. Do not call a source-only or binary-only result live PX4 evidence.
