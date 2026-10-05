# Native OpenVINS online shadow: development evidence

This stage delivers actual raw Gazebo IMU and owned RGB bytes to the pinned native OpenVINS library during a new, disarmed PX4/Gazebo run. **The25s online shadow completed; public initialized stayed false throughout, so fusion remains false.** This is neither flight validation nor evidence that the full fruit-fly decision latency is solved.

Spec/plan: docs/superpowers/{specs,plans}/2026-10-06-openvins-online-shadow.md. Working evidence: results/openvins-online-shadow-dev-1701. Stack base: PR35 ce61a0e. Independent review is closed below; archive/publication metadata is appended after sealing.

## What changed and why

The PR35 CausalInput now feeds a single-owner native worker through a one-request-in-flight bounded pipe. Images are exact160×120×3 owned RGB bytes; the native worker accepts no image filename or truth pose, converts RGB to grayscale and waits for a consumed later IMU. A separate acknowledgement descriptor retains actual header receipt, native processing and return clocks, checked against Linux monotonic time on every request. Public initialization is not overridden. The native fast propagator creates fresh20ms targets after causal IMU receipt, with unavailable targets retained; it never repeats an old image to create frequency.

The existing recorder persists raw events/pixels before handing them to the native consumer. A consumer failure latches delivery off while raw records remain available. Source presence, native write/processing deadlines and the existing outer process-group supervisor cover different failures. There are no ODOMETRY messages, flight commands, EKF2 injection or arming actions.

