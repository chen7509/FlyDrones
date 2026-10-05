# Disarmed motion probe: public-ready flag observed, dynamic VIO failed

One25s externally excited, disarmed PX4/Gazebo development run completed. **OpenVINS public initialized became true at5.4s, but its position diverged severely.** At24.9s, displacement from the4.9s pre-force reference was29.8005m in VIO versus0.26505m physically. The translation-error lower bound under any rotation of coordinates is29.5355m. **Reliable dynamic VIO and fusion remain unverified/failed.** This is not a fruit-fly learning or policy test, and no weights were trained.

Branch codex/openvins-motion-readiness, base ac77f7b/PR36. Spec/plan: docs/superpowers/{specs,plans}/2026-10-06-openvins-motion-readiness.md. Working evidence: results/openvins-motion-readiness-dev-1701. One physical attempt, no estimator tuning or replay.

## Change and source choice

The existing native shadow capture gains an optional externally forced simulator fixture. Installed Gazebo8.15.0 Link.add_world_force applies a world-frame force at base_link COM for one physics step. Pinned upstream taggz-sim8_8.15.0 resolves446a44335a45b704b4d36dabcc5508ee34eeb3d8; Apache-2.0, nonarchived, GitHub pushed2026-10-05. Link.cc, its Python binding, Physics.cc andLICENSE/metadata/hashes are retained. Physics clears the wrench component each step. The available ApplyLinkWrench transport plugin was not needed; direct per-step calls avoid its persistent-command/clear lifecycle. The older zero-gravity velocity-setter probe was rejected as inappropriate for this physical question.

