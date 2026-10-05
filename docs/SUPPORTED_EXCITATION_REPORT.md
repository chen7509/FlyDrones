# Supported excitation development1701 — blocked before force

**No sensor-consistency success or VIO success was obtained.** This stage implemented and tested an explicit sensor-only external force fixture, but both physical attempts stopped before any force call. No estimator or training ran; fusion remainsfalse.

The proposed supported-lateral-v1 condition keeps25s/1msphysics/250HzrawIMU/10Hz160x120RGBD and the original total±26N lateral excitation. Six link COM forces distribute fixed-mass support, with a time-only quintic0.4m lift from2–4s. Simulator position never controls force or enters VIO; it only bounds motion and audits ground clearance. This is a new development condition, not a pass of old ground-contact tests or drone flight control. Increased fixture logging/omitted native worker changes workload; no performance conclusion.

## Attempts and failures

1. **capture-v1, producerd01d55d:** stopped at10ms due to missing Python `Link.gravity_enabled`. The C++ API exists but installed and fixed upstream Python binding do not expose it. ThreeIMU/oneRGB-info-depth, zero forces, no ULog generated. Owned PX4 required SIGKILL during cleanup; process check subsequently empty. All failure files retained.
2. **capture-v2, producer2996b84:** after replacing the unavailable method with runtime World.gravity plus explicit SDF configuration validation/hashes, progressed to2s and stopped at the first planned support force because no valid disarmed heartbeat had yet arrived. Zero force calls;3999pre/post trace rows and1999clearance rows retained. This is a correct safety refusal and an unresolved startup scheduling design issue. No attempt was made to disable the heartbeat check or tune force/thresholds. PX4 exited normally; resources empty.

Per-link gravity is **validated SDF configuration**, not observed runtime GravityEnabled. Runtime world gravity and link masses were read and saved in support-links.json. Binding correction added five passing configuration fault/normal tests; the initial file named binding-red.txt actually ran after the implementation became visible and contains passes, so it is not a synthetic RED claim. The actual integration failure is retained in capture-v1. The initial module-import RED and subsequent targeted tests are separate evidence.

## Validation and limits

129targeted tests pass, including mechanical integration, exact mass/link-set validation, stale/future/missing heartbeat refusal, ground-clearance/motion limits, invalid mode combinations, partial six-link force failure, short writes and close failure retention. Final full regression:845passed,2existing warnings,214.73s. Independent review found1Important unchecked truth write and2Minor cleanup-loss/causal-wording issues, all fixed in one pass;2new fault cases RED→GREEN. Final failure-path hardening is synthetic/regression tested, not a physical rerun. Partial trace cannot be marked complete. No full25s supported capture, ground-separation success, raw-integral criterion, online OpenVINS accuracy, quality/reset/covariance or EKF2 result is claimed.

Changed-file lint and whole-repository baseline checks are recorded separately. Existing PR37 VIO terminal error lower bound29.5355m and five-camera0.873RTF<0.95 remain failures.

|Status|Scope|
|---|---|
|Verified|Synthetic mechanics/refusal/IO tests; actual runtime mass/world gravity/configuration readback in v2; both attempts issued zero forces and released resources.|
|Implemented|Time-only distributed support, full-rate clearance logging, sensor-only CLI and failure retention.|
|Untested|Full supported motion, post-lift ground separation, raw-IMU consistency criteria and native VIO under this condition.|
|Failed|v1 unavailable binding; v2 missing accepted heartbeat at fixed start; existing VIO/RTF failures unchanged.|

## Upstream choice and next dependency

Gazebo8.15 Apache2 source446a443 public Model.links, Link.AddWorldForce/WorldInertial/WorldAxisAlignedBox and Python bindings were inspected; source/maintenance metadata in results/supported-excitation-dev-1701/sources. API https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1Link.html . Each force acts at its link COM for one step. No new dependency. Fixed DART/backend from PR39 reused. OpenVINS ICRA2020 https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf provides inertial-estimation context, not certification of this fixture. Alternatives and costs are in the spec; no truth-feedback support or altered IMU values adopted.

Next must design startup readiness independently: bounded wait in advancing simulation, using actual unarmed heartbeat and source readiness to establish a recorded schedule anchor; retain the same force waveform and safety checks. No accepted unarmed heartbeat was available at the scheduled2s start; readiness timing is the next hypothesis to investigate, not a proven cause. Pausing simulation while awaiting a simulated-time heartbeat may stall lockstep, so do not add an arbitrary sleep. A new schedule condition must be named/frozen before execution, with late/missing/armed/stale heartbeat tests, timeout and full-duration evidence requirements. Only after sensor-only consistency passes should a separate online native VIO trial proceed. Both failures here remain sealed.