Research and local source snapshots are retained in research.md and upstream-snapshots-v4. OpenVINS69488123ed9362dd44b6f28e7f4680abbff1442b (GPL-3.0), existing librarySHA532ae57a6a952a0137cc1de291bc47ad556d419c7524fbb23b7a90c00addab5b, Gazebo sensors8.2.2/Apache-2.0 and PX4d6f12ad/BSD-3-Clause are unchanged. Upstream local initializer logging patches and their diff are retained. The [official API](https://docs.openvins.com/classov__msckf_1_1VioManager.html), [calibration guidance](https://docs.openvins.com/gs-calibration.html) and [ICRA2020 paper](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf) support the adapter choice, not a claim of calibrated or flight-qualified output. ROS/DDS installation and EKF-bias-corrected HIGHRES_IMU were rejected for the current raw-source question. Version/license/maintenance/interface/resource/adaptation decisions are recorded before the live runs.

The frozen **raw-model-zero-bias-diffusion-v1** development configuration uses gyro density5.519215538799549e-5 and accelerometer density0.0004338644949751016, derived from maximum-axis model sample standard deviations×sqrt(.004). Bias diffusion0 is an explicit ideal SDF-model assumption, not empirical bias calibration. Dynamic calibration, scalar anisotropy approximation and covariance calibration remain unverified. Other estimator settings are inherited unchanged. No post-run noise tuning was performed.

## Actual runs and failures

Two setup-only source snapshot attempts failed before starting either native estimator or simulation: the sparse checkout did not materialize its root LICENSE; guessing LICENSE.txt was also wrong. The verified git HEAD:LICENSE blob resolved this. Both partial snapshots and error records remain.

**capture-v1 failed** after1s simulation: first RGB arrived4.040s after native process creation and the initial2s source guard incorrectly treated cold startup as operational source loss. It delivered251 IMU/10 images (261 acknowledgements), with no public/internal initialization and no heartbeat yet. ULog remains retained. This is a harness startup failure, not fruit-fly or VIO algorithm failure.

The explicit prospective correction separates a10s first-all-sources startup deadline from the unchanged2s operational source-silence deadline; native write/processing deadline stays2s. A regression test failed then passed. **capture-v2** uses the same frozen estimator config, scene,1ms physics,250Hz IMU and10Hz160×120RGBD. No load or existing acceptance threshold was reduced. Its complete25s simulation occupied29.981s capture wall time including setup/cleanup; this ratio is **not** a measured steady-state capacity RTF or the five-machine gate.

|Evidence|capture-v2 result|
|---|---|
|Raw inputs|6251 IMU;251 each RGB, depth and CameraInfo;24 disarmed heartbeat records|
|Native input|6251 IMU+250 RGB images=6501 checked acknowledgements; all250 transferred RGB payload hashes match closed recorded PPM payloads|
|Last image|25s frame retained, later_imu_missing; not duplicated or forced through|
|Camera state|226 internally initialized frames;0 public initialized;225 ZUPT-latched frames|
|First initialization evidence|Initializer reference1.312s; successful camera2.4s; state2.4s; that camera native processing2.459940ms. These are different clocks/meanings, not a1.312s computation time.|
|50Hz native targets|1250 attempted;1129 successful,121 unavailable;0 public initialized. All targets used an actually received IMU3ms after the target, not future data.|
|Numerical checks|1129 finite13-state/12×12-covariance outputs; quaternion norm error≤1.12e-16; covariance symmetry error≤5.56e-17; minimum symmetrized eigenvalue3.046e-6. Numerical consistency is not calibration.|
|Disarmed ULog|50 vehicle_status entries, arming_state1 throughout; SHA597dd2d7955231270c316d98dd387a5d28e76f24a9ebb13efd931dd54ac33bd2|
|Lifecycle|Native exit0/PX4 exit0; no capture errors; pre/post code/config/model/binary hashes identical; no competing process left in recorded checks|

The fixed VioManager.h public initialized() requires both is_initialized_vio and timelastupdate!=-1. VioManager.cpp returns early after an accepted stationary ZUPT, before setting timelastupdate. The run's last_regular_update_s remains-1. Thus internal state and fresh propagation exist while the public availability contract remains closed. This evidence does not justify bypassing that contract.

## Measured timing, limited to this disarmed development run

|Actual measured interval|Median|P95|Maximum|
|---|---:|---:|---:|
|IMU native work (including due propagation)|0.004295ms|0.486005ms|5.659853ms|
|Image native camera call|0.600799ms|1.099798ms|7.880864ms|
|IMU callback arrival→native end|1.258249ms|10.406776ms|54.579106ms|
|RGB callback arrival→native end|10.815140ms|17.583571ms|32.393702ms|
|RGB callback arrival→acknowledgement|11.232725ms|18.057325ms|33.575461ms|

Camera processing begins after header/payload parsing and grayscale conversion; callback-to-end includes those and causal buffering. These are real wall intervals inside the online adapter. They exclude sensor-generation/render latency before the callback, and are not complete sensor-to-actuator latency, airborne performance, or full fruit-fly inference latency. The3ms target/boundary gap is simulation sample time, not communication or end-to-end time.

## Verification and remaining boundaries

Before integration,13 unit cases passed after missing-interface RED; synthetic POSIX checks covered valid RGB conversion,11 malformed/boundary packets, output overwrite, actual cross-process clocks and a blocked pipe (0.2525s refusal at a0.25s test deadline). Three missing-adapter tests failed then passed; the startup correction adds a separate RED→GREEN case. Focused regression:57 passed. Full regression and independent review are recorded in closure below.

|Status|Scope|
|---|---|
|Verified locally|One complete disarmed online native shadow with actual pixels/raw IMU, causal order, measured callback/native clocks, unavailable outputs, source/native failure guards tested, ULog and process cleanup.|
|Only implemented|Diagnostic single-owner adapter and model-only noise configuration; not a qualified external-vision publisher or calibrated estimator.|
|Untested|Dynamic motion/calibration, repeated-run latency distribution, real sensor timing, estimator resets/quality, VIO→EKF2 injection and fault recovery, flight performance.|
|Failed / gate closed|capture-v1 startup failure retained; public initialized0/250 in v2, all fusion false; previous physical collision and full-fly latency remain unresolved; five-camera0.873RTF<0.95 remains failed. No20/100/HITL/real-flight qualification.|

Next dependency: resolve the stationary ZUPT/public readiness lifecycle through pinned upstream research and a separately designed development experiment, preserving the gate. Verify actual public-ready output and loss/reset handling before VIO→EKF2 injection. Do not jump from internally available propagation to fusion or arming. Other broad algorithm/swarm work remains under the existing roadmap; this stage does not complete the drone goal.

## Review closure

Pre-review full regression: **724 passed in211.40s**,2 existing warnings. One fresh-context independent review identified3Important and0Critical/Minor: constructor cleanup before caller ownership, missing dispositions after a partially delivered release batch, and a freeze manifest that did not constrain the selected config. All were addressed in one pass. Eight new unit cases failed before the fixes and passed afterward; five real POSIX setup injections went from live child/descriptor leakage to no leaks.65focused tests pass. A fresh synthetic native protocol check validates the hardened client's normal/invalid paths and blocked-write refusal0.2519s. No second review was used.

The successful physical capture-v2 was **not rerun after failure-path hardening**. Its exact pre-review source is retained in producer-v2-before/after; final code is separately snapshotted. The native binary/library/noise configuration are unchanged. Final code evidence for the review fixes is synthetic failure injection plus regression, not a claimed new live estimator run.

Reviewer-declined independent numerical/hash/ULog reruns, binary rebuild, visual inspection, dynamic calibration, capacity, fusion and flight remain explicit limits. Rulings: standing authorization covers implementation and draft publication; preserve ledgers/failed attempts at disk cost; bytes-only image transfer excludes path ambiguity; zero bias diffusion is model-only and may be optimistic; the startup/operational split fixes a measured harness lifecycle defect without changing flight/VIO/RTF gates. Preparatory next-readiness-research.md records why merely disabling ZUPT also changes initialization and is not a proven fix.

Final full regression: **732 passed in201.03s**,2 existing warnings. Final focused regression65passed; fivePOSIX setup failure cases and15native synthetic protocol checks passed. Ruff and diff checks passed. No deferred Minor remains. Current stage has reviewable results; public readiness and subsequent fusion/flight stages remain incomplete.

Evidence seal: evidence/openvins-online-shadow-dev-1701.zip,903members/7,832,531bytes, SHA256 **8aab46377da3016b9cdc4e595fbaf8316383a3b75cbe5e36505545e0434c30fa**. Every member was verified against its byte count andSHA manifest after creation. The sealed report/source at0a093d8 precedes this archive-metadata paragraph. Final resource check found no competing PX4/Gazebo/native/training/test process. All two physical attempts, two prelaunch failures, RED/GREEN logs and independent review remain sealed.

Publication closure: draft PR36 https://github.com/chen7509/FlyDrones/pull/36, stacked onPR35. Native transport ed4fc83, online integration066e9f9, reviewed failure fixes0a093d8, sealed evidence d722355. This publication paragraph and ledger closure postdate the immutable evidence snapshot. Next dependency is recorded in the sealed next-readiness-research.md; no additional estimator or physical run was started during publication.
