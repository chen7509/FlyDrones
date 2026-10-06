# Owned Runtime Mapping Design

## Purpose

Extend the prospective capture binding so it can prove which declared files are mapped by the capture worker, PX4, and the OpenVINS native consumer at named lifecycle phases. The evidence closes the current gap between a declared local resource graph and the processes that actually load code during a run.

This stage does not claim complete runtime closure. Kernel, driver, hardware, anonymous mappings, data files opened without mapping, descendant processes that escape the registered process identity, and future lazy loads outside the observed phases remain outside the claim.

## Fixed Inputs and Research Basis

The implementation keeps the already frozen PX4, Gazebo Sim 8.15, gz-common 5.9, SDFormat 14.9, DART, OpenVINS `6948812`, and native reference artifacts. It uses Linux `/proc/<pid>/stat`, `/proc/<pid>/exe`, and `/proc/<pid>/maps` semantics. Gazebo `TestFixture` and `Server` run inside the worker process, while PX4 and the OpenVINS native consumer are direct, explicitly registered child processes. Existing license and maintenance records remain authoritative: Gazebo and SDFormat sources are Apache-2.0, PX4 is BSD-3-Clause, and OpenVINS is GPL-3.0 with uncertain current maintenance cadence.

## Declaration Contract

`capture-resource-binding-v3` adds a `runtime_maps` object with exactly:

- `self_phases`: the ordered worker phases required for qualification;
- `owned_roles`: a map from the exact role `px4` or `openvins` to its ordered required phases;
- `max_maps_bytes`: a positive bounded read limit no larger than 8 MiB;
- `max_observations`: a positive limit no larger than 16.

The fixed online profile requires worker phases `postimports`, `postfinalize`, and `postfirststep`. It requires `px4` at `ready` and `prestop`, and requires `openvins` at `ready` and `prestop` when the shadow consumer is enabled. A profile without OpenVINS must omit that role rather than fabricating an observation.

Every owned executable must already be part of the declared pre-run file snapshot. Roles, phases, limits, and files are fixed before `NativeClient`, `TestFixture`, or PX4 starts.

## Process Identity and Map Observation

The observer accepts only a direct process object explicitly registered by the capture code. Registration records:

- role;
- PID;
- process group;
- session;
- `/proc/<pid>/stat` start ticks;
- canonical `/proc/<pid>/exe` target;
- expected declared executable.

Each observation performs this bounded sequence:

1. read and validate `stat` and `exe`;
2. read at most `max_maps_bytes + 1` bytes from `maps` and reject overflow;
3. read and validate `stat` and `exe` again;
4. reject PID reuse, exec changes, disappearance, malformed data, unreadable files, deleted mappings, or identity changes;
5. compare every file-backed mapping to the declared snapshot by canonical path, device, and inode;
6. persist the raw map and structured result before returning qualification.

The observer never scans all processes, sends signals, or changes cleanup behavior. It observes only the registered worker, PX4, and OpenVINS processes. Existing owned-group cleanup remains a separate mechanism.

## Capture Lifecycle

The worker keeps the existing `postimports` and `postfinalize` observations and adds `postfirststep` immediately after the first successful `server.run` call. This phase detects renderer and sensor libraries loaded lazily on the first simulation step.

OpenVINS is registered immediately after `NativeClient` starts. Its `ready` observation occurs after its protocol session is usable and before motion can become eligible. Its `prestop` observation occurs before termination in the cleanup callback.

PX4 is registered immediately after `Popen`. Its `ready` observation occurs only after the existing accepted unarmed heartbeat establishes source readiness. Its `prestop` observation occurs before termination in the owned-PX4 cleanup callback.

An observation failure locks the binding qualification and is added to capture errors. Existing safety cleanup still runs. No map failure may bypass the readiness, source-health, motion, or native-consumer gates.

## Evidence and Qualification

Evidence includes the prospective v3 declaration, pre/post declared-file snapshots, raw maps, structured observations, registered identity records, the unchanged capture journal, and ULog when a physical integration run is performed.

`runtime_mapping_coverage_verified` is true only when:

- the pre snapshot was recorded;
- declared files remain stable at post capture;
- every required self and owned phase appears exactly once in order;
- every observation retained the same process identity and executable;
- every file-backed mapping matched the declared snapshot;
- no binding error occurred.

`runtime_closure_qualified` remains false. `local_file_graph_verified` remains a separate resource-graph result. A mapping pass does not prove sensor correctness, VIO accuracy, estimator health, complete process ancestry, physical performance, or flight readiness.

## Tests

Tests must cover normal identity and mapping, PID reuse, leader exit between reads, exec changes, unreadable and oversized maps, deleted/nonabsolute/malformed mappings, unknown files, device/inode mismatch, duplicate roles or phases, out-of-order phases, observation-budget exhaustion, missing required phases, log short writes, and post-snapshot drift.

A real bounded harness spawns ordinary owned child processes without PX4 or Gazebo, verifies a normal child and an exec-changing or disappearing child, and confirms no unrelated process is inspected or signalled. Physical integration is a separate frozen study after the v3 declaration and all selected runtime inputs are captured prospectively.

## Nonclaims and Stop Conditions

The implementation does not alter the vehicle, physics, camera, IMU, force profile, OpenVINS parameters, public initialization gate, source watchdogs, or 25-second study limits. It does not use Gazebo truth inside VIO and does not publish ODOMETRY or unlock EKF2 fusion.

The physical mapping study must stop and retain failure evidence if any declared file is absent, any required process or phase cannot be observed, the runtime identity changes, a map is unknown, or a source/readiness/safety gate fails. After this stage, the next independent prerequisite is the prospective trajectory/gauge contract for initialization after motion begins.
