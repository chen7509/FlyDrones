# Heartbeat simulation-time physical retry design

## Purpose

The immutable `study-v15/capture-v1` attempt proved the OpenVINS initializer handoff and public-state transition, then refused solely because heartbeat age was measured in host wall time while PX4/Gazebo ran in slower lockstep simulation time. The dual-clock readiness correction passed fixed-evidence and full regression tests but has not run physically. This stage binds that correction into one new prepare-only package, runs one startup-only preflight, and, only after committed independent audits, permits one immutable `study-v16/capture-v1` attempt.

## Frozen workload and safety boundary

The new package preserves the source execution contract: 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGB-D, the same vehicle, gravity, models, OpenVINS binary/configuration, native reference, supported-motion profile, 26 N lateral profile, 200 ms anchor delay, 8 s startup limit, and every source/native/fan-out/supervisor deadline. The heartbeat limit remains 2 s; only its clock domain changes to simulation time. No truth enters VIO, no frames are repeated, no load is reduced, and public initialization and all safety/fusion gates remain closed unless their existing evidence conditions pass.

`study-v16` must be generated from the immutable `study-v15` failure, its physical audit, the exact dual-clock audit and evidence archive, and the current committed implementation. Its runtime binding re-snapshots every prior dependency and explicitly includes the dual-clock source, auditor, generator, auditor tests and authorization record. The package audit recomputes the command, runtime binding and execution contract and requires an absent future destination.

## Execution sequence

1. Generate and independently audit `study-v16` without starting PX4, Gazebo or OpenVINS.
2. Commit that boundary, rerun the audit, then execute exactly one `--startup-preflight` at a separate immutable destination. It must stop before TestFixture, PX4, OpenVINS, sensors, motion or force.
3. Independently audit the startup result and package membership, then commit the physical boundary.
4. If and only if all gates still pass and resources are empty, execute the manifest command once. Never overwrite or retry its destination.

The physical result must retain all failures, ULog, supervisor, runtime maps, source/fan-out/native/readiness/reference/physics/motion records and hashes. A complete 25 s process is not enough to qualify VIO: the frozen trajectory gauge, continuous public output, quality/reset/covariance boundaries and failure handling remain separate gates. No result here is evidence about fruit-fly learning, weights, loss or swarm behavior because that policy is not running.
