# Heartbeat commit-order retry package design

## Goal

Create a new prepare-only package from the immutable `study-v19` physical
failure and the sealed heartbeat commit-order correction. The package must not
start PX4, Gazebo, OpenVINS, training, sensors, physics or motion.

## Inputs and fail-closed checks

- Require the exact `study-v19` package, its single `capture-v1`, physical
  completion and independently qualified one-shot boundary.
- Require the zero-failure `heartbeat-commit-order-audit-v1`, including the
  10 ms heartbeat lead, 0.988 s previous-heartbeat age, pre-arrived IMUs at
  2.608/2.612 s, zero force/impulse and closed fusion/policy claims.
- Pin `evidence/heartbeat-commit-order-dev-1701.zip` by name and SHA-256;
  verify CRC, unique names, manifest membership, every member hash, external
  audit byte identity and archived/current `readiness_anchor.py` identity.
- Preserve the 25 s, 1 ms, 250 Hz, 10 Hz 160x120, vehicle, gravity,
  estimator/native inputs, motion profile, safety gates, 10 s startup and 2 s
  operational limits. Do not repeat frames or enlarge timeouts.
- Reject source, archive, implementation, runtime binding, command, workload,
  destination, resources or positive-claim drift.

## Output

Generate a fresh `study-v20` directory containing copied immutable contracts,
a heartbeat commit-order authorization, rebuilt runtime binding, execution
contract and manifest. `capture-v1` must remain absent. All physical, VIO,
fusion, flight and fruit-fly claims remain false.
