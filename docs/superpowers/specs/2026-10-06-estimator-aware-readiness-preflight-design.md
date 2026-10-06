# Estimator-Aware Readiness Preflight Design

## Goal

Make the next supported-motion OpenVINS study capable of scoring the full motion interval without choosing a favorable trajectory origin after the run. Motion may receive its immutable 200 ms future anchor only after the existing sensor and unarmed-heartbeat proof and a causally delivered OpenVINS camera acknowledgement that reports internal initialization.

This stage implements and independently audits the new readiness route and a prepare-only launch package. It does not start OpenVINS, PX4, Gazebo, training, a capture worker, or physics.

## Evidence and upstream basis

The prior physical study selected its anchor at 1.622 s, while the first internally initialized state appeared at 2.4 s. The frozen trajectory policy therefore correctly classified startup motion as unavailable. Repeating the same anchor contract would not close that gap.

OpenVINS separates internal estimator initialization from public readiness. The fixed native producer already emits both flags on every acknowledged camera update. The new gate consumes that existing causal acknowledgement; it does not inspect a log later, poll an output file, use Gazebo pose, change OpenVINS initialization settings, or infer readiness from elapsed time. OpenVINS evaluation guidance supports explicit trajectory alignment and error metrics, while initialization success alone is not an accuracy result. Gazebo TestFixture and PX4 lockstep remain the physical execution mechanisms; this stage does not instantiate them.

Fixed upstream and local evidence remains:

- OpenVINS commit `69488123ed9362dd44b6f28e7f4680abbff1442b`, GPL-3.0, non-archived at the recorded observation but with uncertain current maintenance cadence;
- PX4 commit `d6f12ad`, BSD-3-Clause, with lockstep simulation-clock behavior already traced locally;
- Gazebo Sim 8.15 APIs, Apache-2.0, where TestFixture construction and stepping remain deferred to the later physical study;
- oneTBB `v2021.11.0` commit `8b829acc65569019edb896c5150d427f288e8aba`, Apache-2.0, and Ubuntu `libtbbmalloc2` `2021.11.0-2ubuntu2`, already qualified only for the exact first-IMU lazy mapping.

## New opt-in route

Add `ready-shadow-heartbeat-estimator-v1` without changing either existing fan-out profile.

`ShadowInput` retains the exact native acknowledgement batch produced by each source record. The batch is cleared before every record, contains only acknowledgements returned by the existing bounded `NativeClient`, and is never reconstructed from log files. A failed or partial delivery remains visible and cannot be rolled back.

`EstimatorAwareReadiness` composes the existing `JournaledReadiness`. Sensor and heartbeat semantics remain unchanged. It accepts an acknowledgement batch only inside the existing fan-out gate after the native route returns and before the source record can commit to readiness. A qualifying acknowledgement must:

- be a camera acknowledgement with strict integer sequence/sample/clock fields;
- retain valid monotonic receive, processing, and acknowledgement ordering;
- report `internal_initialized=true` and a finite state time matching the camera sample to within the existing 1 ns rule;
- include a strict Boolean public flag, but public readiness is not required to select the anchor;
- advance native sequence and camera sample monotonically;
- be no older than the unchanged 2 s wall-health limit when proof is requested.

Every qualifying acknowledgement is written and flushed to an estimator-readiness journal before it becomes eligible evidence. The journal is not fsync durability. Invalid, duplicate, regressed, stale, future, missing, partially written, flush-failed, or close-failed evidence latches failure. The first qualifying record is retained; later records refresh health without changing the already immutable anchor.

## Anchor and trajectory consequences

The existing `AnchoredPolicy` remains unchanged. It still requires a fresh proof, selects exactly `current_sim_time + 200 ms`, preserves the 8 s startup limit, uses the same two-second 0.4 m support lift and 26 N / 1.6 s lateral excitation, and fails closed if proof is later lost.

Because the new proof cannot exist before the first internal state acknowledgement, the trajectory policy's fixed origin rule—first internal state in the session—must precede or equal anchor selection. No truth, error, public status, or future trajectory quality may select the origin. The later offline audit must still require public coverage, fixed 4-DoF alignment, unit scale, zero time shift, the existing error screens, and an unmodified 25 s endpoint. Internal initialization only removes the known startup-origin ambiguity; it does not prove accuracy, health, covariance, quality, reset handling, fusion, or flight readiness.

## Prepare-only integration

Derive a new package from the independently audited PR63 preparation. It must:

- validate all PR63 source members, its passing prepare audit, the exact oneTBB lazy contract, and the absence of any source `capture-v1`;
- include the new source modules and tests in a freshly snapshotted runtime-binding inventory;
- preserve the exact frozen OpenVINS binary/config, native reference module, PX4/Gazebo resource graph, trajectory policy, workload, timeouts, force profile, and safety gates;
- change only the source fan-out profile from `ready-shadow-heartbeat-v1` to `ready-shadow-heartbeat-estimator-v1`;
- recompute the execution contract and an absolute future worker command to a new capture destination;
- keep physical execution, runtime closure, VIO accuracy/health, fusion, and flight false.

The builder and independent auditor never invoke the generated command. Missing or drifted sources, extra fields, an old profile, a lowered limit, an unknown runtime mapping allowance, a reused capture destination, or a downstream success claim is a prelaunch refusal.

## Verification boundaries

Synthetic tests cover acknowledgement batching, causal ordering, invalid state clocks, stale proof, concurrent proof, journal failures, partial native delivery, shutdown, unchanged legacy profiles, exact command and binding reconstruction, and independent audit drift cases.

Passing this stage qualifies only the new preflight package. A later, separately named physical study gets at most one attempt after resource checks. Any new runtime mapping, watchdog failure, source loss, estimator failure, or cleanup defect is retained as its own failure and is not attributed to fruit-fly learning.
