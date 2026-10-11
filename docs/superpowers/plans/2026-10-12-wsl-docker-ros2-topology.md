# WSL–Docker ROS 2 topology diagnostic plan

1. Inspect the pinned collector, Agent capture path, PX4 XRCE topic/transport configuration, Docker image, running resources and host memory.
2. Run two isolated, bounded UDP probes on port 18889. Retain exact results, including a loopback timeout. Verify owned container and listener release.
3. Audit the records without treating `sendto` success as delivery. State exactly which connectivity claim is supported and which DDS/PX4 claims remain open.
4. Seal script and result with member hashes, run the audit, update the stage report, and leave the frozen v12 physical study untouched.
