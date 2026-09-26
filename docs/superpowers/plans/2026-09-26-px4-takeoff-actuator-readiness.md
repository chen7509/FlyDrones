# PX4 Takeoff and Actuator Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a PX4 worker from entering the autonomous mission until command acceptance, actual climb, OFFBOARD state, and the PX4-to-Gazebo actuator chain are proven per vehicle.

**Architecture:** A MAVLink-only takeoff transaction owns flight readiness and safe failure handling. A separate Gazebo Transport probe observes motor commands and raw odometry only for SITL diagnostics; offline evidence joins worker JSON, ULog, and Gazebo events without feeding simulator truth into control.

**Tech Stack:** Python 3.10+, pymavlink, PX4 SITL, Gazebo Harmonic / `gz.transport13`, pyulog, pytest, Ruff, PowerShell and WSL Ubuntu.

**Spec:** `docs/superpowers/specs/2026-09-26-px4-takeoff-actuator-readiness-design.md`

## Global Constraints

- Do not change policy weights, loss functions, curriculum training, planner thresholds, vehicle model, sensors, or mission geometry.
- Gazebo truth and actuator probe data are diagnostic artifacts only; they must never enter the autonomous policy, safety supervisor, MAVLink telemetry, or PX4 EKF.
- `mission-ready` requires a matching arm ACK, armed state, matching takeoff ACK, three consecutive fresh altitude samples at least 0.5 m above baseline within 12 seconds, and confirmed OFFBOARD after 1.5 seconds of setpoint priming.
- Retry at most once and only before any accepted arm/takeoff side effect, with fresh evidence that the vehicle is both disarmed and landed.
- Preserve every failed run, ULog, PX4 console log, cleanup record, and SHA-256 index; never overwrite or patch a frozen campaign.
- Unit tests, kinematic tests, Gazebo physics runs, HITL, and real flight must be labeled separately.
- Keep the existing three raw result trees untracked; publish only compact summaries and checksums under `docs/results`.
- Add no product runtime dependency and do not modify PX4 or Gazebo upstream source.

## Review Focus

- An unrelated or stale `COMMAND_ACK` must not satisfy the current command; Task 2 tests command, target, result, and timeout correlation.
- PX4 may report takeoff complete and not landed while the model remains stationary; Task 2 requires continuous altitude gain and Task 6 cross-checks Gazebo odometry.
- A worker whose takeoff fails must make zero policy and planner calls; Task 3 pins this before any mission loop is entered.
- A Gazebo probe may start late, lose a topic, or end with a truncated JSONL tail; Tasks 4 and 5 reject incomplete evidence and preserve it.
- Old trial directories lack the new evidence schema; Task 6 labels them `legacy-unverified` instead of passing or crashing.

---

## File Structure

- Create `src/flydrones/takeoff_readiness.py`: immutable runtime evidence types, reason codes, serialization, and pure offline chain classification.
- Modify `src/flydrones/safety.py`: add PX4 armed, landed, navigation, OFFBOARD, and status freshness fields to `Telemetry`.
- Modify `src/flydrones/drones/mavlink.py`: correlate command ACKs, consume status messages, run the takeoff state machine, and fail safely.
- Modify `src/flydrones/distributed_px4.py`: gate mission entry, persist takeoff evidence, and support a short takeoff-only validation mode.
- Modify `tools/px4_distributed_agent.py` and `tools/run_distributed_px4_swarm.py`: expose and aggregate takeoff-only runs.
- Create `tools/probe_gazebo_actuator_link.py`: read-only Gazebo Transport motor-command and odometry recorder.
- Modify `tools/run_vio_stress_trial_wsl.py`: own the probe lifecycle, preserve PX4 console logs, and hash the new artifacts.
- Modify `tools/summarize_vio_stress_wsl.py`: extract ULog takeoff state and classify every vehicle's end-to-end chain.
- Create `configs/px4_takeoff_stability.json` and `tools/run_takeoff_stability_campaign_wsl.py`: frozen ten-run D3D12 cold-start gate.
- Modify `configs/vio_renderer_stability.json`: update frozen hashes only after code and thresholds are frozen.
- Create or modify focused tests named in each task; update `docs/VIO_RENDERER_STABILITY_REPORT.md` and compact results only after live validation.

### Task 1: Takeoff Evidence Contract

