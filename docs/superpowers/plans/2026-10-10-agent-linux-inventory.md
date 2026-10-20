# Agent Linux inventory plan

**Spec:** [Agent Linux package inventory design](../specs/2026-10-10-agent-linux-inventory-design.md)

- [x] Check working tree, current processes, containers and memory before work.
- [x] Capture bounded read-only WSL package, toolchain, executable, CMake-config and linker inventories with command/exit evidence.
- [x] Compare package candidates with fixed Agent and Fast-DDS CMake selection rules; distinguish Ubuntu WSL from Docker.
- [x] Independently verify the raw capture and seal evidence; publish the limited report, commit/push to `personal` and update PR65.
