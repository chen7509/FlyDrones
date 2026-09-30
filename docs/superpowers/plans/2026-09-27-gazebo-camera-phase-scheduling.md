# Gazebo Camera Phase Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable simulation-clock scheduler that preserves five 10 Hz depth streams while staggering them at 0/20/40/60/80 ms, then determine with a frozen paired campaign whether it removes D3D12 tail-latency degradation.

**Architecture:** A pure Python scheduling/evidence module defines all timing math and gates. Trial-only SDF transformation enables Gazebo's built-in triggered depth-camera mode, a publisher process emits simulation-time triggers, and an independent observer measures actual image timestamps for both simultaneous and phased trials. The existing PX4/Gazebo trial runner owns their lifecycle, while a separate frozen campaign runner performs alternating D3D12 control/treatment pairs.

**Tech Stack:** Python 3.10+, `gz.transport13`, `gz.msgs10`, Gazebo Harmonic / gz-sensors 8, SDFormat XML, PX4 SITL, pyulog, pytest, Ruff, PowerShell and WSL Ubuntu.

**Spec:** `docs/superpowers/specs/2026-09-27-gazebo-camera-phase-scheduling-design.md`

## Global Constraints

- Keep every camera at 160×120, 10 Hz, the existing FOV, clip range, pose and inertia.
- Use simulation time for scheduling; wall time is evidence only.
- The only formal independent variable is `camera_schedule_mode = simultaneous | phased`.
- Phased offsets are exactly 0, 20, 40, 60 and 80 ms in each 100 ms period.
- Phase-error p95 and adjacent-spacing median error are each capped at 8 ms.
- Do not change policy weights, loss functions, curriculum, planner, PX4 controller, safety thresholds, mission geometry or vehicle dynamics.
- Do not modify PX4, Gazebo, gz-sensors or SDFormat upstream source.
- Do not feed scheduler or phase-probe evidence into the policy, safety supervisor, MAVLink telemetry or PX4 EKF.
- Preserve every failed trial and never overwrite or splice a frozen campaign.
- Do not run 120 ms / 400 ms fault regressions unless the no-fault paired gate passes.
- Label unit tests, Gazebo physics simulation, HITL and real flight separately.
- Keep raw ULogs, CSV/JSONL streams and console logs out of Git; version compact summaries and SHA-256/size indexes.
- Stop at an amendment boundary if the installed gz-sensors 8 does not support triggered depth cameras.

## Review Focus

- A large `/clock` jump must record missed slots and publish at most one current trigger, never emit a catch-up burst; Task 2 pins this.
- A stale, duplicated or cross-model topic must prevent readiness and cannot be attributed to another vehicle; Tasks 4 and 5 pin this.
- A phased trial must transform only its run-directory camera copy and restore the shared PX4 model byte-for-byte; Tasks 3 and 6 pin this.
- The phase observer must run in both groups and bounded buffering must not block Gazebo callbacks or silently drop images; Task 5 pins this.
- Resume must reject schedule, threshold, source-hash or mode drift even when trial directories look complete; Task 7 pins this.

---

## File Structure

- Create `tools/check_triggered_depth_camera_wsl.py`: isolated installed-stack compatibility probe; no product imports at module import time.
- Create `src/flydrones/camera_phase.py`: schedule math, immutable event types, topic mapping and pure evidence summary.
- Create `tools/configure_gazebo_camera_phase.py`: trial-copy SDF transformer and structural evidence.
- Create `tools/run_camera_phase_scheduler_wsl.py`: phased-only simulation-clock trigger publisher.
- Create `tools/probe_camera_phase_wsl.py`: read-only actual image/trigger observer used by both modes.
- Modify `tools/launch_px4_depth_swarm_wsl.sh`: validate mode and configure the copied camera model before Gazebo starts.
- Modify `tools/run_vio_stress_trial_wsl.py`: own scheduler/probe lifecycle, manifests, artifacts and hashes.
- Modify `tools/summarize_vio_stress_wsl.py`: add per-trial `camera_phase` evidence without changing policy inputs.
- Create `src/flydrones/camera_phase_stability.py`: smoke/formal schedules and trial/campaign scoring.
- Create `configs/vio_camera_phase_stability.json`: frozen thresholds, alternating schedule and expected hashes.
- Create `tools/run_camera_phase_stability_campaign_wsl.py`: immutable smoke/formal orchestration.
- Modify `tools/snapshot_vio_gate_results.py`: compact camera-phase campaign evidence and raw indexes.
- Create focused tests matching each component and `docs/CAMERA_PHASE_STABILITY_REPORT.md` after live validation.

