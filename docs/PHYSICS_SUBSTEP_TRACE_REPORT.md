# Physics substep trace — development1701

## Result and scope

One new **substep-lateral-v1 sensor-only diagnostic** completed25s, with the existing1ms physics,250Hz raw IMU,10Hz160×120RGBD and unchanged lateral-wrench-v1 force. No estimator, training, ODOMETRY or arming ran. Omitting the native worker changes CPU load; this is **not a capacity or VIO benchmark**.

The captured dynamics close at full rate under the discrete right-endpoint rule, but all four250Hz sampling phases give substantial integral errors during excitation. This supports temporal undersampling/aliasing of these contact-driven dynamics as the cause of this particular acceleration-versus-velocity discrepancy. It does not prove the source of all PR37 VIO drift, qualify calibration, or establish reliable VIO.

|Window(s)|1kHz right error(m/s)|1kHz trapezoid error|250Hz right errors, phases0/1/2/3ms|Raw250Hz trapezoid error|
|---|---:|---:|---|---:|
|5–5.1|8.118e-12|0.003536|0.375553/0.360461/0.360479/1.085829|0.361426|
|5–6.6|4.175e-9|0.004426|2.350175/2.705194/2.722387/2.965181|2.333941|
|8–9|0.00002751|0.00002751|approximately0.0000274 each|0.0002047|

Quarter-phase windows use their own actual first/last velocity endpoints; phases1–3 have slightly shorter intervals. Raw IMU matches phase0, with same-time acceleration residualP95=0.01847m/s² over5–6.6s. Comparing this residual alone would miss the integration problem. Neither full-rate acceleration nor a truth-derived derivative was fed to an estimator.

## Evidence

- Producer5b907bb. `results/physics-substep-trace-dev-1701`: prospective-profile-v2.json, before/after manifests, capture-v1, audit.json and scripts. Initial launcher failed before simulation because WSL Git could not resolve the Windows worktree pointer; empty prospective-profile.json and original package output retained. Corrected launcher receives the Windows-resolved commit. Only one physical attempt occurred.
-50000pre/post rows, no unavailable fields. Every pre state equals the preceding post state exactly for position,velocity,acceleration,angular velocity and quaternion. Official end-of-step timestamp interpretation thus agrees with actual readback.
-6251IMU,251RGB/info/depth each,24unarmed heartbeats.1600nonzero force steps, zero net impulse and41.6N·s absolute impulse. Original fixture bounds and source watchdog retained.
-ULog49vehicle_status records, all arming_state1; SHA256 `0270a57577e347c1406f2e621efa8ac69a5778532cb072669f3c917aad4b7f33`.
-Runtime `/proc/self/maps` identifies gz-physics7.8.0 dartsim plugin and DART6.13 libraries with exact hashes. Package versions and loaded binaries recorded; all frozen producer/model/binary hashes unchanged after capture. Relevant processes released.
-Changed files Ruff/94targeted tests passed before capture; full regression and independent review are recorded in the final evidence seal. Whole-repository Ruff's prior50errors in32unchanged files remain unresolved; no whole-repository lint success claim.

## Research and next dependency

Reuse installed Gazebo8.15 TestFixture/Link readback, Apache2, fixed source446a443; gz-physics7.8.0 Apache2 source189471c and DART6.13.2 BSD2 sourcea51e08c. Existing PR37/38 source provenance and maintenance metadata retained. Official callback semantics: https://gazebosim.org/api/sim/8/createsystemplugins.html ; lifecycle: https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1TestFixture.html . This adds bounded1kHz IO, requires no new runtime, and avoids an unnecessary estimator replay. OpenVINS ICRA2020 context: https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf . Installed package patches are not asserted equivalent to pure upstream source.

Next research/design must address a physically consistent excitation and IMU observation model. Examine contact impulses, upstream sensor sampling/anti-aliasing or delta integration, and a bounded non-contact external fixture. Do not silently replace IMU with truth, select a favorable phase, change physics/sensor rates, or claim the present diagnostic fixes VIO. Any new development condition requires a named frozen design and failure tests before one new validation; reliable online VIO, resets/quality/covariance, and VIO→EKF2 remain unverified.

## Status

**Verified:** bounded trace and synthetic fault tests, this physical trace, full-rate closure versus quarter-rate discrepancy, unarmed evidence and release.

**Implemented:** explicit sensor-only diagnostic and offline phase analysis.

**Not tested:** corrected observation/excitation design, new online VIO accuracy, EKF2 injection, complete fly decision performance under this setup.

**Still failed:** PR37 VIO terminal error lower bound29.5355m; five-camera WSL capacity0.873RTF below0.95. No20/100-drone, HITL or real-flight approval.