**Files:**
- Create: `src/flydrones/takeoff_readiness.py`
- Create: `tests/test_takeoff_readiness.py`

**Interfaces:**
- Consumes: no product modules.
- Produces: `TakeoffStage`, `TakeoffFailureReason`, `CommandAckEvidence`, `TakeoffEvent`, `TakeoffEvidence`, `TakeoffEvidence.to_dict()`, and `classify_takeoff_chain(worker, ulog, gazebo) -> dict[str, object]`.

- [ ] **Step 1: Write failing evidence-model tests**

Add tests that assert JSON-safe serialization preserves ordered events and target IDs; accepted evidence is possible only at `mission-ready`; missing worker/ULog/Gazebo sections return `legacy-unverified`; and the classifier distinguishes `gazebo-motor-command-missing`, `actuator-response-timeout`, and `estimator-response-timeout`.

- [ ] **Step 2: Run the focused tests and verify the new module is missing**

Run: `python -m pytest tests/test_takeoff_readiness.py -q`

Expected: FAIL during import of `flydrones.takeoff_readiness`.

- [ ] **Step 3: Implement the immutable evidence types and pure classifier**

Use `str, Enum` rather than `StrEnum` for Python 3.10. Pin the runtime thresholds as explicit inputs; do not read configuration or files inside the classifier.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_takeoff_readiness.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the evidence contract**

Commit: `Add takeoff readiness evidence model`

### Task 2: Transactional MAVLink Takeoff

**Files:**
- Modify: `src/flydrones/safety.py`
- Modify: `src/flydrones/drones/mavlink.py`
- Modify: `tests/test_mavlink_drone.py`

**Interfaces:**
- Consumes: Task 1 evidence types.
- Produces: `MavlinkDrone.takeoff() -> TakeoffEvidence`, `_ingest_message(message, *, received_at: float) -> None`, `_wait_command_ack(command: int, *, timeout_s: float) -> CommandAckEvidence`, and PX4 status fields on `Telemetry`.

- [ ] **Step 1: Add failing MAVLink state and ACK tests**

Cover matching versus unrelated ACKs, target-system mismatch, `IN_PROGRESS` followed by `ACCEPTED`, rejection, hard timeout, heartbeat armed state, `EXTENDED_SYS_STATE` landed state, OFFBOARD confirmation, interleaved position/status messages during ACK waits, and unchanged sensor timestamps when no fresh messages arrive.

- [ ] **Step 2: Run the state and ACK tests to verify failure**

Run: `python -m pytest tests/test_mavlink_drone.py -q`

Expected: FAIL on missing status fields and transaction helpers.

- [ ] **Step 3: Implement status ingestion and correlated ACK waiting**

Route every received MAVLink message through `_ingest_message` so blocking ACK waits cannot discard sensor or status updates. Request `EXTENDED_SYS_STATE` explicitly, filter ACKs by command and available target extensions, and record unmatched ACKs without treating them as success.

- [ ] **Step 4: Add failing takeoff postcondition tests**

Use deterministic fake time and telemetry sequences to assert: three samples over 0.5 m pass; one spike fails; accepted commands with stationary altitude return `actuator-response-timeout`; OFFBOARD rejection fails; `flying` remains false until `mission-ready`; and no retry occurs after accepted arm or takeoff.

- [ ] **Step 5: Run the new takeoff tests to verify failure**

Run: `python -m pytest tests/test_mavlink_drone.py -q`

Expected: FAIL in the legacy fixed-sleep `takeoff()`.

- [ ] **Step 6: Implement the takeoff state machine and bounded recovery**

Use 12 seconds, 0.5 m, three consecutive fresh samples, 1.5 seconds of setpoint priming, and the configured rate. On failure after arming, request LAND, wait for landed evidence, and disarm only after landed is confirmed; retain cleanup failure in the returned evidence.

- [ ] **Step 7: Run MAVLink and safety regression tests**

Run: `python -m pytest tests/test_mavlink_drone.py tests/test_control.py -q`

Expected: PASS.

- [ ] **Step 8: Commit the MAVLink transaction**

Commit: `Require confirmed PX4 takeoff readiness`

### Task 3: Gate the Distributed Worker

**Files:**
- Modify: `src/flydrones/distributed_px4.py`
- Modify: `tools/px4_distributed_agent.py`
- Modify: `tools/run_distributed_px4_swarm.py`
- Modify: `tests/test_distributed_px4.py`

