# Gazebo D3D12 Five-Vehicle Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an attested NVIDIA D3D12 rendering profile and use a frozen, paired five-vehicle PX4/Gazebo campaign to decide whether it removes the observed VIO and `/clock` tail stalls without weakening the safety gate.

**Architecture:** Keep renderer selection and attestation in a small Python module, launch one explicitly owned Gazebo server before five standalone PX4 instances, and extend the existing VIO trial runner with immutable renderer and timing evidence. A separate campaign module owns the fixed five-pair schedule and pass/fail rules so individual trial collection remains reusable and failed runs remain preserved.

**Tech Stack:** Python 3.10+, Bash under Ubuntu WSL, PX4 SITL, Gazebo Harmonic / OGRE2, Mesa D3D12 Gallium, GZ Transport Python bindings, pytest, Ruff, JSON/CSV/ULog evidence.

**Spec:** `docs/superpowers/specs/2026-09-26-gazebo-d3d12-five-vehicle-stability-design.md`

## Global Constraints

- The only formal experiment factor is `FLYDRONES_GZ_RENDER_PROFILE=default|d3d12-nvidia`.
- `d3d12-nvidia` means exactly `GALLIUM_DRIVER=d3d12` and `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA`; no silent fallback is valid.
- Freeze depth sensing at `160×120 @ 10 Hz`, seed `240901`, the current world, policy, PX4 configuration, speed, physics, controller, and 250 ms VIO freshness gate.
- Keep Gazebo truth labeled as an external-vision surrogate; this work is PX4/Gazebo physical simulation, not camera+IMU VIO, HITL, or flight evidence.
- Preserve every startup, mission, gate, timeout, cleanup, and attestation failure; never overwrite or dilute a failed formal run.
- Renderer variables may reach the Gazebo server and attestation probe only; all PX4 instances use standalone mode.
- Cleanup may terminate only processes whose PID and Linux start time were recorded by this run; never use broad `pkill` as the cleanup mechanism.
- Do not commit large ULogs, perf data, raw CSV, or replays; commit compact summaries and a SHA-256 index.
- A formal D3D12 pass requires five attested `5/5` mission and landing runs, zero safety violations, steady-state raw-VIO and `/clock` max below 250 ms, p99 at or below 100 ms, RTF at least 0.95, and passing 120 ms / 400 ms fault regressions.

## Review Focus

- D3D12 requested but Mesa selects Intel or `llvmpipe`: attestation must reject the trial before mission scoring (Task 1 tests).
- A stale PID file points at a reused PID: teardown must leave that unrelated process alive and report an ownership mismatch (Task 2 tests).
- A partial or malformed trial directory exists: campaign scoring must preserve it as a failure, never skip it or infer success (Task 4 tests).
- Startup stalls are excluded from steady-state percentiles: the report must still count them as startup reliability failures and keep full-run metrics (Task 3 tests).
- A campaign is resumed with changed hashes, profile order, or seed: the orchestrator must refuse to append trials and require a fresh campaign (Task 5 tests).

---

### Task 1: Renderer Profile and Attestation

**Files:**
- Create: `src/flydrones/gazebo_renderer.py`
- Create: `tools/attest_gazebo_renderer_wsl.py`
- Create: `tests/test_gazebo_renderer.py`

**Interfaces:**
- Produces: `RendererProfile(name: str, environment: dict[str, str], required_adapter: str | None, require_d3d12: bool)`.
- Produces: `resolve_renderer_profile(name: str) -> RendererProfile` for `default` and `d3d12-nvidia`; unknown names raise `ValueError`.
- Produces: `parse_egl_renderer(text: str) -> str | None`.
- Produces: `DepthObservation(width: int, height: int, frequency_hz: float, message_count: int)`.
- Produces: `evaluate_renderer_attestation(*, profile: RendererProfile, egl_renderer: str | None, mapped_libraries: Collection[str], depth_observations: Mapping[str, DepthObservation], expected_depth_topics: int, expected_width: int = 160, expected_height: int = 120, expected_frequency_hz: float = 10.0) -> dict[str, object]` with `accepted`, `reasons`, requested/actual renderer, library evidence, and topic/resolution/frequency evidence.
- Produces CLI: `python tools/attest_gazebo_renderer_wsl.py --profile NAME --gazebo-pid PID --expected-depth-topics N --output PATH`.

- [ ] **Step 1: Write failing profile and parser tests**

