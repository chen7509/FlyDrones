# Full-Load Runtime Mapping Study Design

## Purpose

Run one prospectively declared 25-second PX4/Gazebo/OpenVINS mapping study under the existing supported-motion workload. The study determines whether every file-backed mapping observed in the worker, PX4, and OpenVINS processes belongs to the frozen declaration at the required lifecycle phases.

This stage qualifies only runtime mapping coverage. It does not qualify complete runtime closure, VIO accuracy, estimator health, PX4 fusion, flight safety, learning, or swarm behavior.

## Existing Constraints

The study keeps the existing physical and sensor conditions:

- 25 seconds requested simulation time;
- 1 ms physics step;
- 250 Hz raw IMU;
- 10 Hz 160×120 RGBD;
- the fixed x500 body, gravity, support fixture, 0.4 m two-second lift, 26 N 1.6-second lateral excitation, 200 ms future anchor, eight-second readiness limit, and existing motion abort thresholds;
- the two-second native/source/oldest-unreconciled watchdogs and 32-pending observation limit;
- the pinned PX4 binary, OpenVINS `6948812` online consumer, uncalibrated `raw-model-zero-bias-diffusion-v1`, and native reference module.

The policy remains read-only and disarmed. It publishes no control, arm, ODOMETRY, or EKF2 input. Gazebo truth is available only to the isolated support fixture, abort monitor, and offline audit; it never enters OpenVINS.

## Approaches Considered

### Selected: source-derived prospective closure

Start from the sealed ordered resource graph, then add exact executable and module roots for the current worker, PX4, OpenVINS, native reference, selected Gazebo systems, DART physics engine, Ogre2 renderer, and only the sensor libraries required by the scene. Run trusted `ldd` on each exact ELF root before capture, parse every result strictly, and snapshot the union before any worker starts.

This approach provides the strongest local claim without starting physics for discovery. It may still fail if a source-selected lazy library was omitted; that failure is retained and does not authorize adding the observed path to the same study.

### Rejected: declare the full installed Gazebo inventory

The earlier 999-file installation inventory would reduce unknown mappings but would blur selected files and unused candidates. It is retained as research evidence, not used as the study declaration.

### Rejected: discover mappings in a first physical run and retry

Post-run allowlisting would tune the declaration to the test execution. Unknown mappings must fail this study. Any future revision requires a new named study and an independent source or package-selection reason.

## Prospective Builder

Create `tools/benchmark/full_load_runtime_mapping.py`. It accepts explicit paths for:

- the sealed v2 ordered-resource binding declaration;
- the resource resolver binary;
- PX4;
- OpenVINS online consumer and its four-file frozen configuration;
- native reference module and SHA-256;
- output directory.

The builder refuses active competing resources and refuses missing, duplicate, non-regular, changed, or undeclared inputs. It records the hashes of every source declaration and binary before deriving anything.

The builder creates:

1. `execution-contract.json` from the same `execution_contract(args)` function enforced by capture: 300-second worker and supervisor limits, 25-second simulation, and the exact supported-ready-shadow-heartbeat profile;
2. `runtime-binding-v3.json` by copying the sealed resource graph contract, rebuilding its baseline from current files, adding runtime roots and their strictly parsed `ldd` dependencies, and adding `runtime_maps`:
   - self: `postimports`, `postfinalize`, `postfirststep`;
   - PX4: `ready`, `prestop`;
   - OpenVINS: `ready`, `prestop`;
   - 8 MiB per map read and 16 owned observations;
3. a study manifest containing the exact command, environment, root-selection reasons, source/package evidence, hashes, and nonclaims.

The expected generated hashes come from the pinned board-pattern archive consumed by capture plus the actual pinned `gz_env.sh`. The builder verifies these bytes directly; it does not copy hashes from a historical runtime output.

## Runtime Root Selection

Roots are exact paths selected before launch:

- current WSL Python executable;
- imported compiled bindings for `gz.sim8`, `gz.math7`, and protobuf modules used by capture;
- the ten system plugins selected in the sealed generated-world graph;
- the DART engine plugin selected by fixed PX4/Gazebo configuration;
- the Ogre2 renderer selected by the sensor-system configuration;
- gz-sensors base, rendering, RGBD camera, camera, depth-camera, IMU, magnetometer, navsat, and air-pressure libraries required by the SDF sensors;
- PX4, OpenVINS online consumer, and native reference binaries.

Each root has a fixed reason and, for installed packages, package name and version. Wildcard discovery may locate the unique installed version before declaration, but the resulting manifest must contain one exact canonical file per required root and refuse zero or multiple canonical candidates.

`ldd` runs only on these trusted local ELF roots, with a ten-second bound. Empty output, `not found`, unsupported lines, timeout, nonzero exit, or path drift refuses launch. Symlink chains and final file identities are retained by the existing declared snapshot.

## Launch and Evidence Flow

The builder invokes `capture_disarmed_sensors.py` only through `declared_command`. Parent and worker both validate the execution contract and v3 declaration before native consumers or simulation start.

The capture must retain:

- declaration and execution contract;
- pre/post declared snapshots;
- ordered resource graph and query records;
- raw and structured worker maps at all three phases;
- raw and structured PX4 and OpenVINS maps at ready and prestop;
- process identity records;
- source-fanout, heartbeat, native request/ack, physical reference, motion, ULog, supervisor, and cleanup evidence;
- all partial evidence when any gate fails.

The first successful `server.run` establishes `postfirststep`. OpenVINS ready requires its first validated acknowledgement. PX4 ready requires the accepted unarmed heartbeat after its registered process exists. Missing ready prevents corresponding prestop qualification and causes terminal mapping failure.

## Qualification

`runtime_mapping_coverage_verified=true` requires:

- prospective declaration and execution contract validated by both parent and worker;
- all required self and owned phases observed exactly once and in order;
- no unknown, deleted, unreadable, oversized, replaced, or identity-mismatched file mapping;
- declared files byte- and identity-stable at post capture;
- capture completed the requested 25 simulation seconds;
- worker and original owned process group released with existing cleanup evidence;
- no safety, source, readiness, native, logging, ULog, or supervisor error.

The following remain false regardless of a mapping pass:

- `runtime_closure_qualified`;
- `vio_accuracy_qualified`;
- `estimator_health_qualified`;
- `fusion_eligible`;
- `flight_ready`.

If the study fails because WSL wall time or heartbeat scheduling cannot satisfy an unchanged watchdog, record it as a platform/run failure. Do not label it a fruit-fly learning failure and do not extend the watchdog or reduce load.

## Testing

Before launch, tests cover:

- exact root selection, zero/multiple candidate refusal, and package evidence;
- strict `ldd` parsing, nonzero/timeout/missing dependency, duplicates, symlink changes, and read-time file drift;
- deterministic inventory ordering and duplicate canonical-path refusal;
- generated input hash derivation from the pinned archive and `gz_env.sh`;
- exact execution command, 300/300 limits, profile values, and no legacy undeclared launch;
- v3 declaration roles and lifecycle phases;
- active-resource refusal, partial-write/close failures, and capture nonzero retention;
- audit refusal for missing phases, incomplete simulation, unknown maps, missing ULog, or unqualified cleanup.

After these pass, run one dry prospective build with no physics. Only then may the single full-load study start.

## Next Dependency

After this mapping study is sealed, design and freeze the trajectory/gauge contract before another VIO accuracy run. The previous estimator initialized after lift began; the next accuracy protocol must define initialization coverage, gauge origin, coordinate transformation, comparison interval, and failure accounting before seeing the new trajectory.
