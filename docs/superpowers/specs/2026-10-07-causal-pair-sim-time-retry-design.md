# Causal Pair Simulation-Time Retry Design

## Purpose

Create a new prepare-only package that binds the immutable `study-v16` physical refusal and the verified RGB/CameraInfo simulation-time correction without altering the flight workload or claiming that a physical rerun has passed. The first generated `study-v17` is retained as a rejected baseline-drift package; the fresh authoritative package is `study-v18`.

## Evidence boundary

The builder accepts only:

- `study-v16/capture-v1`, whose earliest terminal cause is independently classified as `camera-pair-wall-age-slow-simulation-refusal`;
- `physical-run-v8-completion.json`, showing exactly one attempted destination, return code 2 and an empty post-run resource scan;
- `results/causal-pair-sim-time-dev-1701/study-v16-audit.json`, with zero failures, pair wall age 355,099,344 ns, idle wall age 294,079,878 ns, pair simulation age 0, a passing fixed replay and a failing simulation-silence counterexample;
- `evidence/causal-pair-sim-time-dev-1701.zip` with SHA-256 `1b063c7e502670f646984fa3dd64b963a4a77e1d46686f269e9bf353fcc15ef9`, valid CRC, unique names, manifest count and member hashes;
- the current `tools/benchmark/openvins_causal_input.py` bytes contained in that archive.

Any archive, audit, implementation, source result, destination, runtime binding or workload drift is a refusal.

## Frozen execution

`study-v17` must retain the exact `study-v16` execution contract: 25 s simulated duration, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGB-D, the same PX4/OpenVINS/native inputs, vehicle, gravity, trajectory gauge, supported-motion and lateral-force profiles, 200 ms future anchor, 8 s initial readiness limit, 2 s high-rate source/native/fan-out/supervisor wall watchdogs, 300 s worker/supervisor budgets and all safety limits.

The correction changes only the RGB/CameraInfo causal dependency clock. Its threshold remains 250 ms in observed simulation time. Host idle service calls cannot advance it; source simulation time cannot regress; a missing complement after more than 250 ms simulation time remains fail-closed. PX4 heartbeat liveness retains its already verified simulation-time rule. No timeout may be enlarged and no old frame may be replayed.

## Output and claims

The builder creates only a new directory containing copied immutable contracts, a `causal-pair-simulation-time-authorization.json`, regenerated runtime binding, execution contract and study manifest. `capture-v1` must not exist. All physical execution, runtime mapping/closure, VIO accuracy/health, fusion and flight claims remain false.

After `study-v18` passes an independent audit from committed code, exactly one startup preflight may run. It must exclude PX4, OpenVINS, physics, sensors, motion, ULog and fusion; its supervisor journal, cleanup and resource scan must pass. A later physical run requires another committed one-shot boundary and is outside this package task.

## Failure handling

Every rejected package and startup failure is retained. `study-v16/capture-v1` is immutable and is never overwritten or rerun. Failures before the fruit-fly policy executes cannot be attributed to training, weights, losses or swarm autonomy.
