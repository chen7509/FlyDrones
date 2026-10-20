# Fixed Agent Humble rebuild plan

1. Recheck memory, Docker/WSL processes, source/bundle hashes and an empty output path. Record the pinned image, compiler, glibc and required system headers. Refuse without launch when host free memory is below the separate 2 GiB offline-build preflight or any input changes; retain the refusal.
2. Mount the fixed source and nine local Git stores read-only; configure an out-of-source, network-disabled, single-job build in a new bounded container. Record configure/build logs, resource limits and all failures. Do not reuse WSL binaries.
3. If build succeeds, audit fixed commits and selected library paths, source pre/post hashes, binary/library hashes, ELF GLIBC requirements and actual image loader resolution. Run bounded Agent usage/listener lifecycle without PX4 or ROS 2.
4. Run targeted refusal/cleanup checks and independent evidence review; seal hashes and report what is verified versus still untested. Continue to an XRCE-created DDS interface test only after the ABI and owned-runtime gate passes.
