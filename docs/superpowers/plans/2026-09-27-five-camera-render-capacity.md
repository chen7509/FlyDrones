# Five-Camera Sustained Render Capacity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether the current five-camera real-time failure is caused by the Python Gazebo Transport observer or by sustained rendering/Transport capacity, then integrate a native scheduler-observer only when all native five-camera repetitions meet the frozen gates.

**Architecture:** Add a standalone gz-transport13 C++ executable that records the same bounded camera-phase metadata as the Python tools and can optionally publish the existing simulation-clock trigger schedule. A dedicated no-worker trial runner keeps five PX4 instances disarmed while four immutable load cells run three times each; one Python scorer owns all acceptance and root-cause classification. Production integration and one flight development rerun are conditional on three `native-5` passes.

**Tech Stack:** Python 3.12, C++17, CMake 3.28, CTest, gz-transport13 13.6.0, gz-msgs10 10.4.0, Gazebo Sim 8.15.0, PX4 SITL, pytest, Ruff, WSL2.

**Spec:** `docs/superpowers/specs/2026-09-27-five-camera-render-capacity-design.md`

## Global Constraints

- This is roadmap substage A0. It does not complete roadmap stage 0, stage 1, or real VIO stage 2.
- Keep PX4 revision `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` and implementation base `cba7d03eea0d9defa868599895578d3f89ca0e02` recorded in every live manifest.
- Keep five vehicles, 4 ms physics steps, D3D12 NVIDIA renderer, 160 x 120 `R_FLOAT32` depth, 10 Hz, and phase offsets `0/20/40/60/80 ms`.
- Keep RTF `>=0.95`, image frequency `9.5..10.5 Hz`, p95 phase error `<=8 ms`, and adjacent median-spacing error `<=8 ms` as inclusive gates.
- Capacity runs use 30 scored simulation seconds and a 120 second wall-clock timeout after the scoring epoch; PX4 remains disarmed and no mission worker starts.
- Do not change the policy, checkpoint, reward, safety supervisor, PX4 inner loop, vehicle dynamics, camera properties, takeoff timeout, or formal acceptance rules.
- Do not add a new external dependency or fork Gazebo. Use installed gz-transport13, gz-msgs10, Threads, CMake, and the standard library.
- Preserve every scheduled live run, including startup, integrity, timeout, and cleanup failures. Never replace a failed schedule slot silently.
- Raw ULogs, CSV, JSONL, console logs, worlds, and model copies remain under `results/`; Git receives compact evidence and a complete SHA-256/size index.
- Truth-relay external vision remains labeled as a Gazebo surrogate. Nothing in this plan is HITL, real VIO, or flight evidence.

## Review Focus

- A zero-subscriber cell must prove that no depth subscriber exists during the scored interval while still observing every trigger; Task 4 tests the manifest and readiness distinction.
- A native callback must not retain or copy `Image.data()` and must fail on queue overflow rather than hide loss; Task 2 tests payload handling and bounded-queue overflow.
- A skipped or repeated `/clock` timestamp must produce exactly the same trigger slots as Python or a stable failure; Tasks 1 and 2 share boundary fixtures.
- Completion arriving before readiness must create an immutable failed run and still release all owned processes; Task 4 tests this path.
- Three individually valid but thermally unstable repetitions with RTF range above `0.03` must be `non_monotonic_or_inconclusive`; Task 1 tests this classification.

---

## File map

