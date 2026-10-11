# DDS colocation feasibility plan

1. Check current containers, processes, memory, WSL route and pinned binary/image identity.
2. Run three bounded reverse UDP cases on port 18890: two Docker host-network destinations and one explicitly published bridge port. Keep all timeouts and exact listener output.
3. Inspect GLIBC requirements of the fixed Agent bundle and glibc provided by the pinned ROS 2 image. Audit route and ABI observations separately; leave DDS/XRCE/PX4 qualifications false.
4. Seal scripts, raw outputs and audit with file hashes/CRC; report the feasible deployment path and remaining source-authentication gates. Do not execute v12, change physical loads, or start a training/simulation process.
