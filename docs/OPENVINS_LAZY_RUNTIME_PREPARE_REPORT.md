# OpenVINS Lazy Runtime Prepare Integration Report

## Result

The prepare-only integration passed its independent audit. The generated runtime-binding baseline now prospectively declares the one previously qualified OpenVINS lazy mapping:

`/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2.11`

The declaration is limited to the exact Ubuntu `libtbbmalloc2:amd64` package version `2021.11.0-2ubuntu2`, exact file identity and SHA-256, the preserved package archive, oneTBB upstream tag `v2021.11.0` at commit `8b829acc65569019edb896c5150d427f288e8aba`, and the trigger `first_acknowledged_imu`. Every other unknown runtime mapping remains subject to the existing runtime-binding v3 refusal.

This stage created a command for a future physical study but did not execute it. It did not start OpenVINS, PX4, Gazebo, training, a capture worker, or physics. No `capture-v1` directory exists.

## Inputs and failure retained

The preparation consumed the retained PR61 `dry-v5` preflight package and the PR62 lazy-runtime closure evidence. It independently recomputed the PR62 audit, required it to equal the stored final audit, and incorporated every referenced source record plus the generated lazy-runtime contract into a fresh runtime-binding baseline.

The first formal preparation attempt stopped before creating a study because the new validator required a downstream claim field that the PR61 source schema does not define. That failure is retained in `prepare-failure-v1.txt`. The validator was narrowed to the false claims actually defined by the PR61 schema, covered by regression tests, and the corrected preparation was run once. This was a metadata validation defect; it was not an OpenVINS, PX4, Gazebo, VIO, training, or fruit-fly policy failure.

## Fixed output

The successful `study-v1` contains exactly five files:

- `execution-contract.json`: 4,423 bytes, SHA-256 `95df71ac81d621a1fe92ec1b2adff437fa9b34ab20598fd147232162e052d891`
- `lazy-runtime-contract.json`: 21,086 bytes, SHA-256 `caa64813b32cc19967e9c12365bcccbe4c62edbe065ae2a2538db4909a79b233`
- `runtime-binding-v3.json`: 459,308 bytes, SHA-256 `840b909a4e769e5f77f84e401d23479670f96d1f68b5014f74df40243448fb55`
- `study-manifest.json`: 12,495 bytes, SHA-256 `9254f24806177864a818f3b170ac67ff53200f08d9a463f25ebb846681ac8ece`
- `trajectory-gauge-policy.json`: 1,031 bytes, SHA-256 `a97bc126e90e0bfb88cc995f782904a7a842e460854dbd71cec977cd98800463`

The independent `openvins-lazy-runtime-prepare-audit-v1` reported no failures and set only `prepare_qualified=true`. It explicitly kept physical execution, whole runtime mapping coverage, runtime closure, VIO accuracy, estimator health, fusion, and flight false.

The generated execution contract preserves the 25-second study, 1 ms physics step, 250 Hz raw IMU, 10 Hz 160x120 RGB-D, supported-motion and substep profiles, journaled heartbeat fan-out, 300-second wall and supervisor limits, and the frozen trajectory-gauge policy. These are declared future inputs; they were not exercised in this stage.

## Verification

- Focused preparation and audit tests: 18 passed.
- Full regression: 1,339 passed, 3 skipped, with 2 existing warnings, in 314.07 seconds.
- Changed-file Ruff: passed.
- Source-tree Ruff: 53 findings in 34 unchanged files, equal to the established source-tree baseline.
- `git diff --check`: passed.
- The final process scan found no remaining PX4, Gazebo, OpenVINS, capture, training, or pytest process.
- The successful study has no `capture-v1` member or directory.

## Classification

**Verified:** the exact PR61 and PR62 sources, stored and recomputed PR62 audit equality, narrow package/upstream/trigger contract, fresh runtime-binding inventory and baseline, copied trajectory-gauge policy, recomputed execution contract and absolute command, exact five-member output, and independent prepare-only audit.

**Implemented but not physically exercised:** the prospective allocator declaration in a future capture package and the generated worker command.

**Not tested:** OpenVINS startup under the new binding, later lazy mappings, PX4/Gazebo motion, journaled heartbeat behavior online, VIO accuracy and estimator health, reset/quality/covariance behavior, ODOMETRY publication, and VIO-to-EKF2 injection.

**Still failed or blocked:** the PR61 `dry-v5` physical attempt remains a safe prelaunch refusal and is not relabeled. PR48 remains a 6.417-second health refusal with indeterminate accuracy. The earlier 29.5355 m displacement-error lower-bound failure, contact/mixing diagnosis, startup failure, five-aircraft 0.873 RTF capacity failure, and hardware/native-Linux/flight dependencies remain unchanged.

## Next gate

A new physical study may now be designed from this audited prepare-only package. Before execution it must retain the fixed workload and safety limits, preserve the declared runtime closure and trajectory-gauge checks, and treat any new unknown mapping or source-health failure as a refusal. The study must preserve all failures and cannot interpret a platform watchdog or runtime-declaration failure as a fruit-fly learning failure. Reliable public VIO plus loss/reset, quality, and covariance evidence is still required before ODOMETRY publication, arming, or EKF2 injection.
