# Fixed input reveals inertial/physical velocity inconsistency

The PR37 dynamic failure has a measurable input-side discrepancy before the first ordinary visual update. Over5.0–5.1s, raw-IMU acceleration integrated in the physical world frame differs from physical endpoint velocity change by **0.361485m/s**. The independently recorded physical acceleration field produces **0.361413m/s** disagreement. Raw-to-native recorded delivery matches for all6251IMU packets. This narrows the next investigation to sampled sensor/physics consistency; it does **not** prove the final cause of29m drift or certify the estimator.

No simulator or estimator was launched. No weights, noise parameters, public readiness gates or sensor values were changed. Truth is used only in offline arithmetic, not estimator initialization/correction. All fusion eligibility staysfalse.

## Method and evidence

Inputs are read directly from immutable PR37 archive SHA87a1eb39053ba72b84136908ae800799db7dc54b7fe81a64b20f5f4bd8e617b6. The archive hash and hashes/sizes of all six consumed members were verified. tools/benchmark/audit_inertial_consistency.py checks raw FLU→FRD vectors, reconstructed packets against retained SHA/length, request order, acknowledgements and sample/arrival identity.6251IMU packets match within6501total requests. Image payloads are outside this IMU-specific audit, and no fresh native parser execution is claimed.

The inertial audit uses exact4ms paired samples, physical rotation to map raw specific force to world, actual SDF gravity[0,0,-9.81], and trapezoidal integration. It compares the resulting delta-velocity against physical endpoint velocity change. No interpolation, trajectory/gauge fitting, tuned noise or post-hoc threshold. Frames and gravity signs have synthetic stationary/constant/rotated checks; malformed timestamps/vectors/quaternions and packet corruption are rejected. Fixed windows were written in the spec before the audit.

|Window(s)|Raw sensor integral closure norm(m/s)|Physical acceleration integral closure norm(m/s)|Scope|
|---|---:|---:|---|
|4.9–5.0|0.004533|0.004517|Includes the first force sample at5.0; not a pure stationary baseline|
|5.0–5.1|0.361485|0.361413|Before first ordinary visual update|
|5.1–5.2|0.359763|0.359835|Before first ordinary visual update|
|5.2–5.3|0.051775|0.051864|Before first ordinary visual update|
|5.0–6.6|2.334790|2.333716|Entire excitation interval|
|8.0–9.0|0.000210|0.000028|Settled interval|

For5.0–5.1s specifically, physical delta-velocity is[-0.000144,0.616421,-0.001013]m/s, while the IMU integral is[-0.014208,0.868778,-0.259450]m/s. The raw-sensor and physics-acceleration integrals differ by only approximately[0.000009,0.000071,-0.000032]m/s. Thus PR37's small same-stamp IMU-versus-acceleration residuals did not establish time-integrated consistency with physical velocity. Those earlier results remain true but insufficient.

The norm of the stored native velocity change is0.907263m/s in that first interval and last_regular_update remains-1. This is norm(v_end-v_start), not change in speed. Its components are stored separately without claiming they are aligned world-frame components. No native replay, cache ablation or visual update instrumentation was run, and this audit does not assign the entire terminal error to one factor.

## Source investigation and unresolved distinction