- `src/flydrones/camera_render_capacity.py`: immutable schedule, thresholds, per-run scoring, and twelve-run classification.
- `tests/test_camera_render_capacity.py`: pure contract, scoring, and classification tests.
- `tests/fixtures/camera_phase_vectors.json`: shared Python/C++ simulation-clock boundary vectors.
- `native/camera_phase/CMakeLists.txt`: standalone native build and CTest registration.
- `native/camera_phase/include/flydrones/camera_phase_native.hpp`: option, schedule, event, bounded-queue, and lifecycle interfaces.
- `native/camera_phase/src/camera_phase_native.cc`: schedule, subscriptions, queue, writer, readiness, completion, and shutdown implementation.
- `native/camera_phase/src/main.cc`: CLI parsing and stable exit-code mapping.
- `native/camera_phase/tests/camera_phase_native_test.cc`: native unit tests using the shared vectors.
- `tools/build_camera_phase_native_wsl.sh`: reproducible out-of-tree build and executable hash output.
- `tests/test_camera_phase_native_contract.py`: repository/build-script and shared-fixture contract tests.
- `configs/five_camera_render_capacity.json`: frozen twelve-run schedule, thresholds, versions, and expected hashes.
- `tools/run_camera_render_capacity_trial_wsl.py`: one no-worker capacity cell with immutable evidence and cleanup.
- `tests/test_camera_render_capacity_trial.py`: command, readiness, timeout, cleanup, and manifest tests.
- `tools/run_camera_render_capacity_campaign_wsl.py`: resumable twelve-slot orchestration and final classification.
- `tests/test_camera_render_capacity_campaign.py`: schedule, resume, resource exclusion, hash, and stop-condition tests.
- `tools/run_vio_stress_trial_wsl.py`: conditional native auxiliary selection for the existing flight development gate.
- `tests/test_vio_stress_runner.py`: conditional integration and unchanged Python default tests.
- `tools/snapshot_vio_gate_results.py`: compact capacity snapshot and raw index.
- `tests/test_renderer_stability_campaign.py`: capacity snapshot coverage.
- `docs/FIVE_CAMERA_RENDER_CAPACITY_REPORT.md`: final outcome and limitations after live execution.

### Task 1: Freeze capacity schedule and classification

**Files:**
- Create: `src/flydrones/camera_render_capacity.py`
- Create: `tests/test_camera_render_capacity.py`
- Create: `tests/fixtures/camera_phase_vectors.json`

**Interfaces:**
- Produces: `CapacityCell(name: str, subscriber_count: int, implementation: str)`.
- Produces: `CapacityRun(name: str, cell: CapacityCell, repetition: int, sequence: int)`.
- Produces: `CapacityThresholds.from_mapping(value: Mapping[str, object]) -> CapacityThresholds`.
- Produces: `capacity_schedule() -> tuple[CapacityRun, ...]` with the exact twelve slots from the spec.
- Produces: `score_capacity_run(manifest: Mapping[str, object], summary: Mapping[str, object], thresholds: CapacityThresholds) -> dict[str, object]`.
- Produces: `classify_capacity_campaign(runs: Sequence[tuple[Mapping[str, object], Mapping[str, object]]], config: Mapping[str, object]) -> dict[str, object]`.
- Produces: shared fixture keys `sim_ns`, `expected_cycle`, `expected_vehicle_ids`, and `expected_planned_ns` for exact 4 ms boundary, repeated-clock, and skipped-clock cases.

- [ ] **Step 1: Write failing schedule and threshold tests**

Assert the exact row order `idle-0,native-1,python-5,native-5 / native-5,python-5,native-1,idle-0 / python-5,idle-0,native-5,native-1`, unique names, repetitions `1..3`, subscriber counts `0/1/5/5`, and inclusive spec thresholds. Assert unknown cells, booleans used as numbers, non-finite values, a changed schedule, and relaxed thresholds are rejected.

