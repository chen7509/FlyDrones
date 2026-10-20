# Pinned XRCE Agent: top-level CMake configure preflight

The fixed Micro XRCE-DDS Agent v2.4.3 `source-v4` tree configured in Ubuntu WSL with CMake 3.28.3, Ninja 1.11.1, GCC/G++ 13.3.0, `Release`, `UAGENT_SUPERBUILD=ON`, and tests disabled. This is **top-level configuration only**. It created no Agent executable and did not run or download any of the generated dependency targets. The fresh result is `results/agent-configure-preflight-dev-1701`; its cache, Ninja graph, generated clone scripts, raw stdout/stderr, toolchain inventory, source hashes, and audit are sealed in `evidence/agent-configure-preflight-dev-1701.zip` (88 members, SHA-256 `8c8058b29e2a32da233fdd0404130060c3f2942ac338433f38f9df456564ec45`). Every archived member passed ZIP CRC and per-member SHA-256 verification.

The CMake cache records `fastcdr_DIR`, `fastrtps_DIR`, `foonathan_memory_DIR`, `microxrcedds_client_DIR`, and `spdlog_DIR` as not found. The generated Ninja graph therefore has five external dependency targets: Fast-CDR, Fast-DDS, foonathan memory, Micro XRCE-DDS Client, and spdlog. Their generated clone scripts name the exact commits already audited in [PX4 Agent dependency objects](PX4_AGENT_DEPENDENCY_OBJECTS_REPORT.md). For each, both download and build stamps are absent. The Agent's `uagent` target depends on those external projects. The actual full build and link closure remain unverified.

The generated Fast-DDS cache arguments pass `THIRDPARTY=ON`, `COMPILE_TOOLS=OFF`, `SECURITY=OFF`, and `SHM_TRANSPORT_DEFAULT=OFF`. No nested Fast-DDS CMake configure ran, so its Asio, TinyXML2, Fast-CDR, Boost, or other package choice is **not** established. In particular, `THIRDPARTY=ON` can still select an installed package; the fixed [gitlink source audit](FAST_DDS_GITLINK_OBJECTS_REPORT.md) does not make those gitlinks the chosen runtime implementation. A later build also needs a frozen policy for downloading versus using the locally verified objects, especially because the generated `ExternalProject` scripts would otherwise clone repositories.

Before configuration, the Windows host reported 3,696,824 KiB free physical memory; WSL reported 6,856 MiB available inside its virtual machine. The selected Windows and WSL process scans found no competing PX4, Gazebo, OpenVINS, Agent build, or trainer. These are point-in-time readings, not a guarantee for a full compile. The source tree contained 214 files including its generated `source-profile.json`; the per-file SHA-256 list was identical before and after. No existing evidence or failure was overwritten.

The first bash wrapper failed to retain CMake's numeric exit code because its shell variable was lost, although stdout said configuration and generation completed. That error is preserved as an empty `configure.exit`. A direct no-build verification of the same cache returned process exit **0**, again reporting successful configuration; the independent audit requires the cache and graph plus all five fixed clone targets and absent download/build stamps. The trial was not used to infer an Agent build result.

| Gate | Result |
| --- | --- |
| Fixed source, top-level CMake options and five direct external targets | Verified in WSL configure output, cache and generated graph. |
| Source bytes stable across configuration | Verified for all 214 local files. |
| Nested Fast-DDS package selection, compiled binary and linked ABI | Not tested. |
| Owned PX4↔Agent↔DDS provenance, VIO→EKF2, training or flight | Not tested. |

The next dependency is a bounded offline build/configure recipe that binds the already verified Git objects and records Fast-DDS's actual nested CMake selections without silently using a different system package. Only then should a one-job Agent build be attempted under a fresh host-memory check. This preflight does not authorize ODOMETRY publication, EKF2 changes, arming, or using Gazebo truth as flight-state input.