**Interfaces:**
- Consumes: `MavlinkDrone.takeoff() -> TakeoffEvidence`.
- Produces: `result["takeoff"]`, `checks["takeoff_mission_ready"]`, `DistributedAgentConfig.takeoff_only_hold_s`, and `aggregate_takeoff_readiness_artifacts(output_dir, vehicle_count=5) -> tuple[list[dict], dict]`.

- [ ] **Step 1: Replace the transient-arm retry test with failing readiness gates**

Assert a rejected, timed-out, or no-climb takeoff produces zero policy/planner calls, never logs `escaping`, records the exact reason, requests safe landing when armed, and cannot be accepted. Add a success fixture that returns `mission-ready` evidence.

- [ ] **Step 2: Run worker tests to verify the legacy path enters the mission**

Run: `python -m pytest tests/test_distributed_px4.py -q`

Expected: FAIL because the worker ignores a structured takeoff result and still retries the entire call.

- [ ] **Step 3: Gate mission entry and persist takeoff evidence**

Remove the blind full-takeoff retry. Write the takeoff object even when the trace is empty, and keep the worker's existing `finally` cleanup path.

- [ ] **Step 4: Add failing takeoff-only mode and aggregation tests**

Assert `takeoff_only_hold_s=2.0` streams local zero-velocity hold commands, makes no policy/planner calls, lands, and is accepted by `aggregate_takeoff_readiness_artifacts` only when all five workers are mission-ready and landed.

- [ ] **Step 5: Implement CLI plumbing and takeoff-only aggregation**

Add `--takeoff-only-hold-s` to both worker CLIs and `build_distributed_agent_commands`; keep the default autonomous mission unchanged.

- [ ] **Step 6: Run worker and CLI tests**

Run: `python -m pytest tests/test_distributed_px4.py -q`

Run: `python tools/px4_distributed_agent.py --help`

Run: `python tools/run_distributed_px4_swarm.py --help`

Expected: PASS.

- [ ] **Step 7: Commit the mission gate**

Commit: `Gate PX4 missions on takeoff readiness`

### Task 4: Read-Only Gazebo Actuator Probe

**Files:**
- Create: `tools/probe_gazebo_actuator_link.py`
- Modify: `src/flydrones/takeoff_readiness.py`
- Create: `tests/test_gazebo_actuator_probe.py`

**Interfaces:**
- Consumes: five model names `x500_depth_fly_0` through `_4`, Gazebo `Actuators`, and raw odometry.
- Produces: `actuator-link.jsonl`, a readiness marker, and `summarize_actuator_link(events, fleet_size) -> dict[str, object]`.

- [ ] **Step 1: Write failing routing and summary tests**

Cover exact per-model motor topic mapping, cross-model rejection, out-of-order timestamps, malformed events, stationary odometry despite significant motor command, physical movement with stationary EKF input, missing stop event, and one-vehicle/five-vehicle modes.

- [ ] **Step 2: Run probe tests to verify failure**

Run: `python -m pytest tests/test_gazebo_actuator_probe.py -q`

Expected: FAIL because the CLI and summary do not exist.

- [ ] **Step 3: Implement the probe and pure summary**

Import `gz.transport13` only inside live execution. Subscribe independently to `/{model}/command/motor_speed` and `/flydrones/odometry_raw`; write line-buffered `start`, `topology`, `motor-command`, `odometry`, error, and `stop` events. Never publish and never expose probe data to a controller object.

- [ ] **Step 4: Run probe tests and script help**

Run: `python -m pytest tests/test_gazebo_actuator_probe.py -q && python tools/probe_gazebo_actuator_link.py --help`

Expected: tests PASS and help exits 0 without importing Gazebo bindings.

- [ ] **Step 5: Commit the probe**

Commit: `Add Gazebo actuator link probe`

### Task 5: Trial Lifecycle and Artifact Preservation

**Files:**
- Modify: `tools/run_vio_stress_trial_wsl.py`
- Modify: `tests/test_vio_stress_runner.py`

**Interfaces:**
- Consumes: Task 4 probe CLI and readiness/stop markers.
- Produces: manifest schema `flydrones-vio-stress-trial-v3`, `actuator_probe_closed_cleanly`, `actuator-link.jsonl`, per-instance PX4 console logs, and hashes for every artifact.