- [ ] **Step 2: Run the contract tests and confirm the missing module fails**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_render_capacity.py -q`

Expected: collection fails because `flydrones.camera_render_capacity` does not exist.

- [ ] **Step 3: Implement immutable contracts and exact schedule**

Use frozen dataclasses and deterministic reason ordering. Keep the shared clock vectors data-only so both Python and C++ tests consume the same expected values.

- [ ] **Step 4: Add failing per-run score tests**

Cover accepted `idle-0`, `native-1`, `python-5`, and `native-5` fixtures, then independently violate renderer attestation, PX4 health/disarmed state, scored duration, RTF `0.949999`, subscriber count, trigger completeness, 9.5/10.5 Hz inclusive boundaries, 8 ms phase/spacing boundaries, dimensions, format, integrity counters, cleanup, and source/executable hashes.

- [ ] **Step 5: Implement `score_capacity_run`**

Separate `evidence_valid` from `performance_pass`. An RTF failure remains a valid measured failure when all evidence and cleanup fields are intact.

- [ ] **Step 6: Add failing campaign classification tests**

Assert all five outcomes: `host_or_baseline_capacity_failure`, `python_transport_boundary`, `sustained_render_transport_capacity`, `mixed_python_and_render_capacity`, and `non_monotonic_or_inconclusive`. Pin median improvement at `0.05`, repetition RTF range at `0.03`, missing/duplicate identities, and the rule that every individual `native-5` run must pass.

- [ ] **Step 7: Implement `classify_capacity_campaign` and run tests**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_render_capacity.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/flydrones/camera_render_capacity.py tests/test_camera_render_capacity.py tests/fixtures/camera_phase_vectors.json
git commit -m "Add camera render capacity contract"
```

### Task 2: Build the native schedule and metadata probe

**Files:**
- Create: `native/camera_phase/CMakeLists.txt`
- Create: `native/camera_phase/include/flydrones/camera_phase_native.hpp`
- Create: `native/camera_phase/src/camera_phase_native.cc`
- Create: `native/camera_phase/src/main.cc`
- Create: `native/camera_phase/tests/camera_phase_native_test.cc`
- Create: `tools/build_camera_phase_native_wsl.sh`
- Create: `tests/test_camera_phase_native_contract.py`

**Interfaces:**
- Consumes: `tests/fixtures/camera_phase_vectors.json` and the event field names accepted by `summarize_camera_phase`.
- Produces: executable `build/native-camera-phase/flydrones_camera_phase_native`.
- Produces: CLI modes `observe` and `schedule-observe`; options `--vehicle-count`, `--subscriber-count`, `--output`, `--ready-marker`, `--completion-marker`, `--duration-s`, `--poll-interval-ms`, `--flush-interval-ms`, `--completion-drain-ms`, and `--stop-after-trigger-count`.
- Produces: stable exits `0=complete`, `2=queue/integrity rejection`, `3=startup/runtime failure`, `4=directed scheduler failure`, `64=invalid CLI`.
- Produces: `TriggerScheduler::Advance(std::int64_t simNs) -> std::vector<TriggerSlot>` and `BoundedEventQueue::TryPush(EventRecord) -> bool`.

- [ ] **Step 1: Write failing repository contract tests**

Assert the CMake target name, C++17, exact allowed `find_package` dependencies, out-of-tree build location, no vendored source, no `Image.data()` copy/access in the callback implementation, and build-script refusal when required pkg-config packages are missing.

- [ ] **Step 2: Run tests and confirm the native files are absent**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase_native_contract.py -q`

Expected: failures identify the missing native project and build script.

- [ ] **Step 3: Add native interfaces, CMake target, and CLI shell**

Keep transport ownership RAII-based. Store callbacks for the executable lifetime. `EventRecord` contains metadata only: event kind, vehicle, cycle, topic, source/receipt simulation timestamps, monotonic receipt, sequence, width, height, and format.

- [ ] **Step 4: Write failing native unit tests**

Use the shared vectors to test phase scheduling at 4 ms boundaries, repeated clock values, skipped cycles, one-trigger-per-slot, stable vehicle ordering, queue high watermark, overflow rejection, unique stop record, completion-before-readiness, and SIGTERM-equivalent shutdown state.

- [ ] **Step 5: Implement schedule, bounded queue, and lifecycle state machine**

The callback may inspect protobuf metadata and `ByteSizeLong()` but must never read, copy, or retain `Image.data()`. One writer thread emits the existing JSONL fields plus native CPU/high-watermark/build metadata and flushes every 250 ms.

- [ ] **Step 6: Implement Transport observe and schedule-observe modes**

Use separate `gz::transport::Node` instances per selected image stream, plus clock and trigger nodes. Readiness requires exact topic mapping, connected trigger publishers in schedule mode, expected subscribers, and the configured warmup condition; `subscriber_count=0` must never subscribe to a depth topic.

- [ ] **Step 7: Build and run native tests in WSL**

Run: `wsl.exe bash tools/build_camera_phase_native_wsl.sh --test`

Expected: CMake configures against gz-transport13/gz-msgs10, CTest passes, and the script prints the executable path and SHA-256.

- [ ] **Step 8: Run Python contract tests and CLI validation**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase_native_contract.py tests/test_camera_phase.py -q`

