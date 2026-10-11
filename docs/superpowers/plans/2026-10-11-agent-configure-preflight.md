# Agent configure preflight plan

**Spec:** [Fixed XRCE Agent configure preflight](../specs/2026-10-11-agent-configure-preflight-design.md)

- [x] Confirm no competing PX4/Gazebo/Agent/learning job and sufficient host memory for configuration.
- [x] Save exact source hashes, tool versions, search paths, configure command and exit in a fresh result directory. The first wrapper lost its exit variable; the direct verification rerun returned exit 0.
- [x] Configure without building or fetching; preserve the first wrapper error and successful direct verification.
- [x] Independently inspect CMake cache, generated Ninja/ExternalProject metadata and pre/post source hashes. State which nested choices remain unobserved.
- [x] Write a bounded report, run checks, seal evidence, commit and update draft PR65 using only the `personal` remote.