Add tests named `test_d3d12_profile_pins_nvidia_without_changing_default_environment`, `test_unknown_renderer_profile_is_rejected`, and `test_egl_parser_extracts_renderer` asserting the exact two environment variables, an empty renderer environment for `default`, and correct parsing of NVIDIA D3D12, Intel D3D12, and `llvmpipe` output.

- [ ] **Step 2: Run the new tests and verify failure**

Run: `python -m pytest tests/test_gazebo_renderer.py -q`

Expected: FAIL because `flydrones.gazebo_renderer` does not exist.

- [ ] **Step 3: Implement the profile model and EGL parser**

Implement the Task 1 signatures in `src/flydrones/gazebo_renderer.py`. Keep profile definitions constant and immutable; do not read ambient renderer variables while resolving a profile.

- [ ] **Step 4: Write failing attestation tests**

Add parametrized tests named `test_d3d12_attestation_rejects_wrong_backend_or_adapter`, `test_d3d12_attestation_requires_process_libraries_and_every_depth_stream`, and `test_default_attestation_records_backend_without_requiring_d3d12`. Cover `llvmpipe`, Intel D3D12, absent `libd3d12`/`libdxcore`, four of five depth topics, a topic that produces no sampled message, the wrong resolution, and frequency outside 9–11 Hz.

- [ ] **Step 5: Implement pure attestation and the WSL CLI**

The CLI must run `eglinfo -B` with only the selected renderer environment added, read `/proc/<pid>/maps`, list topics with `gz topic -l`, read JSON message metadata using `gz topic -e --json-output -t TOPIC -n 2`, and measure frequency with `gz topic -f -t TOPIC -d 2` under timeouts. It writes JSON atomically, exits 0 only for `accepted=true`, and never starts or stops Gazebo.

- [ ] **Step 6: Run targeted tests and Ruff**

Run: `python -m pytest tests/test_gazebo_renderer.py -q && python -m ruff check src/flydrones/gazebo_renderer.py tools/attest_gazebo_renderer_wsl.py tests/test_gazebo_renderer.py`

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/flydrones/gazebo_renderer.py tools/attest_gazebo_renderer_wsl.py tests/test_gazebo_renderer.py
git commit -m "Add Gazebo renderer attestation"
```

### Task 2: Owned Gazebo Launch and Teardown

**Files:**
- Create: `src/flydrones/process_ownership.py`
- Create: `tools/stop_owned_processes_wsl.py`
- Modify: `tools/launch_px4_depth_swarm_wsl.sh`
- Modify: `tools/stop_px4_swarm_wsl.sh`
- Create: `tests/test_process_ownership.py`
- Create: `tests/wsl/test_px4_depth_process_ownership.sh`

**Interfaces:**
- Consumes: `resolve_renderer_profile` and the Task 1 attestation CLI.
- Produces: `ProcessIdentity(pid: int, start_ticks: int, argv: tuple[str, ...], role: str)` serialized in `$FLYDRONES_PX4_RUN_DIR/owned-processes.json`.
- Produces: `read_process_identity(pid: int, proc_root: Path = Path('/proc')) -> ProcessIdentity` and `identity_matches(record: ProcessIdentity, proc_root: Path = Path('/proc')) -> bool`.
- Produces CLI: `python tools/stop_owned_processes_wsl.py --registry PATH --timeout-s 2.0`, returning nonzero when a live PID no longer matches its recorded start time or command.

- [ ] **Step 1: Write failing process-identity tests**

Add tests for parsing `/proc/<pid>/stat` when the process name contains spaces or parentheses, matching an unchanged PID/start time/argv, rejecting a reused PID, rejecting a changed command, and reporting a missing process as already stopped.

- [ ] **Step 2: Run the process tests and verify failure**

Run: `python -m pytest tests/test_process_ownership.py -q`

Expected: FAIL because `flydrones.process_ownership` does not exist.

- [ ] **Step 3: Implement process identity and owned teardown**

Use `/proc/<pid>/stat` field 22 for Linux start ticks and `/proc/<pid>/cmdline` for argv. The stop CLI sends TERM only to matching live identities, waits up to the supplied timeout, sends KILL only to the same still-matching identities, and writes `cleanup-evidence.json` with stopped, already-gone, and ownership-mismatch entries.

- [ ] **Step 4: Replace implicit Gazebo startup with one explicit server**

In `launch_px4_depth_swarm_wsl.sh`, validate `FLYDRONES_GZ_RENDER_PROFILE`, refuse occupied ports/processes instead of killing them, source PX4's Gazebo environment, start `gz sim -r -s "$world_target"` under the selected renderer environment, record its identity, and start all PX4 instances with `PX4_GZ_STANDALONE=1`. Record the relay, every PX4 PID, and every matching `px4-gz_bridge --instance N` PID with its start time in the same registry; readiness requires exactly the expected five bridge instances.

- [ ] **Step 5: Add post-startup renderer attestation and fail closed**

After all expected depth topics appear, call the Task 1 CLI with the recorded Gazebo PID. For `d3d12-nvidia`, attestation failure must exit 3 after owned cleanup; for `default`, save the observed backend without requiring D3D12. Copy `renderer-attestation.json` into the run directory before reporting ready.

- [ ] **Step 6: Remove broad cleanup and add the WSL ownership harness**

Change `stop_px4_swarm_wsl.sh` to invoke the owned-process CLI and then restore backed-up shared PX4 files. The WSL harness starts two registered `sleep` processes and one unregistered process, runs cleanup, asserts only registered processes stop, then writes a stale start time for the survivor and asserts cleanup reports mismatch without killing it.

- [ ] **Step 7: Run unit and WSL integration checks**

Run:

```bash
python -m pytest tests/test_process_ownership.py tests/test_gazebo_renderer.py -q
python -m ruff check src/flydrones/process_ownership.py tools/stop_owned_processes_wsl.py tests/test_process_ownership.py
bash tests/wsl/test_px4_depth_process_ownership.sh
```

Expected: Python tests pass, Ruff is clean, the WSL harness exits 0, and its unregistered process remains alive until the harness removes it.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/flydrones/process_ownership.py tools/stop_owned_processes_wsl.py tools/launch_px4_depth_swarm_wsl.sh tools/stop_px4_swarm_wsl.sh tests/test_process_ownership.py tests/wsl/test_px4_depth_process_ownership.sh
git commit -m "Launch and stop owned Gazebo processes"
```