### Task 1: Installed Triggered Depth-Camera Compatibility Gate

**Files:**
- Create: `tools/check_triggered_depth_camera_wsl.py`
- Create: `tests/test_triggered_depth_compatibility.py`
- Create after live probe: `docs/results/camera-phase/triggered-depth-compatibility.json`

**Interfaces:**
- Consumes: installed `gz sim`, `gz.transport13`, `gz.msgs10.Boolean`, a temporary SDF 1.9 world and D3D12 renderer environment.
- Produces: `classify_probe(events: Sequence[Mapping[str, object]]) -> dict[str, object]` and a versioned compatibility record proving no image before trigger and one new image after each trigger.

- [ ] **Step 1: Write failing compatibility-classifier tests**

Add tests named:

- `test_triggered_depth_probe_requires_no_pretrigger_image`
- `test_triggered_depth_probe_requires_one_new_image_per_trigger`
- `test_triggered_depth_probe_rejects_wrong_message_or_topic`
- `test_probe_cleanup_is_required_for_acceptance`

Assert explicit reason codes and `accepted is False` for every incomplete case.

- [ ] **Step 2: Run the focused test and verify the tool is missing**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_triggered_depth_compatibility.py -q`

Expected: FAIL during import of `tools.check_triggered_depth_camera_wsl`.

- [ ] **Step 3: Implement the isolated compatibility CLI**

Implement:

```python
def classify_probe(events: Sequence[Mapping[str, object]]) -> dict[str, object]: ...
def run_probe(output: Path, *, renderer_profile: str = "d3d12-nvidia") -> dict[str, object]: ...
```

The CLI creates a temporary 16×12 triggered depth-camera world, starts one owned headless Gazebo process, subscribes before triggering, publishes `gz.msgs.Boolean(data=True)`, records installed versions and renderer evidence, then cleans up only the owned process. Imports of Gazebo bindings stay inside live execution.

- [ ] **Step 4: Run unit tests and CLI help**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_triggered_depth_compatibility.py -q`

Run: `python tools/check_triggered_depth_camera_wsl.py --help`

Expected: PASS and help exits 0 without loading Gazebo.

- [ ] **Step 5: Verify resources and run the live installed-stack probe**

Confirm no PX4, Gazebo, relay, probe, worker or training process is active. Run the CLI in WSL with a new temporary directory and write
`docs/results/camera-phase/triggered-depth-compatibility.json`.

Acceptance requires:

- zero image messages during the bounded pre-trigger window;
- one additional image after each of three Boolean triggers;
- monotonically increasing image simulation timestamps;
- D3D12 renderer attested;
- owned Gazebo process released.

If this fails, preserve the record, stop the plan and write a reviewed C++ plugin amendment. Do not continue with a wall-clock substitute.

- [ ] **Step 6: Commit compatibility evidence**

```bash
git add tools/check_triggered_depth_camera_wsl.py tests/test_triggered_depth_compatibility.py docs/results/camera-phase/triggered-depth-compatibility.json
git commit -m "Verify triggered Gazebo depth cameras"
```

### Task 2: Pure Simulation-Time Schedule and Evidence Contract

**Files:**
- Create: `src/flydrones/camera_phase.py`
- Create: `tests/test_camera_phase.py`

**Interfaces:**
- Consumes: integer simulation timestamps and JSON-compatible event mappings.
- Produces: `CameraScheduleMode`, `CameraPhaseThresholds`, `TriggerSlot`, `TriggerSchedulerState.advance(sim_ns: int) -> tuple[TriggerSlot, ...]`, `camera_phase_offsets_ns(vehicle_count: int) -> tuple[int, ...]`, `align_epoch_ns(sim_ns: int) -> int`, `depth_topic_vehicle_id(topic: str, *, world: str, vehicle_count: int) -> int | None`, and `summarize_camera_phase(events: Sequence[Mapping[str, object]], *, mode: CameraScheduleMode, vehicle_count: int, thresholds: CameraPhaseThresholds) -> dict[str, object]`.

