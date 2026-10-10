# PX4-compatible XRCE Agent: source readiness

This is a source-provenance investigation, not an Agent build or a PX4/DDS trial. The prior [odometry source diagnostic](PX4_ODOMETRY_SOURCE_DIAGNOSTIC_REPORT.md) remains offline; its typed DDS/CDR parity and owned PX4 publisher identity are still unverified. No Agent, PX4, Gazebo, OpenVINS, trainer, or container was started for this investigation.

## Selection and source evidence

[PX4 v1.17 uXRCE-DDS guidance](https://docs.px4.io/v1.17/en/middleware/uxrce_dds) identifies eProsima Micro XRCE-DDS Agent **v2.4.3** for its v2 client and warns that Agent v3 is incompatible. The [Agent release](https://github.com/eProsima/Micro-XRCE-DDS-Agent/releases/tag/v2.4.3) is dated 2024-03-20. A clean, shallow checkout of that tag was resolved to commit `73622810d984349b80bbac0ef55fc0b694d62222`, tree `30de05fce045d2cc40c3b911f4dc5085b24f1ab4`, with 213 tracked files. The selected `CMakeLists.txt`, `cmake/SuperBuild.cmake`, `Dockerfile`, README, and Apache-2.0 LICENSE are individually SHA-256-bound in `source-provenance.json`. The repository's present maintenance pace and any downstream installed patches were not established. The checkout is retained at `results/px4-agent-v243-source-dev-1701/upstream` and was not modified.

The default `UAGENT_SUPERBUILD=ON` path in the pinned `SuperBuild.cmake` requests the **moving** `Fast-CDR` branch `2.2.x` and `Fast-DDS` branch `2.14.x`. At the recorded UTC observation they resolved to `757d5e422253568c487ad97c22e44680fc1ddbaf` and `575d045b55c16be1074ccd9eebf95e3e4274fe61`, respectively. These observations do not freeze a later build. The same file requests `foonathan/memory v0.7-3`, `spdlog v1.9.2`, and optional XRCE Client `v2.4.3`; their observed Git objects are recorded, but tag-object versus peeled-commit identity and actual build compatibility still require verification. The upstream Dockerfile also starts from an unpinned Ubuntu image and invokes unbounded `make -j $(nproc)`. Therefore neither the default superbuild nor that Dockerfile is a qualified reproducible, resource-bounded binary recipe.

| Dependency | Observed ref/object | Source license | Role and remaining check |
| --- | --- | --- | --- |
| [Fast-CDR](https://github.com/eProsima/Fast-CDR/blob/757d5e422253568c487ad97c22e44680fc1ddbaf/LICENSE) | `2.2.x` / `757d5e4` | Apache-2.0 | Serialization dependency; pin commit and build-test. |
| [Fast-DDS](https://github.com/eProsima/Fast-DDS/blob/575d045b55c16be1074ccd9eebf95e3e4274fe61/LICENSE) | `2.14.x` / `575d045` | Apache-2.0 | DDS transport; pin commit and build-test. |
| [foonathan/memory](https://github.com/foonathan/memory/blob/0f0775770fd1c506fa9c5ad566bd6ba59659db66/LICENSE) | `v0.7-3` / `0f07757` | zlib-style | Fast-DDS dependency; verify peeled commit and compiled selection. |
| [spdlog](https://github.com/gabime/spdlog/blob/eb3220622e73a4889eee355ffa37972b3cac3df5/LICENSE) | `v1.9.2` / `eb32206` | MIT | Logging dependency; verify peeled commit and compiled selection. |
| [XRCE Client](https://github.com/eProsima/Micro-XRCE-DDS-Client/blob/d44dc3fa0c488376e34d26ed92853f1c66dcb670/LICENSE) | `v2.4.3` / `d44dc3f` | Apache-2.0 | Optional superbuild dependency; verify whether this Agent configuration needs it. |

The Agent's required interface for this project is an owned v2-compatible XRCE transport and typed DDS output for PX4 v1.17; a successful source checkout says nothing about process identity, clock correlation, message provenance, throughput or EKF2 fusion. The available WSL installation has CMake and Ninja, but no installed `MicroXRCEAgent`, Fast-DDS/CDR packages, or `colcon`. Fetching and compiling the transitive tree costs network, disk, CPU and memory; this stage measured none of them. Choosing the upstream release minimizes API adaptation relative to a namesake replacement, while explicit dependency pinning and a bounded build are still needed.

## Validation and next gate

`capture_source_provenance.py` verified the exact clean checkout and branch declarations, queried the refs, counted tracked files, and hashed selected source files. `source-provenance.json` SHA-256 is `89e2028a1669bdefe856291fa47523b382bd07c6d1115fdeaf8253d8b57ba7d4`. A separate read rehashed both CMake files against that manifest. The evidence archive contains the script, manifest, console output, report, selected upstream files, and per-member SHA-256/CRC32. These checks verify **source identity and a reproducibility defect**, not a binary or interoperability.

Before a physical source trial, freeze exact commits and source archives for every selected dependency, record compiler/options/linked libraries and a bounded build budget, then validate the resulting Agent executable against the fixed PX4 client in an isolated unarmed setup. The generated-type synthetic DDS/CDR callback test is a separate prerequisite. Do not install the diagnostic logger file, publish ODOMETRY, alter EKF2 parameters, or claim typed ROS parity merely because this checkout succeeded. Existing low-memory synthetic attempts and the historical zero-odometry ULogs retain their failed/unverified status.

| Item | Status |
| --- | --- |
| Agent v2.4.3 source identity and default dependency refs | Verified for the recorded checkout/time. |
| Exact transitive dependency source set and reproducible bounded build | Not implemented or tested. |
| Agent executable, PX4 v2-client handshake, DDS callback/CDR parity | Not tested. |
| Owned publisher attribution, logger selection, EKF2 acceptance | Not tested. |
| VIO fusion, training, swarm capacity or flight | Not established by this stage. |
