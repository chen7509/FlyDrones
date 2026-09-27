# Five-Camera Sustained Render Capacity Design

Date: 2026-09-27

Status: proposed for implementation after user review

## Purpose

Determine why the frozen five-vehicle camera-phase trial runs at only about
half real time, then make the smallest justified correction without changing
the aircraft, camera contract, PX4 behavior, policy, safety supervisor, mission,
or acceptance thresholds.

This package is diagnostic first and conditional second. It does not assume
that moving Python code to C++ will fix the result. It measures the cost of
sustained depth rendering separately from the cost of the Python Gazebo
Transport boundary. A production change is allowed only after the measurements
identify that boundary as the limiting component.

## Current evidence and corrected interpretation

The previous renderer campaign and the final camera-phase development run used
the same five PX4 vehicles, Gazebo 8.15.0, Ogre2 through Mesa D3D12 on the
NVIDIA RTX 3070 Ti Laptop GPU, 4 ms physics steps, and 160 x 120 float depth
images at 10 Hz.

| Evidence | Full RTF | Steady RTF | Sustained image subscriber |
|---|---:|---:|---|
| Five successful D3D12 formal runs | 0.9501-0.9607 | 0.9807-0.9958 | No; renderer attestation stopped after 11 images per camera |
| Final phased five-camera development run | 0.5266 | unavailable | Yes; 186-187 images per camera |

The phased run preserved 10 Hz image frequency, 8 ms p95 phase error, zero
unmatched triggers, and zero unmatched images. Four vehicles timed out during
the unchanged 12 second wall-clock takeoff window and the fifth did not arm
after its one permitted temporary-rejection retry. All five landed and cleanup
passed.

Gazebo Sim's Sensors system disables rendering sensors that have no subscriber
connections. The older renderer campaign therefore proved renderer identity
and short-burst image correctness, but did not prove that five depth cameras
could remain active in real time. The active camera load and the persistent
observer began at the same time in the phased campaign, so existing artifacts
cannot separate their costs.

## Upstream basis and candidate assessment

### Gazebo Sim Sensors system

- Upstream: <https://github.com/gazebosim/gz-sim>
- Installed version: 8.15.0.
- License: Apache-2.0.
- Maintenance: active upstream; the Sensors system in the current source tree
  contains render-thread scheduling, pending-trigger selection, connection
  checks, and the no-subscriber sensor disable path.
- Relevant interface: Gazebo Transport image and trigger topics plus the
  Sensors render loop.
- Resource implication: a persistent image subscriber keeps each triggered
  rendering sensor eligible to render and publish.
- Decision: retain the upstream sensor implementation unchanged. Instrument it
  externally first; do not fork Gazebo.

### Gazebo Transport

- Upstream: <https://github.com/gazebosim/gz-transport>
- Installed version: 13.6.0.
- License: Apache-2.0.
- Maintenance: active upstream and version-matched with the installed Gazebo
  Harmonic stack.
- Relevant interface: `gz::transport::Node`, typed `gz::msgs::Image` and
  `gz::msgs::Boolean` subscriptions, typed trigger publishers.
- Resource implication: both Python and C++ subscribers still require Gazebo
  to render and publish the complete depth message. C++ removes Python binding,
  object-lifetime, queue, and interpreter costs but does not eliminate render
  or Transport serialization costs.
- Adaptation cost: small standalone CMake target; installed headers and
  pkg-config packages are already available.
- Decision: adopt for the diagnostic native subscriber and, conditionally, the
  combined native scheduler-observer.

### In-process Gazebo system or sensor plugin

- Candidate interface: `gz::sim::System` / rendering and sensor callbacks.
- Potential benefit: compact metadata can be recorded before a full image is
  transferred to another process.
- Cost and risk: tighter coupling to Gazebo's render thread and sensor ownership,
  more version-specific code, and a new failure mode inside the simulator.
- Decision: reject for the first implementation. It is justified only if the
  external C++ result shows that Transport transfer remains the final blocker
  and an in-process metadata hook can preserve full image delivery to the real
  downstream consumer.