- [ ] **Step 1: Write failing schedule tests**

Cover exact one/five-vehicle offsets, epoch alignment, 100 ms recurrence, pause with repeated timestamps, 4 ms steps, time reversal, duplicate clocks and a jump across multiple slots. The jump test must assert one current slot at most plus explicit missed slots, never multiple catch-up publications.

- [ ] **Step 2: Write failing topic and evidence tests**

Cover exact scoped topic mapping, `x500_depth_fly_0` versus `_00`, unknown world/model, unordered input, malformed events, wrap-around from 80 ms to 0 ms, 9.5/10.5 Hz boundaries, 8 ms phase and spacing boundaries, missing/duplicate/unmatched images, and required start/topology/ready/stop events.

- [ ] **Step 3: Run tests and verify the module is missing**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase.py -q`

Expected: FAIL during import.

- [ ] **Step 4: Implement the immutable contract and pure algorithms**

Use `str, Enum` for Python 3.10. Use integer nanoseconds throughout scheduling and circular phase calculations. `advance` must be deterministic and must expose missed slots separately from returned publish slots.

- [ ] **Step 5: Run focused tests**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase.py -q`

Expected: PASS.

- [ ] **Step 6: Commit scheduling contract**

```bash
git add src/flydrones/camera_phase.py tests/test_camera_phase.py
git commit -m "Add camera phase scheduling contract"
```

### Task 3: Trial-Copy Camera Model Configuration

**Files:**
- Create: `tools/configure_gazebo_camera_phase.py`
- Create: `tests/test_camera_phase_model.py`

**Interfaces:**
- Consumes: source/target `OakD-Lite-Fly/model.sdf` paths and `CameraScheduleMode`.
- Produces: `configure_camera_model(source: Path, target: Path, *, mode: CameraScheduleMode) -> dict[str, object]` and CLI JSON evidence.

- [ ] **Step 1: Write failing semantic-transformation tests**

Assert:

- phased adds exactly one `camera/triggered=true`;
- simultaneous leaves the sensor free-running;
- both modes preserve width 160, height 120, update rate 10, FOV, clip, pose, inertial and topic fields;
- missing or multiple `StereoOV7251` sensors fail;
- pre-existing contradictory trigger settings fail;
- source and target cannot resolve to the same path;
- evidence includes source/target SHA-256 and a bounded structural diff.

- [ ] **Step 2: Run tests and verify the tool is missing**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase_model.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement the SDF transformer and CLI**

Use `xml.etree.ElementTree`; copy all non-target files unchanged. The transformer writes through a temporary target and atomically replaces it. It never edits `assets/gazebo/models/OakD-Lite-Fly` or an existing PX4 backup.

- [ ] **Step 4: Run focused tests and CLI help**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase_model.py -q`

Run: `python tools/configure_gazebo_camera_phase.py --help`

Expected: PASS.

- [ ] **Step 5: Commit model configuration**

```bash
git add tools/configure_gazebo_camera_phase.py tests/test_camera_phase_model.py
git commit -m "Configure trial-only triggered cameras"
```

### Task 4: Simulation-Clock Trigger Scheduler

**Files:**
- Create: `tools/run_camera_phase_scheduler_wsl.py`
- Create: `tests/test_camera_phase_scheduler.py`

**Interfaces:**
- Consumes: Task 2 scheduler state, `/clock`, expected model count, completion marker and trigger topics derived from discovered depth topics.
- Produces: `camera-scheduler.jsonl`, `camera-scheduler-ready.json`, and `run_scheduler(config: Mapping[str, object], *, node_factory: Callable[[], object], monotonic: Callable[[], float], sleep: Callable[[float], None]) -> int`.

- [ ] **Step 1: Write failing topology and lifecycle tests**

Use fake Transport nodes to assert:

- readiness requires exactly the expected unique depth and trigger topics plus one clock sample;
- stale/duplicate/cross-model topics reject readiness;
- trigger publishers map to the same vehicle as their depth topics;
- start/topology/ready/trigger/missed/clock-reset/stop events are line-buffered;
- completion marker yields a clean stop;
- publisher or clock failure returns nonzero and preserves the log.

- [ ] **Step 2: Write failing publication tests**

Drive fake clock samples through pause, normal 4 ms steps, 100 ms wrap, backward reset and 60 ms jump. Assert published Boolean messages match Task 2 slots, and the jump records misses without a batch.

- [ ] **Step 3: Run tests and verify the scheduler is missing**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase_scheduler.py -q`