- [ ] **Step 1: Add failing runner lifecycle tests**

Assert the worker cannot start before probe readiness, a probe timeout rejects evidence, shutdown targets only the owned process group, all `instance_N/out.log` and `err.log` files are copied, a truncated probe log is preserved, and frozen hashes include the probe plus readiness module.

- [ ] **Step 2: Run runner tests to verify failure**

Run: `python -m pytest tests/test_vio_stress_runner.py -q`

Expected: FAIL on missing v3 fields and probe lifecycle.

- [ ] **Step 3: Integrate the owned probe and console-log copy**

Start the probe only after a successful PX4/Gazebo launch, wait for its readiness marker before workers, stop it through the trial completion marker, and include its clean stop in `evidence_accepted`.

- [ ] **Step 4: Run runner tests**

Run: `python -m pytest tests/test_vio_stress_runner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit lifecycle evidence**

Commit: `Preserve actuator and PX4 startup evidence`

### Task 6: ULog Correlation and Hard Acceptance Gates

**Files:**
- Modify: `src/flydrones/takeoff_readiness.py`
- Modify: `tools/summarize_vio_stress_wsl.py`
- Modify: `src/flydrones/renderer_stability.py`
- Modify: `tests/test_takeoff_readiness.py`
- Modify: `tests/test_vio_stress_summary.py`
- Modify: `tests/test_renderer_stability.py`

**Interfaces:**
- Consumes: worker takeoff JSON, `actuator-link.jsonl`, and ULog datasets named in the spec.
- Produces: `takeoff_chain_by_vehicle`, per-vehicle reason codes, `all_takeoff_chains_proven`, and renderer rejection reasons.

- [ ] **Step 1: Add failing ULog and legacy-evidence tests**

Build small dataset dictionaries for accepted commands with climb, accepted commands without ground-truth movement, ground-truth climb without EKF climb, missing datasets, and legacy v2 manifests. Assert only a complete v3 chain can pass.

- [ ] **Step 2: Run summary tests to verify failure**

Run: `python -m pytest tests/test_takeoff_readiness.py tests/test_vio_stress_summary.py tests/test_renderer_stability.py -q`

Expected: FAIL on missing takeoff-chain output and hard gates.

- [ ] **Step 3: Implement per-vehicle ULog extraction and cross-source classification**

Keep raw timestamps and source hashes. Do not infer Gazebo receipt from PX4 `esc_status`, because the bridge subscribes to its own command topic.

- [ ] **Step 4: Enforce gates in stress and renderer summaries**

Require all expected vehicles to be `mission-ready`, have a complete actuator chain, and land. Emit explicit missing or legacy reasons rather than a generic operational failure.

- [ ] **Step 5: Run evidence and renderer tests**

Run: `python -m pytest tests/test_takeoff_readiness.py tests/test_vio_stress_summary.py tests/test_renderer_stability.py -q`

Expected: PASS.

- [ ] **Step 6: Commit hard evidence gates**

Commit: `Require end-to-end takeoff evidence`

### Task 7: Frozen Ten-Run Takeoff Stability Campaign

**Files:**
- Create: `configs/px4_takeoff_stability.json`
- Create: `tools/run_takeoff_stability_campaign_wsl.py`
- Create: `tests/test_takeoff_stability_campaign.py`
- Modify: `tools/run_vio_stress_trial_wsl.py`
- Modify: `tools/run_renderer_stability_campaign_wsl.py`
- Modify: `tests/test_renderer_stability_campaign.py`
- Modify: `configs/vio_renderer_stability.json`

**Interfaces:**
- Consumes: `run_trial(..., takeoff_only_hold_s=2.0)` and per-trial takeoff-chain summaries.
- Produces: immutable ten-run schedule, fail-fast campaign manifest, `50/50` acceptance, and refreshed frozen hashes for later smoke/formal campaigns.

- [ ] **Step 1: Write failing schedule, resume, and fail-fast tests**

Assert exactly ten D3D12 five-vehicle cold starts, unique trial names, no overwrite, resume only from complete trials, stop on the first failed vehicle, `50/50` readiness/landing requirement, and cleanup verification between runs.

- [ ] **Step 2: Run campaign tests to verify failure**

Run: `python -m pytest tests/test_takeoff_stability_campaign.py tests/test_renderer_stability_campaign.py -q`

Expected: FAIL because the stability runner and takeoff-only trial option do not exist.

- [ ] **Step 3: Implement the immutable stability runner and trial option**

Use seed 240901, renderer `d3d12-nvidia`, fleet size 5, hold 2.0 seconds, ten runs, and new output IDs. Keep normal smoke/formal schedules unchanged.

- [ ] **Step 4: Freeze code and update expected hashes once**

Run the project hash calculators, update both configuration files from their output, and reject any later source drift with the existing hash tests.

- [ ] **Step 5: Run campaign and frozen-hash tests**

Run: `python -m pytest tests/test_takeoff_stability_campaign.py tests/test_renderer_stability_campaign.py -q`

Expected: PASS.

- [ ] **Step 6: Run all automated quality gates**

Run: `python -m pytest -q`

Run targeted Ruff on every changed Python file and `git diff --check`. Record the existing unrelated repo-wide Ruff findings separately if they remain unchanged.

Expected: all tests and targeted Ruff PASS; diff check is clean.

- [ ] **Step 7: Commit the frozen campaign**

Commit: `Add frozen PX4 takeoff stability campaign`

### Task 8: Live Diagnosis, Stability Gate, Formal Rerun, and Report

**Files:**
- Modify: `docs/VIO_RENDERER_STABILITY_REPORT.md`
- Create: `docs/results/px4-takeoff-stability/<campaign-id>/...`
- Create: `docs/results/vio-renderer-stability/<new-smoke-id>/...`
- Create: `docs/results/vio-renderer-stability/<new-formal-id>/...`

**Interfaces:**
- Consumes: all prior tasks and frozen configs.
- Produces: preserved raw campaigns, compact snapshots, checksums, final diagnosis, and the revised renderer verdict.

- [ ] **Step 1: Verify resources and revisions before live work**

Confirm no owned PX4, Gazebo, relay, probe, training, or worker process is running; record repository, PX4, Gazebo, Mesa, renderer, model, policy, profile, and config hashes.

- [ ] **Step 2: Run the three development scenarios**

Run one D3D12 vehicle, five D3D12 vehicles, and the automated stationary-physics injection test. Inspect every vehicle's command ACK, mission-ready result, motor-command receipt, odometry climb, ULog state, landing, and cleanup before freezing.

- [ ] **Step 3: Classify any live failure before authoring its correction**

If a development scenario fails, preserve the immutable trial and produce one of the Task 6 reason codes with its PX4, Transport, odometry, and cleanup evidence. Stop this plan at that diagnostic boundary and write a reviewed amendment for the identified component before changing behavior; the correction cannot be specified honestly until the new probe shows whether the bridge, motor plugin/physics, or estimator failed. After that amendment is implemented, repeat Tasks 6–7 quality gates and restart all development scenarios with new IDs. Do not tune the policy or relax thresholds.

- [ ] **Step 4: Run the ten-cycle D3D12 stability gate**

Run `tools/run_takeoff_stability_campaign_wsl.py` with a new campaign ID. Stop at the first failure, retain it, and return to Step 3; acceptance requires 10/10 trials and 50/50 vehicles mission-ready, landed, and fully evidenced.

- [ ] **Step 5: Run a new renderer smoke campaign**

Use `tools/run_renderer_stability_campaign_wsl.py --phase smoke` with a new ID. Require all three smoke scenarios, evidence, renderer attestation, and cleanup to pass.

- [ ] **Step 6: Run the complete formal renderer campaign from the beginning**

Use a new formal campaign ID and the frozen ten-run schedule. Preserve all failures and obey the existing hard stop rules; never splice results from earlier campaigns.

- [ ] **Step 7: Publish compact evidence and update the report**

Snapshot manifests, summaries, bounded failure windows, PX4 console excerpts, and raw-file SHA-256/size indexes without copying ULogs. State the exact remaining limits: Gazebo physics, truth-relay EV surrogate, measured wall-clock latency, slow-simulation behavior, and absence of HITL/real flight evidence.

- [ ] **Step 8: Run final verification and commit the report**

Run full pytest, targeted Ruff, `git diff --check`, compact-index verification, and owned-process cleanup verification.

Commit: `Report verified PX4 takeoff stability`
