# Agent Linux package inventory design

## Purpose

Record the actual, currently available Ubuntu WSL2 toolchain and package candidates before any Micro XRCE-DDS Agent v2.4.3 configuration or build. The fixed Agent/Fast-DDS source-object audits establish identities, not selected compiled dependencies. This stage is read-only and cannot qualify an Agent executable, PX4 handshake, DDS output, or EKF2 fusion.

## Input and method

Use the already-running Ubuntu distribution. Capture the command, exit status and raw output for OS/kernel, CMake/Ninja/compiler, installed relevant Debian packages, executable discovery, CMake package files, linker cache and memory. Record host free physical memory and whether a competing container or simulation/training process is running. Do not install packages, create a container, run CMake configure, compile, or launch PX4/Gazebo. Keep WSL localhost warnings as an observed environmental artifact rather than interpreting them as package failures.

Read the fixed Agent `SuperBuild.cmake` and Fast-DDS `eprosima_libraries.cmake` selection conditions. Treat an installed package or source gitlink as a *candidate* only: actual selection requires a future frozen CMake cache/build and resolved runtime libraries. Do not infer the Docker image's package inventory from WSL.

## Result and exit condition

Seal the capture script, raw JSON, a concise interpreted report and a per-member hash list. Independently check that report package claims match the captured output and that source-selection claims match the pinned CMake files. An absent package or low host memory is a documented blocker for the chosen path, not a failure of the fruit-fly policy. Preserve earlier failures and do not change any physics or evaluation threshold.