Expected: FAIL during import.

- [ ] **Step 4: Implement the live scheduler**

Lazy-import `Clock`, `Boolean` and `Node` inside live setup. Keep callbacks bounded: callbacks update latest clock/topology state, while the main loop performs logging and publication. Add a development-only `--stop-after-trigger-count` fault injection flag; default `None`, recorded in the start event, and forbidden by formal config validation.

- [ ] **Step 5: Run focused tests and CLI help**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase_scheduler.py -q`

Run: `python tools/run_camera_phase_scheduler_wsl.py --help`

Expected: PASS.

- [ ] **Step 6: Commit scheduler**

```bash
git add tools/run_camera_phase_scheduler_wsl.py tests/test_camera_phase_scheduler.py
git commit -m "Schedule phased Gazebo camera triggers"
```

### Task 5: Independent Actual-Image Phase Observer

**Files:**
- Create: `tools/probe_camera_phase_wsl.py`
- Create: `tests/test_camera_phase_probe.py`
- Modify: `src/flydrones/camera_phase.py`
- Modify: `tests/test_camera_phase.py`

**Interfaces:**
- Consumes: five depth-image topics, optional trigger topics, `/clock`, completion marker and Task 2 evidence summary.
- Produces: `camera-phase.jsonl`, `camera-phase-ready.json`, `camera-phase-summary.json`, and `run_probe(config: Mapping[str, object], *, node_factory: Callable[[], object], monotonic: Callable[[], float], sleep: Callable[[float], None]) -> int`.

- [ ] **Step 1: Write failing observer tests**

Assert:

- actual image header stamps, receipt monotonic times, sequence and model id are retained;
- both modes subscribe to the same image topics;
- phased additionally observes trigger transport messages;
- cross-model and repeated image stamps are explicit failures;
- bounded callback queues report overflow and make evidence fail;
- callbacks enqueue only and do not write files or compute statistics;
- malformed final JSONL and missing stop remain preserved and rejected.

- [ ] **Step 2: Extend pure evidence tests**

Add trigger-to-image matching tests, including one-step delay, 8 ms boundary, unmatched triggers/images, circular wrap and reordered callback arrival. The image header simulation timestamp is authoritative.

- [ ] **Step 3: Run tests and verify failure**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase.py tests/test_camera_phase_probe.py -q`

Expected: FAIL on missing observer and matching output.

- [ ] **Step 4: Implement the observer and bounded writer loop**

Lazy-import Gazebo bindings. Use a bounded queue sized for at least 10 seconds of five 10 Hz streams; any overflow is logged and fails evidence. Write the pure summary only after a clean stop.