Run: `wsl.exe build/native-camera-phase/flydrones_camera_phase_native --help`

Expected: tests pass and help exits 0; an unknown mode exits 64.

- [ ] **Step 9: Commit**

```bash
git add native/camera_phase tools/build_camera_phase_native_wsl.sh tests/test_camera_phase_native_contract.py
git commit -m "Add native camera phase metadata probe"
```

### Task 3: Prove Python/C++ scoring parity

**Files:**
- Modify: `native/camera_phase/tests/camera_phase_native_test.cc`
- Modify: `src/flydrones/camera_phase.py`
- Modify: `tests/test_camera_phase.py`
- Create: `tools/verify_camera_phase_native_parity.py`
- Create: `tests/test_camera_phase_native_parity.py`

**Interfaces:**
- Consumes: native replay JSONL generated from the shared fixture and `summarize_camera_phase(...)`.
- Produces: `canonical_phase_score_fields(summary: Mapping[str, object]) -> dict[str, object]`.
- Produces: parity command that compares Python-generated and native-generated fixtures and exits nonzero on any canonical field difference.

- [ ] **Step 1: Write failing canonical-field and parity tests**

Pin mode, vehicle count, epoch, offsets, per-vehicle counts/frequency/p50/p95/max, spacing error, simultaneous-camera count, and every integrity counter. Include shuffled JSONL, malformed records, one unmatched image, and a native build/hash mismatch.

- [ ] **Step 2: Run the parity tests and confirm failure**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase.py tests/test_camera_phase_native_parity.py -q`

Expected: failures identify the missing canonical helper and verifier.

- [ ] **Step 3: Implement canonical extraction and verifier**

Keep all acceptance arithmetic in Python. The native side emits facts only and cannot declare its own phase acceptance.

- [ ] **Step 4: Extend CTest to export the shared-vector native JSONL fixture**

The fixture command must be deterministic and must not require Gazebo to be running.

- [ ] **Step 5: Run cross-language verification**

Run: `wsl.exe bash tools/build_camera_phase_native_wsl.sh --test`

Run: `$env:PYTHONPATH='src;.'; python tools/verify_camera_phase_native_parity.py --native-executable build/native-camera-phase/flydrones_camera_phase_native`

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_phase.py tests/test_camera_phase_native_parity.py -q`

Expected: all commands pass and canonical score fields are identical.

- [ ] **Step 6: Commit**

```bash
git add native/camera_phase/tests/camera_phase_native_test.cc src/flydrones/camera_phase.py tests/test_camera_phase.py tools/verify_camera_phase_native_parity.py tests/test_camera_phase_native_parity.py
git commit -m "Verify native camera phase parity"
```

### Task 4: Add one-cell no-worker capacity runner

**Files:**
- Create: `tools/run_camera_render_capacity_trial_wsl.py`
- Create: `tests/test_camera_render_capacity_trial.py`
- Modify: `tools/launch_px4_depth_swarm_wsl.sh`
- Modify: `tools/probe_gazebo_runtime_wsl.py`
- Modify: `tools/stop_px4_swarm_wsl.sh`

