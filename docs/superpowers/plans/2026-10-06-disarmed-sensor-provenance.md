# Disarmed sensor provenance implementation plan

Use superpowers:executing-plans inline. Spec: docs/superpowers/specs/2026-10-06-disarmed-sensor-provenance-design.md. Base1276201, existing isolated worktree. User requires evidence retained, not workspace deletion.

### Task 1: Capture and compare live sensor provenance

Interfaces: Gazebo sensor callbacks → strict bounded file recorder; read-only MAVLink heartbeat and copied PX4 ULog → provenance audit. No VIO state or command producer.

- [x] Record pinned source/build/model hashes, candidate maintenance/licenses/resources and source selection.
- [x] Write failing tests, implement reusable recorder/audit and standalone disarmed capture. Preserve raw values; do not use armed NativeGazeboPx4Backend.start.
- [x] Validate development fixture hash, process/port availability and exclusive outputs. Run one25s simulated physical capture; retain failures and compare actual sensor/ULog evidence without retiming.
- [x] Run targeted/full regression, independent review and fix important findings RED→GREEN. Distinguish sensor-only capture from online OpenVINS and fusion.
- [x] Seal evidence/report, draft PR and continuation state.

Review Focus: accidental arm/setpoint/pose truth path; sample versus arrival time confusion; queue loss or hidden dropped frames; source timestamp replacement/integration/calibration mismatch; resource ownership and output overwrite; false equivalence or claims of online VIO; unchanged physical/camera load.