- [ ] **Step 5: Run focused tests and CLI help**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase.py tests/test_camera_phase_probe.py -q`

Run: `python tools/probe_camera_phase_wsl.py --help`

Expected: PASS.

- [ ] **Step 6: Commit observer**

```bash
git add src/flydrones/camera_phase.py tools/probe_camera_phase_wsl.py tests/test_camera_phase.py tests/test_camera_phase_probe.py
git commit -m "Observe actual Gazebo camera phases"
```

### Task 6: Trial Lifecycle, Manifest and Summary Integration

**Files:**
- Modify: `tools/launch_px4_depth_swarm_wsl.sh`
- Modify: `tools/run_vio_stress_trial_wsl.py`
- Modify: `tools/summarize_vio_stress_wsl.py`
- Modify: `tools/stop_px4_swarm_wsl.sh`
- Modify: `tests/test_vio_stress_runner.py`
- Modify: `tests/test_vio_stress_summary.py`

**Interfaces:**
- Consumes: `run_trial(..., camera_schedule_mode: str = "simultaneous", camera_scheduler_stop_after_trigger_count: int | None = None)`, Tasks 3–5 CLIs and existing completion/ownership helpers.
- Produces: optional v3 manifest fields `camera_schedule_mode`, `camera_model_evidence`, `camera_scheduler_closed_cleanly`, `camera_phase_probe_closed_cleanly`, frozen hashes for all new sources, `stress-summary.json["camera_phase"]`, and a two-stage launcher handshake using `gazebo-base-ready.json` plus `camera-aux-started.marker`.

- [ ] **Step 1: Write failing runner lifecycle tests**

Assert:

- only `simultaneous|phased` is accepted;
- the launcher creates trial copies and starts relay/Gazebo, then writes `gazebo-base-ready.json` and waits without starting PX4;
- after that marker, both modes start the observer and phased also starts the scheduler, then the runner writes `camera-aux-started.marker`;
- only after that handshake may the launcher start PX4, which creates the model topics the auxiliary processes discover;
- worker waits for launcher, observer, renderer and actuator readiness, and phased also waits for scheduler readiness;
- worker cannot start after scheduler/probe timeout or early exit;
- launch configures only the copied PX4 camera model;
- the base asset and backed-up PX4 model fingerprints are unchanged after cleanup;
- completion marker, process-group cleanup and logs are preserved on exceptions;
- existing trials default to simultaneous behavior;
- formal callers cannot set the development fault-injection option.

- [ ] **Step 2: Write failing manifest/hash tests**

Require the phase mode, model evidence, scheduler/probe artifacts and new source hashes. Keep manifest schema `flydrones-vio-stress-trial-v3`; fields are backward-compatible optional extensions. Old v3 manifests without phase evidence remain valid for historical renderer reports but cannot pass a camera-phase campaign.

- [ ] **Step 3: Write failing summary tests**

Assert `summarize_trial` loads `camera-phase-summary.json`, includes it under `camera_phase`, preserves reason codes, and does not expose phase data through workers, policy observations or safety inputs. Missing phase evidence is explicit, not synthesized.

- [ ] **Step 4: Run focused tests and verify failure**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_vio_stress_runner.py tests/test_vio_stress_summary.py -q`

Expected: FAIL on missing mode and lifecycle fields.

- [ ] **Step 5: Add the two-stage Gazebo/PX4 launcher handshake**

Set `FLYDRONES_CAMERA_SCHEDULE_MODE` for launch. After copying the base camera asset, invoke Task 3 against the PX4 run copy and write `camera-model-evidence.json`. Start the launcher with `Popen`; it starts relay/Gazebo, writes `gazebo-base-ready.json`, and waits with a bounded timeout for `camera-aux-started.marker` before entering its existing PX4 loop. The runner waits for the base-ready marker, starts the observer and optional scheduler, records their owned process identities, writes the continuation marker, and then waits for launcher completion. Every timeout or early exit preserves evidence and fails closed. The shared stop script never kills an unverified PID.

- [ ] **Step 6: Integrate evidence and acceptance**

After the two-stage handshake, wait for the observer in both modes and the scheduler only in phased mode to discover topics and become ready. Copy/hashes include both handshake markers, model evidence, JSONL logs, summaries and readiness markers. `evidence_accepted` for new phase trials requires clean auxiliary stops; general historical v3 scoring remains unchanged.