**Interfaces:**
- Consumes: `CapacityRun`, the native executable, existing Python scheduler/probe, PX4 launcher, runtime probe, renderer attestation, process registry, and stopper.
- Produces: `run_capacity_trial(*, run: CapacityRun, config: Mapping[str, object], output_root: Path, native_executable: Path) -> dict[str, object]`.
- Produces: schemas `flydrones-camera-render-capacity-manifest-v1` and `flydrones-camera-render-capacity-summary-v1`.
- Produces: scored-epoch marker with start simulation time, start monotonic time, target simulation duration 30 seconds, and wall timeout 120 seconds.
- Produces: `depth-topic-connections.json` captured with `gz topic -i -t <topic>` after temporary renderer attestation exits and again at scored-window completion.

- [ ] **Step 1: Write failing command and manifest tests**

Assert exact auxiliary commands for all four cells. `idle-0` uses native observe mode with zero image subscribers; `native-1` selects vehicle 0 only; `python-5` uses the existing Python observer; `native-5` uses native observe mode with all vehicles. All cells use the unchanged Python simulation-clock scheduler during diagnosis. Mock topic-info output to prove zero, one, duplicate, and unexpected external depth subscribers.

- [ ] **Step 2: Write failing lifecycle tests**

Use fake processes and markers to cover: occupied resources, renderer rejection, PX4 not healthy/disarmed, wrong subscriber count, readiness timeout, completion before readiness, simulation duration completion, 120 second wall timeout, observer early exit, runtime probe early exit, stopper failure, shared-file restoration failure, and owned-process cleanup. Assert no worker command is ever constructed.

- [ ] **Step 3: Run tests and confirm the runner is missing**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_render_capacity_trial.py -q`

Expected: collection or interface failures identify the missing runner.

- [ ] **Step 4: Add capacity-only launcher handshake**

Allow the existing launcher to accept an explicit capacity-ready schema while preserving the current mission path as the default. After the temporary 11-frame renderer attestation exits, the launcher captures `gz topic -i` for every depth topic, records the selected observer PID, proves the exact external image subscriber count, and records PX4 disarmed/landed health before it declares capacity readiness. Repeat topic introspection at the end of the scored window; any extra subscriber invalidates the run.

- [ ] **Step 5: Implement `run_capacity_trial`**

Copy the world/model/config into a fresh output, record software and source hashes, start runtime/resource/GPU probes, launch Gazebo/PX4, start auxiliaries, wait for readiness, mark the scoring epoch, wait for 30 simulation seconds, and perform the existing ownership-safe cleanup. Do not import or call the mission worker.

- [ ] **Step 6: Emit summary and fail-closed evidence**

Reuse `summarize_camera_phase` for image cells. For `idle-0`, emit trigger-only integrity plus explicit `depth_subscription_absent=true`. Record native callback/writer CPU, queue high watermark, payload bytes seen, Gazebo CPU/RSS, full scored-window RTF, renderer evidence, PX4 states, ULog paths, and all exit codes.

- [ ] **Step 7: Run trial tests and existing launcher regressions**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_render_capacity_trial.py tests/test_vio_stress_runner.py tests/test_process_ownership.py -q`

Run: `wsl.exe bash -n tools/launch_px4_depth_swarm_wsl.sh tools/stop_px4_swarm_wsl.sh`

Expected: all tests and shell syntax checks pass.

- [ ] **Step 8: Commit**

```bash
git add tools/run_camera_render_capacity_trial_wsl.py tests/test_camera_render_capacity_trial.py tools/launch_px4_depth_swarm_wsl.sh tools/probe_gazebo_runtime_wsl.py tools/stop_px4_swarm_wsl.sh
git commit -m "Add no-worker camera capacity trial"
```

### Task 5: Freeze and orchestrate the twelve-run campaign

**Files:**
- Create: `configs/five_camera_render_capacity.json`
- Create: `tools/run_camera_render_capacity_campaign_wsl.py`
- Create: `tests/test_camera_render_capacity_campaign.py`
- Modify: `tests/test_camera_render_capacity.py`