### Environment migration

- Candidate: native Linux NVIDIA/Vulkan or another Gazebo-supported native GPU
  path.
- Potential benefit: removes WSL D3D12 translation and synchronization costs.
- Cost: changes the execution environment and requires a new renderer and PX4
  evidence baseline.
- Decision: conditional fallback when sustained five-camera C++ consumption
  remains below the frozen real-time threshold.

## Scope

### Included

1. A native C++ Transport probe that subscribes to selected depth and trigger
   topics and records bounded metadata only.
2. A fixed-duration five-vehicle capacity harness with four load cells and
   three immutable repetitions per cell.
3. CPU, RSS, simulation clock, RTF, image rate, phase, integrity, renderer, and
   cleanup evidence for every run.
4. Deterministic root-cause classification and a fail-closed decision.
5. Conditional integration of a combined C++ scheduler-observer only when the
   native five-camera cell reaches every frozen gate.
6. One five-vehicle development-gate rerun after a justified production change.

### Excluded

- Policy training, reward or loss changes, new weights, or curriculum changes.
- Camera resolution, format, rate, phase offsets, field of view, or clipping
  changes.
- Longer takeoff deadlines, lower RTF thresholds, or relaxed PX4/safety gates.
- Formal smoke, ten-run paired campaigns, VIO fault regressions, HITL, and
  flight unless the existing five-vehicle development gate passes first.
- Treating Gazebo truth relay as real camera-plus-IMU VIO.

## Frozen inputs

The capacity experiment copies and hashes all inputs before the first run:

- PX4 revision `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`;
- FlyDrones base implementation `cba7d03eea0d9defa868599895578d3f89ca0e02`;
- D3D12 NVIDIA renderer profile and attestation rules;
- five vehicles, identical spawn poses, models, world, physics, and sensor set;
- 4 ms physics step and real-time factor target 1.0;
- 160 x 120 `R_FLOAT32` depth, 10 Hz per vehicle;
- phased target offsets 0, 20, 40, 60, and 80 ms;
- existing camera-phase thresholds, including 8 ms p95 phase and adjacent
  spacing limits;
- a fixed 30 seconds of scored simulation time after readiness;
- no mission worker and no autonomous policy during capacity cells;
- one immutable schedule of twelve cell runs.

The no-worker capacity harness keeps five PX4 SITL instances connected and
disarmed. This retains PX4, physics, sensor, bridge, and process pressure while
removing takeoff state transitions and policy activity from the diagnosis.

## Capacity cells

Each cell uses a fresh result directory and fresh simulator/PX4 processes. Runs
must never reuse a Gazebo process or mutable model file.

| Cell | Active image subscribers | Observer implementation | Purpose |
|---|---:|---|---|
| `idle-0` | 0 | native process observes clock and triggers only | PX4/physics/trigger baseline; confirms host can meet RTF without active depth rendering |
| `native-1` | 1 | C++ | measures one sustained depth camera and native subscriber cost |
| `python-5` | 5 | existing Python observer | reproduces the current failure under the capacity harness |
| `native-5` | 5 | C++ | separates Python overhead from sustained rendering plus Transport cost |

The immutable run order balances warm-cache and thermal effects:

1. `idle-0`, `native-1`, `python-5`, `native-5`
2. `native-5`, `python-5`, `native-1`, `idle-0`
3. `python-5`, `idle-0`, `native-5`, `native-1`

No parameter may change after run 1. A startup or cleanup failure is retained
and consumes its scheduled slot; it is not silently replaced.

## Native probe

Create a standalone executable named `flydrones_camera_phase_native` under a
new `native/camera_phase/` CMake project. It links only the installed
gz-transport13, gz-msgs10, Threads, and standard C++ libraries.

The probe has two modes:

