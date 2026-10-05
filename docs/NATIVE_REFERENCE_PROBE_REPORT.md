# Native diagnostic reference overwrite — development 1701

**The new diagnostic child was overwritten on all 25,000 physics cycles, and supported-motion raw IMU consistency meets the predeclared numeric criteria.** This is a single disarmed sensor-only development capture. OpenVINS, learning, ODOMETRY and EKF2 injection were not run; fusion remains false.

## Implementation and research choice

Instead of a separately scheduled System plugin with a new Stop/IPC path, a small native pybind extension runs synchronously inside the existing TestFixture System callbacks. The installed gz.sim8 ECM type was successfully consumed in an ABI probe. Native pre-check runs before the force fixture; post-check runs before the original motion monitor. Native exceptions, native-reference journal errors and safety refusal populate the same capture error list, checked before every subsequent force step even inside a multi-step server.run chunk. Existing CaptureJournal/owned PX4 cleanup remains. The separate asynchronous sensor writer's error is checked by the outer server-chunk loop; the new per-step guarantee does not extend to that unchanged mechanism.

The extension creates exactly one zero-offset non-Link/non-Sensor child (parent24,child69 in this run). Only its derived world pose/velocity/acceleration/angular-velocity outputs are poisoned each PreUpdate; PostUpdate requires finite replacement and unit quaternion. Physical links, local pose, gravity, sensor input and force commands are not modified. New state has an independent unchanged1m/3m/s/45° abort monitor, alongside the original monitor. Production API1 rejects a test-enabled module, requires the binary SHA and does not export synthetic state injection helpers. The test module is separate.

Pinned gz-sim446a443 Apache-2.0 TestFixture and Physics source, installed pybind11 2.11.1 BSD-3-Clause, exact build flags and [official pybind cross-module documentation](https://pybind11.readthedocs.io/en/stable/advanced/misc.html#partitioning-code-over-multiple-extension-modules) were checked; fixed v2.11.1 documentation/license and repository maintenance snapshots are sealed. Metadata records both non-archived, with gz-sim last push2026-10-05T03:38:09Z and pybind11 last push2026-10-05T14:51:42Z; activity is not a support guarantee. The [OpenVINS ICRA2020 paper](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf) supplies estimator context, not certification of this probe. No dependency installation. Reusing TestFixture avoids adding another asynchronous control/cleanup path; middleware upgrades and physics-engine patches were rejected as unnecessary for this diagnostic.

## Frozen physical capture

One capture-v1, producer `e28fcc3`, production binary SHA256 `303b575e29d44bf50850ad03e3d3b865207a225e366418ec5733ed5292cc18ce`. Input/output source and binary hashes match before/after. The explicitly named supported-ready-native-reference-v1 adds diagnostic CPU/journaling work while preserving25s/1msphysics/250HzrawIMU/10Hz160x120RGBD/body/gravity/noise and original ready/force/safety conditions. This is not a capacity optimization or performance comparison.

Readiness selected1.617s, immutable anchor1.817s; lift1.817–3.817s and lateral4.817–6.417s. There are23,184support steps,1,600lateral steps,25,000native pre/post acknowledgments,50,000old Link trace records,6,251IMU and251each RGB/CameraInfo/depth.24heartbeats and51ULog vehicle-status records are all unarmed. Minimum recorded ground clearance after lift0.3999994m. ULog SHA256 `44589038f6646e32cc5bffa13426f4a6e88cdc756f92f5b2ceccfa57cad1d0b6`. Process exit0, PX4 normal cleanup, no related processes remain.

## New versus cached reference

| Window | Child1kHz right integral error m/s | Old Link error m/s | Raw IMU trapezoid error m/s |
|---|---:|---:|---:|
| Lateral first100ms | 1.90e−21 | 1.90e−21 | 0.00023976 |
| Full lateral1.6s | 3.23e−20 | 0.0244670 | 0.00104709 |
| Settled1s | 2.32e−20 | 12.2335227 | 0.00075993 |
| Lift2s | 1.56e−17 | 0.00069044 | 0.00134664 |

Raw intervals use actual available samples and their matching child-state endpoints:4.820–4.916s (96ms/25samples) within the first100ms window, and4.820–6.416s (1.596s/400samples) within the full lateral window. No endpoint interpolation or favorable phase selection. These satisfy the original0.02/0.05m/s criteria under the documented sample-bracketing rule. The child full-lateral trapezoid error is0.00611676m/s; one250Hz right-endpoint phase gives0.03670057m/s while the other three are near numerical zero. All phases and failures are retained; do not report universal exact discrete integration.

Old/new differences also occur during initial ground contact: maximum velocity difference2.227859m/s and acceleration difference2237.669m/s² at0.228s; maximum position discrepancy is about1e−6m. The new probe does not remove initial contact transients or prove raw250Hz inertial accuracy throughout all startup intervals. The supported-motion criteria and per-step overwrite evidence support the next estimator study, not the claim that all prior VIO drift is fixed. PR39's old ground-contact aliasing and PR37's29.5355m VIO error lower bound remain independent failed evidence.

## Validation and remaining boundary

Initial Python module RED, two integration RED cases,111targeted tests passed;9native synthetic cases passed (success, unconsumed/partial canary, quaternion/topology/epoch/sequence/session faults). Production import/hash and absence of test mutation exports verified; missing physical parent refuses and latches. Native failure in synthetic callback integration prevents every subsequent motion call; writer short/flush/close and terminal refusal tests retain failure. These tests do **not** demonstrate a deliberately injected native fault while a real PX4/Gazebo capture is running. Actual normal-path owned PX4 cleanup passed. A short, separately frozen runtime refusal/cleanup experiment remains before online VIO integration; it must preserve gates and use no state injection into VIO.

Independent review found no Critical/Important issues and two Minor issues: native synthetic runner persistence and overbroad wording about writer-error timing. The runner is now checked into tests/native/native_reference_synthetic.py and its nine cases were rerun successfully, and the per-step guarantee is explicitly scoped to the native-reference journal. Both were resolved in the same review pass without changing the capture producer. Audit review confirmed matching raw endpoints and transform/integral logic, with sample-bracketing clarified above. Full regression: 895 passed, two existing loader warnings, 215.98 seconds. Changed Python files pass Ruff; whole-repository lint retains the existing 50 errors in 32 unchanged files, not a whole-repository pass.

| Status | Scope |
|---|---|
| Verified | ABI, native synthetic refusals, production isolation,25,000actual canary replacements, complete disarmed capture and supported-motion consistency/normal cleanup. |
| Implemented | Native diagnostic bridge, fail-closed callback ordering, separate journal/abort monitor and module hash gate. |
| Untested | Deliberately injected native failure with actual PX4/Gazebo cleanup; online OpenVINS under this supported condition; reliable quality/reset/covariance and EKF2 fusion. |
| Retained failures | PR37 VIO drift; PR39 initial ground-contact aliasing; PR40 fixed-start failures; original stale Link diagnostics; five-camera0.873RTF<0.95. |

Next complete the bounded real runtime refusal/cleanup check without another25s normal trial, then design native-reference plus online OpenVINS recording with a composite source callback. The current writer chooses readiness **or** shadow handling; simply allowing both CLI options would starve the shadow input. Preserve actual causal source delivery, both failure paths, timing evidence and single native estimator ownership. Do not loosen public initialized, fabricate quality/reset, or start ODOMETRY/arming/EKF2 before reliable public VIO evidence.