**Interfaces:**
- Consumes: `capacity_schedule`, `run_capacity_trial`, `score_capacity_run`, and `classify_capacity_campaign`.
- Produces: `build_capacity_campaign_manifest(config: Mapping[str, object], *, campaign_id: str, frozen_hashes: Mapping[str, str]) -> dict[str, object]`.
- Produces: `execute_capacity_campaign(*, config_path: Path, output_root: Path, campaign_id: str, native_executable: Path) -> dict[str, object]`.
- Produces: campaign schemas `flydrones-camera-render-capacity-campaign-v1` and `flydrones-camera-render-capacity-campaign-summary-v1`.

- [ ] **Step 1: Write failing config and manifest tests**

Pin versions, four cells, twelve-slot order, thresholds, 30/120 second durations, D3D12 profile, five vehicles, exact model/profile/policy paths, PX4 revision, and hashes for every changed Python/C++/shell/config input plus the native executable.

- [ ] **Step 2: Write failing resume and resource tests**

Assert that matching completed slots resume without rerun, a partial slot remains failed and is not reused, changed config/hash/schedule/campaign identity is rejected, only one slot starts at a time, and any matching PX4/Gazebo/observer/scheduler process blocks startup without being terminated.

- [ ] **Step 3: Run tests and confirm failure**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_render_capacity.py tests/test_camera_render_capacity_campaign.py -q`

Expected: failures identify missing config, manifest, and runner.

- [ ] **Step 4: Implement frozen config and campaign runner**

Write the campaign manifest before slot 1. After each slot, validate immutable identity, score it, append its path and score atomically, and verify resources are free. Always continue through the twelve frozen slots unless cleanup/resources are unsafe or user interruption occurs.

- [ ] **Step 5: Implement final classification and stop decision**

Require exactly twelve identities before classification. Write all per-run RTF values, ranges, medians, paired cell deltas, failures, and one root-cause code. Set `production_integration_eligible=true` only for `python_transport_boundary` with three individual native passes.

- [ ] **Step 6: Run tests and CLI checks**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_camera_render_capacity.py tests/test_camera_render_capacity_campaign.py tests/test_camera_render_capacity_trial.py -q`

Run: `python tools/run_camera_render_capacity_campaign_wsl.py --help`

Expected: all tests pass and help exits 0 without external processes.

- [ ] **Step 7: Freeze actual hashes after all prior commits**

Run the campaign runner's `--print-frozen-hashes` mode, update only `expected_hashes`, rerun the hash test, and commit.

- [ ] **Step 8: Commit**

```bash
git add configs/five_camera_render_capacity.json tools/run_camera_render_capacity_campaign_wsl.py tests/test_camera_render_capacity.py tests/test_camera_render_capacity_campaign.py
git commit -m "Add frozen camera render capacity campaign"
```

### Task 6: Validate native live integration before the campaign

**Files:**
- Modify only when a verified defect is found: files owned by Tasks 2-5
- Create only after a defect is proven: `docs/superpowers/specs/2026-09-27-five-camera-render-capacity-amendment-N.md`
- Produce raw evidence: `results/camera-render-capacity/dev-native-single-<timestamp>/`
- Produce raw evidence: `results/camera-render-capacity/dev-native-five-<timestamp>/`
- Produce raw evidence: `results/camera-render-capacity/dev-native-fault-<timestamp>/`

**Interfaces:**
- Consumes: the frozen build, trial runner, and scorer.
- Produces: one-camera, five-camera, and directed native-process-failure development evidence.

- [ ] **Step 1: Verify resources are free and build identity is frozen**

Run read-only Windows and WSL process checks for PX4, Gazebo, relay, scheduler, observer, and worker roles. Build with `tools/build_camera_phase_native_wsl.sh --test` and record the executable SHA-256 in the development manifests.

- [ ] **Step 2: Run one native-camera development cell**