- `observe`: subscribe to `/clock`, selected depth-image topics, and selected
  trigger topics. The callback reads the message timestamp, dimensions,
  vehicle identity, sequence number, and monotonic receipt time. It never
  copies `Image.data()` into an application buffer and never writes from the
  callback thread.
- `schedule-observe`: add simulation-clock trigger publication using the same
  epoch and phase arithmetic already specified by `TriggerSchedulerState`.
  This mode is built and tested, but it becomes the production path only after
  `native-5` passes.

Callbacks push fixed-size metadata records into a bounded queue. One writer
thread drains the queue into JSONL and flushes at 250 ms wall-clock intervals.
Queue overflow, duplicate sequence, malformed timestamp, topic mismatch,
publisher disconnect, stale clock, early exit, and incomplete shutdown are
explicit failures. SIGINT and SIGTERM stop subscriptions, drain the queue for
one second of quiescence, write exactly one stop record, and exit with a stable
code.

The C++ output uses the existing event names and fields consumed by
`summarize_camera_phase`, plus:

- `implementation: "native-cpp"`;
- `subscriber_count`;
- `callback_cpu_ns` and `writer_cpu_ns` aggregates;
- `image_payload_bytes_seen` as a count derived from message size without
  retaining the payload;
- `queue_high_watermark`;
- build compiler, linked Gazebo versions, executable SHA-256, and source hash.

The Python and C++ evidence are scored by the same Python summary code. The
native executable does not implement a second acceptance formula.

## Harness and evidence

Add a capacity-run command that:

1. validates a frozen config and the expected source/executable hashes;
2. copies the model and world into the run directory;
3. configures the same triggered depth cameras and starts five PX4 instances;
4. starts the selected observer and the unchanged simulation-clock scheduler;
5. waits for explicit readiness and records the scoring epoch;
6. runs for 30 scored simulation seconds, with a 120 second wall-clock timeout
   measured after the scoring epoch;
7. writes completion, waits for the observer's clean stop, then invokes the
   existing stopper;
8. verifies model restoration, closed UDP relays, terminated descendants, and
   absence of relevant Windows/WSL processes;
9. generates a per-run manifest and summary without deleting failed artifacts.

Every run preserves:

- config and source hashes;
- renderer attestation and mapped GPU libraries;
- clock, process resource, and GPU probes;
- trigger/image JSONL and phase summary;
- PX4 startup ULogs even though vehicles remain disarmed;
- stdout/stderr, exit codes, cleanup evidence, and exact command lines.

The campaign summary reports all twelve runs, medians and ranges, cell-paired
deltas, every failure, and raw artifact hashes. It does not report only an
average.

## Per-run gates

All cells require:

- renderer attestation accepted;
- five PX4 instances connected and healthy while disarmed;
- 30 scored simulation seconds completed;
- full-run RTF at least 0.95;
- zero stale-clock, queue-overflow, duplicate, cross-model, and cleanup errors;
- exact selected subscriber count;
- all expected trigger streams present;
- all processes stopped and shared files restored.

Cells with active image subscribers additionally require:

- each selected camera between 9.5 and 10.5 Hz;
- zero unmatched triggers and images;
- p95 phase error no greater than 8 ms;
- median adjacent-spacing error no greater than 8 ms when five cameras are
  active;
- fixed 160 x 120 `R_FLOAT32` metadata.

`idle-0` does not require image records. It must prove that no depth-image
subscription exists during the scored interval.

## Root-cause classification

Classification happens only after all twelve scheduled runs are present.

1. `host_or_baseline_capacity_failure`: any valid `idle-0` run has RTF below
   0.95. Stop; neither observer implementation can be evaluated fairly.
2. `python_transport_boundary`: all three `native-5` runs pass every gate and
   all three `python-5` runs fail RTF. The native implementation is eligible
   for conditional production integration.
3. `sustained_render_transport_capacity`: any valid `native-5` run has RTF
   below 0.95 and its median improvement over `python-5` is less than 0.05.
   Stop implementation and move to the environment-migration package.
