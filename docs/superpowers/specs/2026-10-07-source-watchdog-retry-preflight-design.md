# Source-watchdog retry preflight design

## Scope

Create one new prepare-only study after the immutable `study-v18/capture-v1` startup-cohort refusal and the committed source-watchdog correction. The package must not start PX4, Gazebo, OpenVINS, physics, sensors, motion, training, ODOMETRY, EKF2 injection or fusion.

## Frozen evidence

The builder accepts only the immutable `study-v18` failure, its one-shot completion and physical-boundary audit, the zero-failure `source-watchdog-startup-cohort-audit-v1`, and `evidence/source-watchdog-startup-cohort-dev-1701.zip` with SHA-256 `9899cf5d0908cfa07eb6bcacde334292b67760ee842b7e481051c66b1cf63d98`. It verifies ZIP CRC, unique names, manifest membership, every member size and hash, audit byte identity, and byte identity between the archived and current `openvins_online_shadow.py`.

The source failure remains `source silence: imu` at 10 ms simulation time. The authorization records the measured stale first IMU, the sub-millisecond next-IMU arrival after refusal, and the fresh counterfactual three-source cohort. It keeps the 10 s startup and 2 s operational wall limits unchanged, repeats no frame, and leaves all physical, VIO, fusion and flight claims false.

## Output and execution boundary

The new study copies the frozen contracts, recomputes a complete runtime-binding baseline, and emits the same 25 s / 1 ms / 250 Hz / 10 Hz 160x120 workload at a fresh `capture-v1` destination. An independent auditor recomputes source, evidence, binding, command and execution identity and rejects an existing destination or active resource.

After the implementation is committed, one new package may be generated and audited. A separate startup-only preflight may then run at a distinct destination; it must stop before TestFixture, PX4 or OpenVINS. No physical retry is authorized in this stage. A physical attempt would require another committed exact-head one-shot boundary.