- [ ] **Step 7: Run focused and existing renderer/takeoff regressions**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_vio_stress_runner.py tests/test_vio_stress_summary.py tests/test_renderer_stability.py tests/test_takeoff_stability_campaign.py -q`

Expected: PASS.

- [ ] **Step 8: Commit trial integration**

```bash
git add tools/launch_px4_depth_swarm_wsl.sh tools/run_vio_stress_trial_wsl.py tools/summarize_vio_stress_wsl.py tools/stop_px4_swarm_wsl.sh tests/test_vio_stress_runner.py tests/test_vio_stress_summary.py
git commit -m "Integrate camera phase trial evidence"
```

### Task 7: Frozen Paired Camera-Phase Campaign

**Files:**
- Create: `src/flydrones/camera_phase_stability.py`
- Create: `configs/vio_camera_phase_stability.json`
- Create: `tools/run_camera_phase_stability_campaign_wsl.py`
- Create: `tests/test_camera_phase_stability.py`
- Modify: `tools/snapshot_vio_gate_results.py`
- Modify: `tests/test_renderer_stability_campaign.py`

**Interfaces:**
- Consumes: Task 6 trial/summary, existing renderer trial metrics and frozen hashes.
- Produces: `CameraPhaseRun`, `smoke_schedule() -> tuple[CameraPhaseRun, ...]`, `formal_schedule(config: Mapping[str, object]) -> tuple[CameraPhaseRun, ...]`, `score_phase_trial(manifest: Mapping[str, object], summary: Mapping[str, object], config: Mapping[str, object]) -> dict[str, object]`, `score_phase_campaign(trials: Sequence[Mapping[str, object]], config: Mapping[str, object]) -> dict[str, object]`, immutable smoke/formal orchestration and compact snapshots.

- [ ] **Step 1: Write failing schedule and resume tests**

Assert the exact three-run smoke and ten-run alternating formal schedule from the spec, five unique pairs, D3D12 only, no overwrite, resume only complete matching trials, and rejection of mode/threshold/hash/schedule drift.

- [ ] **Step 2: Write failing single-trial scoring tests**

Require all existing mission, landing, takeoff, EV, renderer, absolute timing, RTF and cleanup gates. Phased additionally requires the phase hard gates. Any auxiliary fault injection in a formal manifest fails validation. A missing phase summary must use a specific reason.

- [ ] **Step 3: Write failing campaign scoring tests**

Pin:

- five phased trials and five valid pairs;
- existing three-run >5 ms sustained-degradation rule;
- at least 4/5 negative paired max-tail deltas;
- paired max-tail median `<= -5 ms`;
- p99 median degradation `<=2 ms`;
- RTF median degradation `<=0.01`;
- the three distinct verdicts: `supported`, `operational_but_not_proven`, `rejected`.

- [ ] **Step 4: Write failing fail-fast tests**

A single-trial operational, phase, evidence or cleanup failure in either mode stops and preserves the campaign. Simultaneous campaign-level trend is reported but does not stop an otherwise valid control sequence.

- [ ] **Step 5: Implement scoring and campaign runner**

Mirror existing immutable campaign patterns without modifying `renderer_stability.py`. Config contains exact phase, absolute, efficacy and schedule thresholds plus expected hashes for every new and changed source.

- [ ] **Step 6: Extend compact snapshots**

Add `snapshot_camera_phase_campaign(source, target)`. Copy compact manifests, stress summaries, model evidence, phase summary and cleanup/renderer attestations. Index scheduler/probe JSONL, ULogs, CSV, console logs, world and model copies by SHA-256/size without committing them.

- [ ] **Step 7: Run campaign, snapshot and hash tests**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase_stability.py tests/test_renderer_stability_campaign.py -q`

Run: `python tools/run_camera_phase_stability_campaign_wsl.py --help`

Expected: PASS.

- [ ] **Step 8: Run all automated quality gates before live work**

Run: `$env:PYTHONPATH='src;.'; python -m pytest -q --deselect tests/test_distributed_stress.py::test_four_independent_udp_processes_converge`

Run the deselected test alone, targeted Ruff on every changed Python file, and `git diff --check`.

Expected: main suite PASS, isolated known intermittent test PASS, Ruff PASS and clean diff.

- [ ] **Step 9: Commit the frozen campaign**

```bash
git add src/flydrones/camera_phase_stability.py configs/vio_camera_phase_stability.json tools/run_camera_phase_stability_campaign_wsl.py tools/snapshot_vio_gate_results.py tests/test_camera_phase_stability.py tests/test_renderer_stability_campaign.py
git commit -m "Add frozen camera phase campaign"
```

### Task 8: Development Runs, Formal Campaign, Conditional Faults and Report

**Files:**
- Modify after verified live runs: `configs/vio_camera_phase_stability.json` expected hashes only
- Create: `docs/CAMERA_PHASE_STABILITY_REPORT.md`
- Create: `docs/results/camera-phase/<development-or-fault-id>/...`
- Create: `docs/results/camera-phase-stability/<smoke-id>/...`
- Create: `docs/results/camera-phase-stability/<formal-id>/...`