### Task 3: Immutable Trial Manifest and Runtime Probes

**Files:**
- Create: `src/flydrones/runtime_timing.py`
- Create: `tools/probe_gazebo_runtime_wsl.py`
- Modify: `tools/run_vio_stress_trial_wsl.py`
- Modify: `tools/summarize_vio_stress_wsl.py`
- Modify: `tests/test_vio_stress_runner.py`
- Modify: `tests/test_vio_stress_summary.py`
- Create: `tests/test_runtime_timing.py`

**Interfaces:**
- Consumes: renderer attestation and owned cleanup artifacts from Tasks 1–2.
- Produces: `percentile(values: Sequence[float], quantile: float) -> float | None` using nearest-rank semantics.
- Produces: `summarize_gap_series(rows: Iterable[Mapping[str, str]], *, epoch_start_s: float | None) -> dict[str, object]` with full-run and steady-state p50/p95/p99/max plus counts over 100/200/250 ms.
- Extends `run_trial` with keyword-only `renderer_profile: str`, `pair_id: int | None`, `pair_position: int | None`, `campaign_id: str | None`, and `output_root: Path = ROOT / "results/vio-stress"`.
- Produces raw files `clock-probe.csv`, `resource-probe.csv`, and `gpu-probe.csv`; unavailable GPU metrics are written as `unavailable`, not zero.

- [ ] **Step 1: Write failing percentile and epoch tests**

Test empty, single-value, and ordered percentile inputs; assert a 600 ms startup gap remains in full-run max but is absent from steady-state max after an explicit epoch boundary. Assert a missing epoch produces `steady_state_valid=false` rather than silently treating the whole run as steady state.

- [ ] **Step 2: Run the timing tests and verify failure**

Run: `python -m pytest tests/test_runtime_timing.py -q`

Expected: FAIL because `flydrones.runtime_timing` does not exist.

- [ ] **Step 3: Implement timing summaries and the combined probe**

The probe subscribes to `/clock`, polls the recorded Gazebo PID through `/proc`, records CPU/RSS/thread counts, and optionally samples `nvidia-smi.exe`; it stops when the runner writes a completion marker. It writes headers immediately and flushes each row so crashes preserve partial evidence.

- [ ] **Step 4: Write failing runner manifest tests**

Extend runner tests to assert schema `flydrones-vio-stress-trial-v2`, renderer profile, pair metadata, seed `240901`, repository/PX4 revisions, world/model/camera/policy/controller/launcher hashes, requested/attested renderer, software versions, and raw artifact hashes. Assert a missing or rejected attestation forces `evidence_accepted=false` and adds an error. Mock a worker timeout and assert the runner terminates only the recorded worker process group before owned PX4/Gazebo cleanup.

