# PX4 startup phase gate implementation plan

Spec: `../specs/2026-10-10-px4-startup-phase-gate-design.md`. Execute inline in the current linked worktree under the user's standing authorization; no additional approval cycle. Freeze a new study only after code/tests pass. Never rerun v10.

## 1. Source-bound status parser (offline)

Files: new `tools/benchmark/px4_mavlink_startup_status.py`, `tests/benchmark/test_px4_mavlink_startup_status.py`; source evidence under `results/px4-startup-phase-gate-dev-1701/`.

- RED: exact multi-instance output with Onboard local/remote UDP pair; wrong port, wrong section, duplicate, missing fields, nonzero, oversized, malformed UTF-8, bool exit, and truncated output fail or remain explicitly pending as specified. No substring-only acceptance.
- GREEN: parser returns bounded source-derived section/port proof only. It has no filesystem, process, socket, fusion or readiness side effects.
- Recheck the pinned source SHA-256 and record compiler/installed runtime ambiguity; no fresh PX4 command is sent at this task.

## 2. Owned read-only startup probe and bounded phase state

Files: extend existing owned daemon transport with one fixed `mavlink status\0` command, or a narrowly separate read-only adapter if changing `ReadOnlyListener` would loosen its TIMESYNC-only allowlist; new tests. Implement a source-owned log observer and explicit startup phase with a finite spawn-anchored cap. No interval `get/set`, TIMESYNC listener or wire send before exact endpoint proof plus fresh successful startup marker. Retain raw exit/trailer/bytes, owner/peer, log identity/offset, each rejected/pending result and original time. Test partial send/recv, missing/late marker, peer change, command block, log truncation/replacement, time regression, source timeout and cleanup. No TTL silently extends.

## 3. Integrate clock callback without early cold-session construction

Files: `capture_wire_lifecycle.py`, `capture_disarmed_sensors.py`, relevant startup runner and tests. Register the immutable PostUpdate clock callback before `fixture.finalize()` while deferring `ObservedWireSession` creation until startup gate success. Preserve all startup simulation steps in the same 25 s episode and in the immutable clock journal. Verify the exact PX4 process, source watchdog, output paths, runtime binding and single socket. Once ready, begin the **unchanged** 8 s bootstrap and 2 s progress timers and keep the original first-empty snapshot, 500-accepted and baseline restoration requirements. Test failure before/after each boundary with fake fixture/owned ordinary process; do not let an already executing step evade the next pre-step failure latch.

## 4. Freeze and physical development attempt

Run targeted/adjacent tests, changed Ruff, diff check and independent code/evidence review. Document all remaining unknowns. New study ID must bind code/config, PX4/installed dependencies, startup phase cap, seeds, source/identity and unchanged 25 s/1 ms/250 Hz/10 Hz physical workload before launch. Check memory and running handles; launch once, unarmed, with independent observer and complete ULog/trajectory/failure retention. Audit startup, TIMESYNC, baseline restoration, source health, runtime mapping and process cleanup separately. If any gate fails, stop and preserve it; never use a later success to erase v10 or infer VIO/EKF2/fly-policy performance.

## 5. Closeout

Update stage report with verified/implemented/untested/failed status, seal per-file SHA/CRC archive, commit/push only `personal`, update draft PR65 and the active `flydrones` heartbeat. Continue independent low-memory provenance-bound EKF2/camera/EGO and full connectome training work; do not claim the swarm objective complete.