Fixed OpenVINS6948812/GPL3 uses local selected copies of its IMU history in both normal and fast propagation. Fast propagation maintains its own cache. Source inspection does not replace a runtime cache side-effect test; the prior filter_unchanged check covered main state/covariance only. Official [inertial derivation](https://docs.openvins.com/propagation.html) and the [ICRA2020 reference](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf) support checking the motion equations without treating a planar pulse as full calibration.

Installed gz-physics7.8.0 maps upstream tag to189471c86fa06ffad9c9bdb199f6928eb2fc02f3,Apache2. Its dartsim KinematicsFeatures.cc reads Frame::getLinearAcceleration into FrameData. DART6.13.2 upstream tag mapsa51e08c210d7892605c6dc0b9ae96fce4446d9fe,BSD2; installed package has+ds1-1~osrf2~noble suffix and has not been rebuilt or proven identical to pristine upstream. World::step integrates unconstrained velocity, solves constraints, computes impulse-related changes and integrates position; Skeleton::computeImpulseForwardDynamics calls updateConstrainedTerms. Do not infer from partial source that contact impulses are necessarily absent from reported acceleration. GitHub metadata, licenses and selected source hashes are retained; these are existing dependencies, no installs.

Further pinned DART GenericJoint.hpp:2434–2436 explicitly adds constraint velocity change to velocity and its timestep-scaled value to acceleration. This rejects a simplistic source claim that constraint impulses are entirely omitted. Installed patch equivalence and runtime sample behavior remain unverified. Both repository metadata snapshots show nonarchived: gz-physics pushed2026-10-01, DART pushed2026-10-05; this is maintenance evidence, not permission to upgrade.

Only every fourth physical step is available in PR37 truth logs. Missing1ms information prevents distinguishing sample-phase/aliasing, discretization/contact behavior, callback timing or engine semantics. A new prospectively designed1ms diagnostic trace may be necessary. It should preserve the25s/1ms physics/250HzIMU/10HzRGBD and force condition, log pre/post-step acceleration/velocity/clock, and retain all failures. Extra logging is not a capacity benchmark. Any choice to omit the native worker must be documented as a diagnostic workload change, never a performance improvement or new VIO pass. Do not repair the IMU by replacing it with a truth-derived derivative.

|Status|Scope|
|---|---|
|Verified locally|Recorded IMU packet identity; exact-sample offline integration; large excitation-only velocity-closure discrepancy, also present in sampled physical acceleration.|
|Implemented/tested synthetically|Reusable offline audit and malformed-input rejection; no online controller or estimator behavior changed.|
|Untested|1ms dynamics/sample phase and installed-engine semantics; runtime fast-cache isolation; camera/visual update validity; a corrective sensor solution.|
|Failed/still blocked|Reliable dynamicVIO and fusion. Earlier29.5355m terminal error lower bound remains. Full-fly learning/latency/collision and5camera0.873RTF<0.95 are separate unresolved gates.|

25 targeted synthetic tests went missing-module RED→GREEN. Independent review found one Important (noninteger/infinite acknowledgement fields could be accepted) and one Minor (norm-of-change wording). Both were corrected in one pass, with four new malformed-ack cases RED→GREEN. Final focused54tests passed with native transport regression; **787 full regression tests passed**, two existing warnings,218.61s. Changed-file Ruff and diff checks passed. Full-repository Ruff still reports50diagnostics in32 files unchanged from92e50d4, with unchanged config; separate baseline check is retained. No deferred review findings or second review.

Final strict delivery check still matches all6251IMU packets and retained original audit.json byte content. Its producerfcf6b8f auditor is separately saved and SHA-verified, while the final auditor is separately hashed. Only packet validation was repeated after hardening; numerical integration, physics and estimator were not rerun. No new physical or estimator evidence is implied by software tests. Final related process check is empty, and Windows test processes exited.

Evidence: evidence/openvins-inertial-consistency-dev-1701.zip,49members/129,616bytes, SHA256 **ac2427cb9af7114a4ea8ddcf36429d628aed732a0736a26f52df298fc4bddad6**. Every member digest and size verified. Source/report snapshot at1a05276 precedes this metadata paragraph. Input archive remains the separately retained PR37 artifact, referenced by hash and consumed-member manifest; it is not redundantly copied into this small diagnostic archive. Next bounded work is documented in sealed next-physics-trace-research.md.

Publication closure: draft PR38 https://github.com/chen7509/FlyDrones/pull/38, stacked onPR37 and attached to current task. Initial auditfcf6b8f, reviewed corrections1a05276, sealed evidencec0d6e7d. This closure postdates the immutable archive. Existing continuation stays active; input-side diagnosis is complete for available data, but a corrective solution and the larger project remain incomplete.
