# OpenVINS raw input profile and causal schedule — development evidence

This stage prepares the input interface to the native estimator using sealed PR34 capturev2. It does not run OpenVINS, another physical capture or flight commands; fusion remains false. The original evidence and failed gates remain unchanged.

## Research and design choice

Upstream source, licenses and activity were checked before implementation; raw GitHub responses and hashed source snapshots are preserved under results/openvins-causal-input-dev-1701/. Existing native OpenVINS and Gazebo transport are reused conceptually; no new dependencies or estimator configuration is installed.

|Candidate|Version/license/activity|Interface, resources and decision|
|---|---|---|
|Gazebo Gaussian IMU source|Upstream sensors8.2.2 tag9348f9fe8a11b9d50381819f51e17e136aedab8a; Apache-2.0. Prior PR34 metadata: nonarchived, pushed2026-10-02.|Per-axis per-update noise. Model rates/values independently checked against sealed actual fixture. Tag source is not a binary attestation of downstream distro patches. Use existing raw callback data, not sensor orientation/pose.|
|OpenVINS native input semantics|69488123ed9362dd44b6f28e7f4680abbff1442b; GPL-3.0; nonarchived, pushed2025-11-30.|ROS1Visualizer waits until a strictly later offset-adjusted IMU exists. Reuse this causal rule without installing ROS. Native Propagator maps continuous variance to discrete usingdt; this stage does not execute it. No native compute-resource claim.|
|PX4 DDS or MAVLink IMU|Pinned PX4d6f12ad; BSD-3-Clause. Existing PR34 research retained.|DDS defaults100Hz and needs absent Agent/subscriber runtime; HIGHRES_IMU bias subtraction and SCALED_IMU integration/quantization differ. Retain explicit raw profile; no silent switch. Runtime adaptation cost exceeds this file-only contract.|

