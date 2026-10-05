# Fixed-input diagnostic reference freshness

**The PR41 Link diagnostic reference is internally inconsistent and remains unqualified.** This stage adds a reusable offline checker and explicit callback-only timestamp provenance for future traces. It does not repair the old measurements, run physics, run OpenVINS, train weights or publish ODOMETRY.

## New evidence from the sealed input

One offline audit consumes four hashed members from PR41 ZIP SHA256 `acd5da7efa70312dbf5b75f6e1a2cbfe25ff286e1ee70e86dc9a3dba101458ba`: complete pre/post trace, force commands, readiness anchor and capture result. All 50,000 records are validated for paired phases, exact 1 ms steps, callback timestamp convention, nondecreasing wall time, available finite state and quaternion norm. Each consumed member's size/hash is retained; input bytes are unchanged. This is a new fixed-input analysis, not an estimator replay or repeated physical trial.

Two exactly unchanged position/quaternion runs report nonzero dynamics:

| Interval | Duration | Reported dynamics | Discrete closure contradiction |
|---|---:|---|---|
| 3.931–4.942 s | 1.011 s | speed 0.000195847 m/s, acceleration norm 0.0353546 m/s² | acceleration predicts approximately −0.0357435 m/s vertical velocity change absent from the records |
| 6.541–15.034 s | 8.493 s | lateral velocity −0.0122335 m/s, acceleration +12.2335 m/s² | acceleration predicts +103.8993 m/s velocity change; velocity predicts −0.1038993 m displacement, both absent |

The second run ends at 15.034 s, not at capture end. All force transition neighborhoods are saved, including events before and after the nominal lateral stop at 6.543 s. Maximum single-step acceleration→velocity residual is 2.227859 m/s and velocity→position residual is 0.00222687 m. These are diagnostics of the sampled reference, not measured flight-control error. Numerical differencing/integration occurs only offline and is never fed to an estimator.

The checker requires an unchanged-pose run of at least 100 ms and reported speed >0.001 m/s or acceleration >0.01 m/s² to retain a contradiction candidate. These are diagnostic selectors, not relaxed physical/VIO acceptance thresholds. True static zero-dynamic and consistent accelerating synthetic traces are not labelled stale. Absence of a detected contradiction returns **indeterminate**, never freshness success. Aliasing and component caching require separate causal evidence.

## Source and interface findings

Pinned gz-sim `446a44335a45b704b4d36dabcc5508ee34eeb3d8` `Link::WorldLinearVelocity` and `WorldLinearAcceleration` return ECM component data. `Physics::ChangedLinks` selects changed-pose links; the link update loop writes kinematics for those selected links. Pinned gz-physics `189471c86fa06ffad9c9bdb199f6928eb2fc02f3` DART implementation selects pose changes using a 1e−6 position/quaternion threshold. Non-link children with a physics-link parent follow a separate `LinkFrameDataAtOffset` path every update. This gives a source-grounded explanation candidate for retaining the final nonzero velocity/acceleration when the position stops changing; **the installed backend runtime cause has not been instrumented or proven**.

Existing `state_time_ns` merely expresses the callback phase convention. Future SubstepTrace records now explicitly include `state_time_basis=callback_phase_only` and `component_refresh_verified=false`. Existing logs and the original misleading PR41 arithmetic boolean stay untouched; PR41's supplemental diagnostic and this report continue to reject overall qualification.

Installed Python gz.sim8 ECM has no public creation/component methods and no `gz.sim8.components` module. The fixed upstream Python ECM wrapper exposes only its constructor. Direct Python child-entity creation is therefore rejected for this installation. Installed pkg-config reports gz-sim8 8.15.0 with g++/cmake available; a native API capability probe is recorded separately and is not simulator or plugin validation.

The first native compile failed because guessed `WorldPose.hh` / world-velocity header names do not exist; output and source remain retained. Inspection of the installed headers showed world/local aliases share `Pose.hh`, `LinearVelocity.hh`, `LinearAcceleration.hh` and `AngularVelocity.hh`. Corrected v2 compiled and ran successfully in a standalone empty ECM, creating a parent/child and reading/writing separate diagnostic components, including a NaN sentinel. Binary SHA256 `1de07768bd9907c655fc6c3cee7ca3af61f22977be6b1a09ec1b7ab3775f7bcb`. This proves only native API availability, not physics-driven sentinel replacement. A shell-quoting preparation attempt failed before compilation; the preserved standalone preparation script produced v2. No physical simulation was started by either probe.

## Research choices and next step

Gazebo/gz-physics are Apache-2.0. Saved repository metadata shows non-archived projects with pushes 2026-10-05T03:38:09Z and 2026-10-01T19:53:02Z respectively; activity does not guarantee support. Pinned source, hashes and [Gazebo 8 system-plugin documentation](https://gazebosim.org/api/sim/8/createsystemplugins.html) are preserved. The [OpenVINS ICRA2020 paper](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf) supplies estimator/evaluation context, not evidence that simulator fields are fresh. No additional dependencies were installed.

The selected next candidate is a small native diagnostic System plugin creating a zero-offset, non-sensor child of the existing base link. It would keep the original Link fields for comparison and use the documented per-step child backend path. Prospective design must include a pre-step sentinel in diagnostic output components and finite post-step replacement, so callback arrival alone cannot certify refresh. Do not poison the child's local Pose, parent, any physical link, sensor input or force; only separate derived diagnostic components may hold sentinels. Compile-only capability is insufficient to claim this works in the simulation.

Before a new physical trial, independently freeze plugin/version/config and define sequential callback accounting, canary/refusal behavior, durable-enough checked logs, ownership/cleanup, bounds and terminal completeness tests. Existing 25 s/1 ms/250 Hz/10 Hz RGBD load, supported-ready-v1 force/time/arming gates and original safety limits remain. New logging adds load and is not a capacity optimization. Fresh diagnostics must also support the isolated abort monitor; stale Link values alone cannot serve as a newly certified safety reference. No fresh field or finite-difference truth may enter VIO. A middleware upgrade or physics-engine patch was rejected as larger and unnecessary before this narrower diagnostic test.

| Status | Scope |
|---|---|
| Verified | Offline input ordering/numerics, two contradictory runs, fixed-source update paths and absence of required Python methods. |
| Implemented | Reusable offline checker and explicit future timestamp provenance. |
| Not yet verified | Native plugin runtime refresh, fresh safety/reference geometry, raw integral qualification, online VIO accuracy, quality/reset/covariance and EKF2 fusion. |
| Failed / retained | PR41 reference consistency, PR37 VIO error lower bound 29.5355 m, five-camera 0.873 RTF <0.95, prior sealed startup/contact-condition failures. |

Initial validation: 44 targeted tests and 876 full regression tests (2 existing warnings,216.19s). Independent review found one Important aggregate-overflow refusal gap and no Critical/Minor issues. Two new cases failed before correction and passed afterward; the expanded targeted set has91 passes. Finite per-step values can overflow a sum or norm, so all reported numeric reductions now reject nonfinite results. The original fixed-input audit remains producer217fec5; no repeat of that audit is claimed after hardening. Final regression: **878 passed, 2 existing warnings,209.65s**. Changed-file Ruff passes; whole-repository Ruff remains50errors in32files unchanged from base. Correctionedac498 is supported by synthetic tests/regression, not a new estimator or physical run. Final resource inspection found no related active processes.