Expected: one exact subscriber, 30 scored simulation seconds, 9.5..10.5 Hz, p95 phase `<=8 ms`, RTF evidence, clean stop, and no worker artifacts.

- [ ] **Step 3: Run five native-camera development cell**

Expected: five exact subscribers, all phase/integrity evidence, RTF measurement, PX4 disarmed health, complete cleanup, and no worker artifacts. This is integration validation, not one of the twelve frozen campaign slots.

- [ ] **Step 4: Run directed native failure before readiness**

Terminate or direct-stop the native process after exactly five triggers. Expected: no scored capacity result is synthesized, the launcher/trial fails closed, all owned processes stop, shared files restore, and the failure record remains.

- [ ] **Step 5: Apply the no-guessing rule**

If a development run exposes a defect, preserve it, identify one root cause, write and review one amendment, add a failing regression, implement one correction, and restart all three development checks with new IDs. Do not alter live behavior without the amendment.

- [ ] **Step 6: Commit only reviewed corrections and final frozen hashes**

Expected: unit/contract tests, CTest, Ruff, shell syntax, and `git diff --check` pass; development evidence remains raw and untracked until snapshot Task 9.

### Task 7: Execute and classify the frozen twelve-run campaign

**Files:**
- Do not modify source or config during this task.
- Produce: `results/camera-render-capacity/<campaign-id>/campaign-manifest.json`
- Produce: `results/camera-render-capacity/<campaign-id>/campaign-summary.json`
- Produce: twelve immutable slot directories.

**Interfaces:**
- Consumes: `execute_capacity_campaign` with frozen config and native executable.
- Produces: one of the five root-cause classifications and the conditional-integration flag.

- [ ] **Step 1: Run preflight verification**

Require clean tracked files, matching hashes, expected PX4 revision, CTest and targeted pytest pass, D3D12 renderer availability, no relevant processes, and enough disk space for twelve raw runs.

- [ ] **Step 2: Start the campaign once**

Run the frozen campaign command with a new immutable campaign ID. Do not launch another campaign while it runs.

- [ ] **Step 3: Preserve and validate every slot**

After each slot, check exact identity, evidence validity, cleanup, and resource release before proceeding. Record failed performance slots without replacement. Stop only for unsafe cleanup/resource ownership, corrupted evidence, user interruption, or unrecoverable infrastructure failure.

- [ ] **Step 4: Generate and independently inspect classification**

Require twelve slot identities, all raw paths, cell medians/ranges, native-minus-Python deltas, every failure reason, and exactly one root-cause code. Independently recompute RTF medians and ranges from raw clock probes.

- [ ] **Step 5: Follow the classification branch exactly**

- `python_transport_boundary`: continue to Task 8.
- Any other classification: skip Task 8 production changes and proceed to Task 9 with a rejected or inconclusive verdict.

### Task 8: Conditionally integrate native schedule-observe and rerun one flight gate

**Files:**
- Modify: `tools/run_vio_stress_trial_wsl.py`
- Modify: `tests/test_vio_stress_runner.py`
- Modify: `configs/vio_camera_phase_stability.json`
- Modify: `tests/test_camera_phase_stability.py`
- Produce raw evidence: `results/camera-phase/dev-native-phased-five-<timestamp>/`

**Interfaces:**
- Consumes: Task 7 summary with `production_integration_eligible=true` and the exact native executable hash.
- Produces: `camera_auxiliary_implementation` manifest field with default `python` and explicit `native-cpp`.
- Produces: native `schedule-observe` command replacing both Python camera auxiliary processes only when configured.

- [ ] **Step 1: Write failing integration tests**

Assert the Python default remains byte-for-byte command compatible, native mode starts exactly one owned auxiliary process, hashes its executable, uses the existing ready/completion paths, never starts alongside Python auxiliaries, preserves directed scheduler failure, and projects no phase/image data into worker inputs.