The [Gazebo Link API](https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1Link.html), [OpenVINS zero-velocity discussion](https://docs.openvins.com/update-zerovelocity.html) and [OpenVINS ICRA2020 paper](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf) informed the design. Pinned OpenVINS6948812 library, native binary, camera/IMU calibration files and uncalibrated raw-model-zero-bias-diffusion-v1 config are byte-identical to sealed PR36. No ZUPT/initialization threshold, gravity, camera rate, physics step, noise or algorithm changed. No dependency install.

The prospective lateral-wrench-v1 profile applies world-y26N in two0.8s cycles during[5,6.6)s: +0.2s, -0.4s, +0.2s per cycle. Net impulse0; absolute impulse41.6N·s. The ideal free2kg calculation predicts2.6m/s peak and0.52m displacement, but this is not a physical performance claim; contact/friction are measured below. Active steps require a PX4-disarmed heartbeat no older than2s. Invalid/gapped1ms timestamps or missing/invalid physics state latch refusal. Fixture-only bounds are1m displacement,3m/s speed and45deg roll/pitch; the supervisor checks every10ms simulation rather than1s chunks. Physics remains1ms, raw IMU250Hz and160×120RGBD10Hz. Extra fixture logging/stepping overhead is not a capacity improvement.

Simulator truth is written to a separate motion-ground-truth stream and used only by the external fixture abort monitor and offline audit. The monitor has no reference to CausalInput or the native sensor client. No truth attitude initialization, pose/velocity teleport, camera-only animation, ODOMETRY publication, arming or motor command occurs. These fixture bounds are not an onboard flight safety layer.

## Actual evidence

|Item|Observed result|
|---|---|
|Capture|25s simulation,30.5065s capture wall time including setup/cleanup; no capacity RTF claim|
|Force|1600 nonzero1ms calls plus final zero transition; exact5.000–6.599s stamps; final transition6.600s; recorded net0/absolute41.6N·s|
|Physical containment|Maximum displacement0.412685m, speed2.22687m/s, roll/pitch0.007135deg; no fixture-bound refusal|
|End physical state|Position[-8.000175,-0.265046,0.227000]m, speed2.72e-6m/s|
|Sensors|6251 IMU,251 each RGB/depth/CameraInfo,24 disarmed heartbeat records|
|Native delivery|6501 acknowledgements,250 image payload hashes matched recorded pixels; final25s image retained with later_imu_missing|
|Initialization|Internal from2.4s (226 frames); public from5.4s (196 frames). Public flag stayed true through subsequent divergence.|
|Fast propagation|1129/1250 successful native targets,979 public-ready target flags; no repeated image or future IMU use|
|Position failure|At24.9s relative to4.9s: VIO29.800545m, physics0.265046m; norm-difference error lower bound29.535500m. No scale fitting or trajectory alignment used.|
|Latency scope|RGB callback→native end median11.5648ms/P9518.1123ms/max28.3678ms, not generation-to-actuator latency or full-fly decision time|
|Disarmed ULog|50 vehicle_status records, arming_state1; SHA3acc8e61bbcb1058b4150b8de96607064c937c4231bf87d630486990da3578af|
|Lifecycle|PX4/native exit0, no capture errors, pre/post source/config/model/binary hashes unchanged, no competing process left|

The source explanation from PR36 is borne out: genuine motion permits regular clone/update lifecycle and public flag progression. That flag is not an accuracy/observability/quality guarantee. A completed data collection is distinct from a passed estimator gate. All fusion fields remainfalse, quality/reset remainunknown.

## Sensor diagnostic and limits

Separate same-timestamp physics comparisons transform world acceleration minus the actual SDF gravity[0,0,-9.81] and world angular velocity into body FLU. During excitation,400 paired samples have accelerometer residual norm median0.01011/P950.01822/max0.02646m/s²; gyro residual median0.001324/P950.002372/max0.003438rad/s. Static and settled periods have similar residual scales. These observations do not identify the drift cause or prove calibration, camera timing/extrinsics, feature validity or estimator consistency. No sensor values were corrected using truth.

The first diagnostic audit mistakenly assumed gravity9.80665; its files remain retained as superseded audit.json/audit_motion_v1.py. audit-v2.json reads gravity from the sealed world. Physical/native inputs were not rerun; displacement traces are unchanged. The correction is analysis-only and cannot explain a29m discrepancy.

Next diagnosis must use this sealed failed dynamic input: examine real camera/IMU timing and frame/extrinsic conventions, accepted/rejected visual tracks/updates and numerical observability around the first divergence. Compare inertial propagation with visual updates without labeling a diagnostic ablation as a new full solution. Do not tune the force/noise/public gate to conceal the failure, change test scenes, or advance to EKF2 injection merely because public istrue.

|Status|Scope|
|---|---|
|Verified locally|Bounded physical force schedule, genuine raw sensor response, actual native online transport and public lifecycle transition, preserved disarmed/ULog/process evidence.|
|Only synthetic verification|Final close-failure retention and every-step nonfinite refusal; successful physical capture used the pre-review producer. Neither the fixture nor its tests qualify onboard safety or calibrated VIO health.|
|Untested|Root cause of dynamic drift, camera timing/extrinsic/visual-update validity, calibrated covariance, reset/quality/fault recovery and VIO→EKF2.|
|Failed / blocked gate|Reliable dynamic VIO:≥29.5355m terminal displacement error lower bound. Fusionfalse. Existing fruit-fly latency/collision and five-camera0.873RTF<0.95 remain unresolved; no20/100/HITL/real-flight pass.|

Tests before the physical run:17 new policy cases went from missing-interface RED to GREEN;62focused tests passed with existing native/capture cases. Before review,749 regression tests passed.

Independent fresh-context review found two Important issues and one Minor. The final fixture always retains its motion snapshot when individual stream closes fail, checks all required physics fields at every1ms step rather than only serialized samples, and registers cleanup before callback setup. Nine new cases reproduced the two faults before correction and then passed;71 focused cases passed. No findings were deferred. These fault-path corrections were tested synthetically, without repeating the physical run or estimator. Its producer9c6873f and unchanged pre/post manifests remain preserved.

The next diagnosis is scoped in the evidence's next-diagnosis-research.md. Existing states show displacement mismatch already at5.1–5.3s, before the first regular visual update at5.4s. This narrows where to inspect raw-to-native delivery, normal propagation and fast-cache interactions; it does not yet identify the cause. Camera/extrinsic/feature checks remain necessary. No correction or tuning was attempted in this stage.

Final regression: **758 passed**, two existing warnings,210.62s; focused71 passed. Ruff on the three changed Python files and diff whitespace checks passed. A separate final resource check found no active PX4/Gazebo/native replay or training process. Evidence includes all original failures, both analysis versions, source snapshots, configs, raw sensors/pixels, force/physics streams, ULog, review findings and RED/GREEN logs. Publication metadata follows in the closure commit.

Evidence seal: evidence/openvins-motion-readiness-dev-1701.zip,628 members/7,405,361 bytes, SHA256 **87a1eb39053ba72b84136908ae800799db7dc54b7fe81a64b20f5f4bd8e617b6**. Every member was checked against its size and SHA manifest after creation. The sealed source/report at2a4ee14 precedes this archive-metadata paragraph. All raw physical/estimator failures remain unchanged; final code is separately snapshotted from the actual producer.

Publication check found **full-repository Ruff fails with50 diagnostics in32 unchanged base files**, while changed-file Ruff passes. Each diagnostic file and pyproject.toml were compared with ac77f7b and are unchanged. The template's combined full-lint/test checkbox therefore remains unchecked. Supplement evidence/openvins-motion-readiness-publication-checks.json retains all diagnostics and base-file hashes; it postdates the immutable ZIP. The sealed report's unqualified word “Ruff” refers only to changed-file checking and is clarified here. No unrelated formatting cleanup was folded into this physical-readiness experiment.

Publication closure: draft PR37 https://github.com/chen7509/FlyDrones/pull/37, stacked onPR36 and attached to the current task. Physical producer9c6873f, reviewed fault fixes2a4ee14, immutable archive9e9e6c7, full-lint limitation e2a4c3d. This closure postdates the seal. The existing continuation remains active for fixed-input dynamic failure diagnosis; this is completion of the experiment/report, not the VIO or swarm goal.
