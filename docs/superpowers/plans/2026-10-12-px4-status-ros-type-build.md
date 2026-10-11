# Bounded PX4 status ROS type build plan

**Goal:** Generate the pinned `EstimatorStatus` ROS type from the derived
source tree with a bounded, one-shot build and exact provenance evidence.

**Spec:** [design](../specs/2026-10-12-px4-status-ros-type-build-design.md)

1. [x] Confirm source/profile/image pins, Docker daemon and resource state;
   preserve the prior full-state success and all older build failures.
2. [x] Write failing tests for source/profile and owned-output preflight,
   Docker competitor/daemon checks, timeout/cleanup accounting, and status
   generated-type success criteria. Include a valid synthetic control.
3. [x] Implement `tools/connectome/run_status_ros_type_build.py` as a new
   one-shot runner without changing the legacy runner or overlay source.
   Make every refusal write an explicit result and never silently resume.
4. [x] Run focused and adjacent regressions, lint and independent review;
   fix concrete findings with RED/GREEN and retain failures.
5. [x] If the unchanged 900,000 KiB offline-build preflight and no-competition
   checks pass, perform exactly one declared Docker build. Preserve all
   logs, generated file hashes, exit and daemon cleanup; otherwise report
   the preflight refusal and continue independent work.
6. [x] Audit result without upgrading firmware/live-source/training claims
   and seal evidence with member hashes/CRC.
7. [ ] Commit, push only to `personal`, update PR65 and the continuing
   automation.