**Interfaces:**
- Consumes: Tasks 1–7, `configs/vio_fault_profiles/baseline.json`, `delay-120ms.json`, `dropout-400ms.json`, and the frozen policy checkpoint.
- Produces: preserved raw trials, compact snapshots, formal verdict, conditional fault results, final report and released resources.

- [ ] **Step 1: Verify revisions and resource ownership**

Record FlyDrones/PX4 revisions, Gazebo/gz-sensors/Mesa/driver versions, renderer, model/policy/profile/config hashes and compatibility evidence. Confirm no relevant owned or foreign PX4, Gazebo, relay, scheduler, probe, worker or training process is active; do not terminate foreign processes.

- [ ] **Step 2: Run phased single-vehicle development validation**

Use a new id. Inspect actual image rate/phase, renderer attestation, command ACK, mission-ready, motor/physics/EKF chain, mission, landing, auxiliary stop and cleanup evidence.

- [ ] **Step 3: Run phased five-vehicle development validation**

Use a new id. Require all five targets `0/20/40/60/80 ms`, all phase gates, `5/5` mission/landing and clean resources.

- [ ] **Step 4: Run scheduler-failure development validation**

Use the explicit development fault option with a new id. Verify the failure is preserved, workers never start when failure occurs before readiness, or stale-depth safety landing occurs if injected after start. It must never count as a formal result.

- [ ] **Step 5: Amend before any behavioral correction**

If development Steps 2–4 expose a live failure, classify it as compatibility, topology, schedule, output phase, controller safety or cleanup. Preserve the run and write a reviewed amendment before changing behavior. After correction, repeat Task 7 Steps 7–8 and all three development scenarios with new ids.

- [ ] **Step 6: Freeze hashes once**

After all development scenarios behave as specified, update only `expected_hashes` in the camera-phase config from the calculator output. Run frozen-hash tests and commit:

```bash
git add configs/vio_camera_phase_stability.json
git commit -m "Freeze camera phase experiment inputs"
```

- [ ] **Step 7: Run new smoke campaign**

Run all three smoke trials with a new campaign id. Require complete phase/model/renderer/actuator/ULog/cleanup evidence. Stop at the first failure and return to the amendment boundary.

- [ ] **Step 8: Run the complete ten-trial formal campaign**

Start with a new formal id and run all alternating pairs from trial 1. Do not reuse previous D3D12 campaigns. Preserve every control and treatment outcome and apply the frozen three-way verdict.

- [ ] **Step 9: Run conditional VIO fault regressions**

Only when the formal verdict is `supported`, run phased five-vehicle trials with `delay-120ms.json` and `dropout-400ms.json` on the same commit/config. Reuse the existing VIO safety-gate acceptance contract: prove injection at relay and PX4, fail-closed behavior for the affected vehicle, safe landing, unaffected-vehicle behavior and cleanup. If the verdict is not supported, record both as not run due to the frozen prerequisite.

- [ ] **Step 10: Publish compact evidence**

Generate camera-phase snapshots. Verify every raw index entry against the local file, and verify every bounded sequence's length, head/tail and canonical SHA-256. Do not stage ULog, CSV, JSONL, HTML or console logs.

- [ ] **Step 11: Write the report**

List every smoke/formal/fault run, phase fidelity, all failures, paired deltas, aggregate gates, actual renderer evidence, resource metrics, software revisions and raw locations. State the exact verdict and limitations: Gazebo physics, truth-relay EV surrogate, wall-clock measurements, slow-simulation behavior, no real camera VIO, no HITL and no flight.

- [ ] **Step 12: Run final verification and resource check**

Run the full suite with the known intermittent test isolated, all focused tests, targeted Ruff, `git diff --check`, compact-index verification and Windows/WSL process inspection.

- [ ] **Step 13: Commit report and evidence**

```bash
git add docs/CAMERA_PHASE_STABILITY_REPORT.md docs/results/camera-phase docs/results/camera-phase-stability tools/snapshot_vio_gate_results.py
git commit -m "Report camera phase stability experiment"
```