- [ ] **Step 5: Extend the runner and launcher handoff**

Pass `FLYDRONES_GZ_RENDER_PROFILE` into the launcher, place the trial beneath `output_root`, start the runtime probe before the flight worker, and run the worker in its own recorded process group. On timeout or exception, terminate only that process group; stop and join the probe in `finally`, copy renderer/cleanup evidence, compute all frozen hashes, and always write the v2 manifest atomically. Do not change the fault profile, flight command path, or 250 ms gate.

- [ ] **Step 6: Write failing summary tests for latency, RTF, and startup reliability**

Use small fixture CSVs to assert per-vehicle raw callback gaps, `/clock` full/steady metrics, RTF, missing probe evidence, and a startup failure. Verify startup failures remain operational failures even when the steady-state rows would pass.

- [ ] **Step 7: Extend trial summaries**

Read probe CSV and relay events, find the shared steady-state epoch only after five streams are continuous, PX4 health is valid, and mission timing starts, then emit schema `flydrones-vio-stress-summary-v5`. Extract EV fusion evidence from every saved vehicle ULog, preserve existing v4 safety fields, and add per-vehicle fusion, renderer, timing, RTF, resource availability, and startup-reliability sections.

- [ ] **Step 8: Run focused and regression tests**

Run:

```bash
python -m pytest tests/test_runtime_timing.py tests/test_vio_stress_runner.py tests/test_vio_stress_summary.py tests/test_vio_stress_evidence.py -q
python -m ruff check src/flydrones/runtime_timing.py tools/probe_gazebo_runtime_wsl.py tools/run_vio_stress_trial_wsl.py tools/summarize_vio_stress_wsl.py tests/test_runtime_timing.py tests/test_vio_stress_runner.py tests/test_vio_stress_summary.py
```

Expected: all listed tests pass and Ruff is clean.

- [ ] **Step 9: Commit Task 3**

```bash
git add src/flydrones/runtime_timing.py tools/probe_gazebo_runtime_wsl.py tools/run_vio_stress_trial_wsl.py tools/summarize_vio_stress_wsl.py tests/test_runtime_timing.py tests/test_vio_stress_runner.py tests/test_vio_stress_summary.py
git commit -m "Record renderer stability timing evidence"
```

### Task 4: Campaign Schedule and Stability Scoring

**Files:**
- Create: `src/flydrones/renderer_stability.py`
- Create: `tools/summarize_renderer_stability.py`
- Create: `tests/test_renderer_stability.py`

**Interfaces:**
- Consumes: v2 manifests and v5 summaries from Task 3.
- Produces: `campaign_schedule() -> tuple[CampaignTrial, ...]` for exactly ten trials in `default,d3d12-nvidia,d3d12-nvidia,default,default,d3d12-nvidia,d3d12-nvidia,default,default,d3d12-nvidia` order across pair IDs 1–5.
- Produces: `score_renderer_trial(manifest: Mapping[str, object], summary: Mapping[str, object]) -> dict[str, object]`.
- Produces: `score_campaign(trials: Sequence[tuple[Mapping[str, object], Mapping[str, object]]]) -> dict[str, object]` with per-trial failures, pair deltas, renderer aggregates, and `d3d12_stability_gate_pass`.
- Produces CLI: `python tools/summarize_renderer_stability.py --campaign-dir PATH --output PATH`.

- [ ] **Step 1: Write failing schedule and validation tests**

Assert exactly five profiles of each kind, the approved AB/BA order, pair positions 1/2, and rejection of duplicate names, missing pair members, profile/order mismatch, seed mismatch, and any frozen hash mismatch.

- [ ] **Step 2: Run the campaign tests and verify failure**

Run: `python -m pytest tests/test_renderer_stability.py -q`

Expected: FAIL because `flydrones.renderer_stability` does not exist.

- [ ] **Step 3: Implement the immutable schedule and input validation**

Give each trial the deterministic name `renderer-pair-{pair_id}-{position}-{profile}`. Validation compares every frozen field against the campaign manifest and treats missing, malformed, partial, or rejected renderer evidence as a recorded failure.

- [ ] **Step 4: Write failing stability-gate tests**

