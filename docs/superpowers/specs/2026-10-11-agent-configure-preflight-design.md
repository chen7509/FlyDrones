# Fixed XRCE Agent configure preflight

## Purpose

Determine what the pinned Micro XRCE-DDS Agent v2.4.3 superbuild selects at its **top-level CMake configure** in the existing Ubuntu WSL environment. Source-object and package inventories already exist; this stage must not relabel them as a built Agent or a working PX4 DDS path.

## Frozen inputs and limits

- Use the existing `source-v4` tree and its recorded source-profile digest. Do not edit its CMake files or resolve any dependency from a moving branch.
- Use Ubuntu WSL, Ninja, CMake, GCC/G++, `Release`, the source's default enabled profiles, and tests disabled. Record exact command, tool versions, environment search paths, source hashes before/after, stdout/stderr, exit code, CMake cache, generated dependency graph and available ExternalProject metadata.
- Configure only. Do not invoke `cmake --build`, launch PX4/Gazebo/OpenVINS, or fetch dependencies. A configure failure is retained as a failed experiment.
- Report explicit top-level `find_package`/ExternalProject decisions. A nested Fast-DDS configuration and actual runtime library selection remain unknown until their own build/configure phases. In particular, `THIRDPARTY=ON` does not prove that pinned gitlinks are selected.
- Keep the result in a newly named directory. Do not overwrite existing evidence. Check processes and host memory before running.

## Acceptance

The configure command and exit are reproducible; input source hashes match before/after; a successful cache and generated graph identify top-level choices. A report must separate observed selection, source-based predictions, and not-yet-executed dependency builds. This stage does not qualify DDS provenance, ODOMETRY publication, EKF2 fusion, training, or flight.