- [ ] **Step 2: Run tests and confirm native selection is absent**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_vio_stress_runner.py tests/test_camera_phase_stability.py -q`

Expected: native-selection tests fail while existing Python tests pass.

- [ ] **Step 3: Implement explicit native auxiliary selection**

Reject native mode unless the executable exists, its SHA-256 matches the frozen config, and Task 7's campaign summary is present and eligible. Preserve all existing scoring and cleanup paths.

- [ ] **Step 4: Run regression and native build checks**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_vio_stress_runner.py tests/test_camera_phase_stability.py tests/test_camera_phase.py -q`

Run: `wsl.exe bash tools/build_camera_phase_native_wsl.sh --test`

Expected: all pass.

- [ ] **Step 5: Freeze changed source hashes and commit**

```bash
git add tools/run_vio_stress_trial_wsl.py tests/test_vio_stress_runner.py configs/vio_camera_phase_stability.json tests/test_camera_phase_stability.py
git commit -m "Use eligible native camera phase auxiliary"
```

- [ ] **Step 6: Run exactly one new five-vehicle development flight gate**

Keep the original checkpoint, profile, world, dynamics, 12 second takeoff deadline, mission, safety layer, and thresholds. Require `5/5` mission-ready, `5/5` landed, full and steady RTF `>=0.95`, accepted camera phase/renderer/actuator/ULog/cleanup evidence, and no policy or sensor changes.

- [ ] **Step 7: Stop on either result**

If it passes, record that the camera infrastructure development gate is restored; do not start smoke in this plan. If it fails, preserve the run and mark production integration rejected pending a separately reviewed amendment.

### Task 9: Snapshot evidence and report the verdict

**Files:**
- Modify: `tools/snapshot_vio_gate_results.py`
- Modify: `tests/test_renderer_stability_campaign.py`
- Create: `docs/FIVE_CAMERA_RENDER_CAPACITY_REPORT.md`
- Create: `docs/results/camera-render-capacity/<campaign-id>/...`

**Interfaces:**
- Consumes: campaign manifest/summary, twelve run directories, development evidence, and optional Task 8 flight-gate evidence.
- Produces: `snapshot_camera_render_capacity_campaign(source: Path, target: Path) -> dict[str, object]`.
- Produces: a report verdict of `accepted`, `rejected`, or `inconclusive` with the exact root-cause code.

- [ ] **Step 1: Write failing snapshot tests**

Require compact config/manifests/summaries, renderer/cleanup/phase evidence, native build identity, all twelve slot identities, and a raw index containing every omitted ULog/CSV/JSONL/log/world/model file exactly once with size and SHA-256. Reject missing or extra raw files.

- [ ] **Step 2: Run tests and confirm capacity snapshot is absent**

Run: `$env:PYTHONPATH='src;.'; python -m pytest tests/test_renderer_stability_campaign.py -q`

Expected: the new capacity snapshot test fails.

- [ ] **Step 3: Implement snapshot and run index verification**

After snapshot creation, independently recompute every indexed raw file size and SHA-256 and require exact set equality.

- [ ] **Step 4: Write the report**

List all twelve runs, medians/ranges/deltas, exact root cause, all failures, renderer and process-resource evidence, software revisions, raw/compact paths, cleanup, and the conditional flight-gate result if run. State that earlier near-real-time evidence used short subscriptions and that the current work does not prove real VIO, HITL, or flight.

- [ ] **Step 5: Run complete verification**

Run main pytest with the known independent UDP test deselected, run that UDP test alone, run CTest, run Ruff on changed Python, run both shell syntax checks, run `git diff --check`, verify compact indexes, and confirm no relevant Windows/WSL processes remain.

- [ ] **Step 6: Commit report and compact evidence**

```bash
git add tools/snapshot_vio_gate_results.py tests/test_renderer_stability_campaign.py docs/FIVE_CAMERA_RENDER_CAPACITY_REPORT.md docs/results/camera-render-capacity
git commit -m "Report five-camera render capacity diagnosis"
```

Do not stage raw `results/` directories.