4. `mixed_python_and_render_capacity`: any valid `native-5` run has RTF below
   0.95 and its median improvement over `python-5` is at least 0.05. The native
   boundary helps but does not make this host eligible; stop and migrate the
   environment.
5. `non_monotonic_or_inconclusive`: missing runs, integrity failures, or an RTF
   range greater than 0.03 across the three valid repetitions of any cell.
   Preserve the evidence and diagnose the infrastructure before changing
   production code.

RTF comparisons use medians only for classification; each individual
`native-5` run must still meet 0.95 before production integration is allowed.

## Conditional production integration

This section executes only for `python_transport_boundary`.

Replace the two Python camera auxiliary processes with the tested C++
`schedule-observe` process. Preserve the existing model configurator, JSONL
schema, ready/completion markers, summary scorer, worker isolation, and cleanup
contract. The process remains evidence-only: no image, trigger, or phase field
enters policy observations, flight commands, PX4 inputs, or the safety
supervisor.

After unit and integration tests, run exactly one new phased five-vehicle
development trial with the original worker and unchanged 12 second takeoff
deadline. It passes only with:

- `5/5` mission-ready and complete takeoff-chain evidence;
- `5/5` final landing;
- full and steady RTF at least 0.95;
- accepted camera phase, renderer, actuator, ULog, and cleanup evidence;
- no policy, camera, model, safety, or threshold changes.

If that run fails, preserve it and stop. It does not authorize another tuning
loop. Smoke and formal campaigns remain blocked until a separately reviewed
amendment explains the new failure.

## Failure injection and regression coverage

Before live capacity runs:

- Unit-test C++ option parsing, topic mapping, epoch/phase arithmetic, fixed-size
  queue overflow, stop-record uniqueness, and exit codes.
- Cross-check C++ scheduling vectors against Python `TriggerSchedulerState`
  fixtures for boundary timestamps and skipped clock intervals.
- Feed identical synthetic event fixtures from Python and C++ into
  `summarize_camera_phase` and require byte-equivalent scored fields.
- Integration-test missing topic, wrong dimensions, stale clock, observer
  termination, scheduler publisher loss, completion-before-readiness, and
  forced queue overflow.
- Verify the capacity campaign rejects changed hashes, reordered schedules,
  missing repetitions, duplicate run identities, and relaxed thresholds.
- Verify cleanup after both normal completion and injected native-process
  failure.

Tests may use synthetic messages and a one-camera Gazebo fixture. The twelve
capacity runs are required for a performance conclusion; unit tests alone
cannot satisfy that conclusion.

## Safety and interpretation boundaries

- Capacity cells keep PX4 disarmed and do not exercise autonomous flight.
- The final conditional development run retains PX4 as the sole attitude and
  motor controller and retains the existing safety supervisor.
- Gazebo image timestamps and truth-relay localization remain simulation
  evidence, not real VIO evidence.
- RTF is measured from simulation clock against monotonic wall time on this
  host. Results apply to this WSL/D3D12 configuration only.
- A native observer pass proves capacity for this simulated image stream; it
  does not prove real camera drivers, VIO compute, HITL, or flight readiness.

## Deliverables

- Native CMake project and reproducible build script.
- Frozen capacity config and twelve-run campaign runner.
- Shared summary/scoring extensions with tests.
- Raw immutable run directories and compact Git evidence snapshots.
- `docs/FIVE_CAMERA_RENDER_CAPACITY_REPORT.md` with the root-cause verdict,
  all run results, software versions, limitations, and the conditional
  five-vehicle gate result when applicable.

## Stop conditions

Stop without production integration when any of these occurs:

- baseline capacity is below 0.95;
- any `native-5` repetition is below 0.95;
- evidence integrity or cleanup cannot be proven;
- the native executable changes camera data, PX4 inputs, policy inputs, or
  safety behavior;
- completing the experiment would require lowering a frozen threshold.

Under these conditions the report must say `rejected` or `inconclusive`, retain
all failures, and recommend the next environment or instrumentation package.