Build a passing ten-trial fixture, then independently violate: one D3D12 mission (`4/5`), one landing, collision/clearance, normal-run VIO gate, rejected per-vehicle ULog EV evidence, raw VIO max `250.0`, `/clock` max `250.0`, p99 `100.1`, RTF `0.949`, and cleanup. Each must make `d3d12_stability_gate_pass=false`; failed default trials remain reported but do not directly satisfy or erase the D3D12 gate.

- [ ] **Step 5: Implement scoring and paired output**

Score all exact thresholds from the spec. Emit each raw run, every failure reason, five pair deltas for p99/max/RTF/mission count, and aggregate distributions; never report only averages. The CLI exits 0 only when the D3D12 gate passes and all ten formal artifacts are present.

- [ ] **Step 6: Run tests and Ruff**

Run: `python -m pytest tests/test_renderer_stability.py -q && python -m ruff check src/flydrones/renderer_stability.py tools/summarize_renderer_stability.py tests/test_renderer_stability.py`

Expected: all tests pass and Ruff is clean.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/flydrones/renderer_stability.py tools/summarize_renderer_stability.py tests/test_renderer_stability.py
git commit -m "Score paired Gazebo renderer trials"
```

### Task 5: Frozen Campaign Orchestration and Development Gates

**Files:**
- Create: `configs/vio_renderer_stability.json`
- Create: `tools/run_renderer_stability_campaign_wsl.py`
- Create: `tests/test_renderer_stability_campaign.py`
- Modify: `tools/snapshot_vio_gate_results.py`

**Interfaces:**
- Consumes: `campaign_schedule`, the extended `run_trial`, and the campaign summarizer.
- Produces CLI: `python tools/run_renderer_stability_campaign_wsl.py --campaign-id ID --phase smoke|formal --profile PATH --model PATH`.
- Produces: `results/vio-renderer-stability/<campaign-id>/campaign-manifest.json`, one immutable subdirectory per trial, and `campaign-summary.json`.

- [ ] **Step 1: Write failing campaign-freeze tests**

Mock `run_trial` and assert `smoke` schedules one default single-vehicle, one D3D12 single-vehicle, and one D3D12 five-vehicle startup run. Assert `formal` loads `configs/vio_renderer_stability.json`, uses exactly the approved ten-run schedule, passes its campaign directory as `output_root`, and refuses an existing campaign whose controller revision, hashes, seed, schedule, or requested profile differs.

- [ ] **Step 2: Run campaign tests and verify failure**

Run: `python -m pytest tests/test_renderer_stability_campaign.py -q`

Expected: FAIL because the campaign runner does not exist.

- [ ] **Step 3: Implement the orchestration CLI**

Create the versioned config with seed `240901`, exact schedule, thresholds, fault/profile paths, sensor settings, and expected hashes. The runner creates a campaign manifest from it before the first process starts, invokes one trial at a time, waits for owned cleanup and resource release before continuing, preserves each nonzero result, and stops the formal campaign at the first D3D12 gate violation or invalid attestation. An interrupted campaign may only continue at the next unstarted scheduled trial when the current Git revision and every frozen manifest field still match; it must never rerun or overwrite an existing trial.

- [ ] **Step 4: Extend the compact evidence snapshot**

Read trial names from the campaign manifest instead of hardcoding them. Copy compact manifests/summaries/attestation/cleanup evidence into `docs/results/vio-renderer-stability/<campaign-id>/` and add hashes for all raw CSV, ULog, replay, and console artifacts without copying large files.

- [ ] **Step 5: Run orchestration tests and all targeted regressions**

Run:

```bash
python -m pytest tests/test_gazebo_renderer.py tests/test_process_ownership.py tests/test_runtime_timing.py tests/test_vio_stress_runner.py tests/test_vio_stress_summary.py tests/test_renderer_stability.py tests/test_renderer_stability_campaign.py -q
python -m ruff check src/flydrones/gazebo_renderer.py src/flydrones/process_ownership.py src/flydrones/runtime_timing.py src/flydrones/renderer_stability.py tools/attest_gazebo_renderer_wsl.py tools/stop_owned_processes_wsl.py tools/probe_gazebo_runtime_wsl.py tools/run_vio_stress_trial_wsl.py tools/summarize_vio_stress_wsl.py tools/run_renderer_stability_campaign_wsl.py tools/summarize_renderer_stability.py tests/test_gazebo_renderer.py tests/test_process_ownership.py tests/test_runtime_timing.py tests/test_vio_stress_runner.py tests/test_vio_stress_summary.py tests/test_renderer_stability.py tests/test_renderer_stability_campaign.py
```

Expected: all targeted tests pass and Ruff is clean.

- [ ] **Step 6: Run the three development scenarios and freeze configuration**

With no PX4/Gazebo resources in use, run the `smoke` phase. Require both single-vehicle profiles to publish depth and land, require D3D12 attestation to identify the RTX 3070 Ti and mapped D3D12 libraries, and require the D3D12 five-vehicle startup to expose five independent depth topics and clean up every owned process. Fix only integration defects; after these three scenarios pass, record and commit the frozen campaign manifest inputs.

- [ ] **Step 7: Commit Task 5**

```bash
git add configs/vio_renderer_stability.json tools/run_renderer_stability_campaign_wsl.py tools/snapshot_vio_gate_results.py tests/test_renderer_stability_campaign.py docs/results/vio-renderer-stability
git commit -m "Add frozen renderer stability campaign"
```

### Task 6: Formal Runs, Fault Regression, and Evidence Report

**Files:**
- Modify: `tools/snapshot_vio_gate_results.py`
- Create: `docs/VIO_RENDERER_STABILITY_REPORT.md`
- Create: `docs/results/vio-renderer-stability/<campaign-id>/campaign-summary.json`
- Create: `docs/results/vio-renderer-stability/<campaign-id>/raw-artifact-index.json`

**Interfaces:**
- Consumes: the frozen campaign, existing `configs/vio_fault_profiles/baseline.json`, `delay-120ms.json`, and `dropout-400ms.json`.
- Produces: a reviewable report that separates unit tests, isolated renderer probes, five-vehicle PX4/Gazebo simulation, fault injection, and unverified HITL/flight claims.

- [ ] **Step 1: Verify the execution preconditions**

Run targeted pytest/Ruff from Task 5, confirm `git status --short` contains only expected raw result directories, record the current Git and PX4 revisions, and verify no related PX4, `gz sim`, relay, worker, or probe processes are live.

- [ ] **Step 2: Run the ten formal paired trials without tuning**

Run the formal campaign using the frozen baseline profile and policy. Do not modify code, configuration, thresholds, or trial order after the first formal run. Preserve every failure; if the campaign stops, diagnose and report the failed gate rather than adding replacement runs.

- [ ] **Step 3: Score the normal-run stability gate**

Run the Task 4 summarizer and independently inspect each D3D12 attestation, `5/5` mission/landing result, safety result, p99/max, RTF, cleanup evidence, and five per-run ULog sets. If any normal D3D12 gate fails, skip fault claims, write the failure report, and stop this subsection.

- [ ] **Step 4: Run 120 ms and 400 ms D3D12 fault regressions only after Step 3 passes**

Run one frozen five-vehicle 120 ms delay trial and one frozen five-vehicle 400 ms dropout trial. The delay trial must not trigger the 250 ms gate. The dropout trial must show no autonomous setpoint after expiry, a land request within the threshold plus one control cycle and timestamp tolerance, correlated PX4 AUTO_LAND evidence, final landing, and preserved outcomes for unaffected vehicles. Treat designed mission abort and safety response as separate fields.

- [ ] **Step 5: Run full regression and static checks**

Run:

```bash
python -m pytest -q
python -m ruff check src tools tests
git diff --check
```

Expected: pytest and Ruff pass and Git reports no whitespace errors. Do not rerun the expensive formal campaign unless a post-campaign code change invalidates its revision; if code changes, create a fresh campaign and rerun all ten trials.

- [ ] **Step 6: Snapshot compact evidence and write the report**

Generate the compact snapshot and raw hash index. The report must list every run, default-vs-D3D12 pair deltas, tail latency, RTF/resources, task/safety/ULog results, all failures, actual renderer evidence, cleanup status, fault results, software revisions, and raw artifact locations. State explicitly that current visual input is Gazebo truth relay and that real camera+IMU VIO, HITL, and flight remain unverified.

- [ ] **Step 7: Verify resources and commit Task 6**

Confirm all recorded PIDs are gone, no matching PX4/Gazebo/relay/probe process remains, shared PX4 files match backups, and raw results remain untracked. Then commit only the report, compact summaries, indexes, and any final tested code changes.

```bash
git add docs/VIO_RENDERER_STABILITY_REPORT.md docs/results/vio-renderer-stability tools/snapshot_vio_gate_results.py
git commit -m "Report five-vehicle renderer stability evidence"
```