Primary references: [GaussianNoiseModel at fixed tag](https://github.com/gazebosim/gz-sensors/blob/9348f9fe8a11b9d50381819f51e17e136aedab8a/src/GaussianNoiseModel.cc), [ImuSensor at fixed tag](https://github.com/gazebosim/gz-sensors/blob/9348f9fe8a11b9d50381819f51e17e136aedab8a/src/ImuSensor.cc), [OpenVINS calibration guide](https://docs.openvins.com/gs-calibration.html), [OpenVINS ICRA2020 paper](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf). The paper motivates the estimator; it does not qualify this raw-input profile. A short stationary capture cannot establish dynamic extrinsics, clock calibration or bias noise.

The model profile preserves gyro per-sample stddev0.0008726646rad/s and acceleration0.00637/0.00637/0.00686m/s² at250Hz. Density candidates use stddev×sqrt(.004), with all axis values retained and a scalar maximum-axis envelope explicitly labeled as a candidate. Bias random walk is unknown/null rather than copied from the old ULog profile. No candidate is written into OpenVINS YAML. Covariance stays uncalibrated. Static optical-to-FRD extrinsics and captured camera intrinsics remain explicit, with dynamic/time-offset validation outstanding.

## Contract and evidence

The single-owner scheduler accepts imu/rgb/info with explicit session, clock and consecutive input index. It deep-copies pending records, preserves raw sample/arrival clocks and converts FLU vectors once to FRD. Each IMU emits once. A camera requires the same-stamp CameraInfo, available IMU history and a consumed strictly later IMU. The scheduler processes recorded submission order; it never globally sorts acquisition times or reads a future row to release current data. Eight pending records per image/info stream,250ms wall wait,200ms image–IMU sample lag and4ms maximum IMU gap are explicit development transport refusal limits, not estimator performance or safety acceptance thresholds. Rejection latches; tick supports silent-source expiry; EOF retains pending records. It cannot infer resets or grant health.

The PR34 archive SHA7d747d0c841ce6e13bc9614cc9b23381c45b260170f98ac2fdad7ce8bc78313d and every indexed member hash were verified before conversion. Source events SHA5c19bd1afc81dbac44d8ebb9bffd42b85845bd604ada88bc77daa67a6405fcfd. All6753 relevant input entries are indexed:6251 IMU,251 RGB and251 CameraInfo. The first conversion emits6251 IMU and250 camera deliveries. The last25s frame is retained with both message indices and reason later_imu_missing. No repeated image fills a higher rate.

Six synthetic mutations of the fixed trace are rejected: missing/duplicate IMU, missing CameraInfo, nonfinite gyro, changed intrinsics and forbidden pose field. Failure reasons are preserved. Initial15 tests failed before implementation then passed; two additional stale-enqueue/boolean-calibration boundary tests failed and passed after guards, for17 targeted tests. Full regression and independent review results appear in closure.

The recorded-arrival watermark wait median/P95 is0ms, maximum0.590029ms: most image callbacks arrived after the relevant IMU. This is only a trace-order causal availability calculation. It excludes processing/native estimation and is not zero transport or end-to-end latency. The first offline schedule conversion took0.0910s total; it is not an online throughput or repeatability result.

|Status|Boundary|
|---|---|
|Verified locally|Raw source noise units/model correspondence; causal schedule and full relevant-input accounting; analytic vector conversion and boundary/fault rejection.|
|Only implemented|Transport-independent native-delivery schedule and descriptive input profile. No native consumer or pixels delivered to OpenVINS.|
|Untested|Applied noise model validity, dynamic calibration, actual online estimator throughput/reset/health/public availability, VIO→EKF2 fusion and faults.|
|Still failed|Earlier physical collision/full-fly latency and five-camera0.873RTF<0.95. No20/100/HITL/real-flight gate passed.|

Next: bind this single-owner contract to the pinned native OpenVINS consumer with explicit pixel ownership, steady-clock processing evidence, initialization/reset states and bounded lifecycle. Validate that bridge before a new disarmed online shadow run at unchanged10Hz camera/physical load. Public initialized/quality/fusion gates remain closed; no old-frame repetition, truth initialization or synthetic reset counter.

Rulings: verify the source-independent contract before native integration, adding a bounded stage to avoid silently changing sensor semantics; preserve working evidence and failures, costing disk space. No additional physical or estimator run was made for this stage.

Pre-review full regression: **704 passed in212.85s**,2 existing warnings. Boundary-guard parity check confirms all6501 fixed schedule entries and the pending record unchanged. Ruff/diff checks passed. Independent review pending.

Independent review found0 Critical,2 Important and1 Minor. Important findings were lost disposition for an IMU triggering a release failure and numeric overflow escaping the failure latch. The Minor allowed a boolean distortion enum to compare equal to0. All three were corrected in one pass: acceptance rolls back its tentative state and retains a structured refused input, overflow latches permanently, and scalar calibration fields require integer types. Three new regression tests failed before correction and passed after, making20 targeted tests. The Minor was included under the user's explicit request to close all gaps, at the cost of one extra regression case; none is deferred.

Final fixed-input conversion preserves byte-identical6501 normal delivery actions and the pending last frame; six synthetic faults now include structured source-sequence/input dispositions. Invalid NaN is stored as an explicitly labeled invalid literal, not silently replaced with a valid measurement. Final offline conversion took0.1713s; this includes transaction copying and is not native inference latency. The earlier conversion and all failed tests remain retained. No second review or estimator/physical replay was used.

Reviewer-declined boundaries remain explicit: native pixel/estimator lifecycle and throughput; actual physical calibration; whole-source health when no camera/info is pending (tick currently promises only pending-input expiry); flight/fusion/public readiness. Evidence sealing and publication are performed after review. These deferrals do not imply those capabilities are verified.

Final full regression: **707 passed in210.13s**,2 existing warnings;20 targeted cases passed. The final checker separately verified the six structured refusals and unchanged fixed schedule after the fixes. Ruff and diff checks passed. No competing simulation or training process was found in the recorded process checks.

Publication closure: draft PR35 https://github.com/chen7509/FlyDrones/pull/35, implementation42c8def, reviewed fixes400833f, evidence751ff04. Archive62members/2,309,902bytes, SHA256 **8ac5a374cb4a5aef97d20e8a4a43d7128d7f7d0d4c8ac88a7b658c5fc9df4fb8**. This closure and completed publication checkbox postdate the sealed snapshot; archive unchanged. Reproduction depends on the unchanged sealed PR34 source archive identified above.
