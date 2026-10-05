# Journaled readiness and supported motion — development 1701

The new bounded startup contract completed one 25-second, disarmed sensor-only capture. It waited for recorded source readiness before choosing an immutable future force schedule. **Overall sensor consistency and VIO remain unqualified:** the capture exposed stale-looking link diagnostic velocity/acceleration fields. No estimator, learning, ODOMETRY publication or EKF2 injection ran.

## Implemented contract and physical evidence

`supported-ready-v1 / substep-ready-v1` preserves the body, gravity, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGBD, 0.4 m / 2 s quintic lift, original ±26 N lateral waveform and safety bounds. No force is applied while waiting. Successful event write and flush (not fsync durability) acknowledges IMU, RGB, CameraInfo and a selected unarmed heartbeat. Each arrival must be at most 2 seconds old. Readiness before the 8-second simulation deadline chooses current simulation time + 200 ms exactly once; the full proof is saved before activation. Future/reversed clocks, journal failure, armed heartbeat or lost readiness refuse further force. Existing first-source and operational watchdogs remain.

The single capture used producer `dbdb662`. Readiness selected at simulation 1.743 s fixed anchor 1.943 s, lift 1.943–3.943 s and lateral excitation 4.943–6.543 s. There were 23,058 support steps and 1,600 lateral steps, zero net lateral impulse and 41.6 N·s absolute impulse. All six per-link force calls were recorded. Recorded post-lift ground clearance minimum was 0.399999 m; recorded maximum displacement 0.510947 m and speed 2.446705 m/s. These are diagnostic component observations, not an independently validated fresh backend state at every step.

Counts: 6,251 IMU, 251 each RGB/CameraInfo/depth, 50,000 pre/post trace records, 24 unarmed heartbeats and 51 ULog vehicle-status records, all arming_state 1. Pre-step component values exactly match the previous post-step values. This verifies log continuity, not component freshness. ULog SHA256: `1c882d0f99e8341bb3b1d2f789d4012a467994c866f9a0ea3e614edfd62f7ce4`. Run-before/after hashes match and owned resources were released. Native OpenVINS was omitted by explicit sensor-only design; elapsed time is not a capacity or VIO performance result.

## Numerical result and new validation gap

Raw IMU integration against the recorded endpoint velocities gives 0.000133 m/s error over the first lateral 100 ms and 0.000819 m/s over the whole lateral window, below the predeclared 0.02 / 0.05 thresholds. Actual raw sample endpoints were used without interpolation or selecting another phase. All four 250 Hz diagnostic phases are retained.

However, full-rate diagnostic integration is inconsistent after motion: over the settled one-second interval, link acceleration implies 12.233523 m/s velocity change while recorded velocity change is zero. At 8 and 9 seconds, position, quaternion, velocity and acceleration are bytewise equal, yet the reported lateral velocity is −0.0122335 m/s and acceleration +12.2335 m/s². Raw horizontal IMU acceleration is near zero. Therefore the endpoint reference itself needs freshness validation. `audit.json` is preserved unchanged; its `new_development_consistency_pass` boolean means only the two arithmetic thresholds passed. `diagnostic-gap.json` explicitly sets overall qualification false and preserves counterexamples.

Pinned source provides a concrete next hypothesis: gz-physics `SimulationFeatures::Write(ChangedWorldPoses)` compares pose with a 1e−6 tolerance; gz-sim `ChangedLinks` and the link component update loop consume changed poses. Child sensor acceleration has a separate per-step backend read path. This can explain stale link kinematics when motion ceases, but source inspection is not runtime proof of the installed path. The trace's `state_time_ns` was assigned from the callback; it is not a backend update timestamp. Do not use it as freshness evidence.

## Validation and scope

Initial missing-module RED and 142 targeted tests are retained. Initial regression: 858 passed, 2 existing warnings, 215.96 s. Independent review found one Important overbroad audit field and one Minor clock high-water gap; both were addressed in one correction pass. The original audit is retained with its explicit superseding diagnostic. Three new clock-fault cases failed before the shared high-water latch and passed afterward. Final targeted suite: **145 passed**; final full regression: **861 passed, 2 existing warnings, 219.74 s**. Changed-file Ruff passed. Whole-repository Ruff still fails with 50 errors in 32 files unchanged from base; no whole-repository lint success is claimed.

The physical capture remains producer `dbdb662`; final clock hardening `d0741e9` is supported by synthetic tests and regression only. It was not physically rerun. All review findings are closed; the diagnostic freshness issue remains a deliberately disclosed next-stage blocker rather than a claimed fix.

| Status | Evidence boundary |
|---|---|
| Verified | Bounded journaled startup, immutable schedule, complete capture counts, disarmed heartbeat/ULog records and cleanup; numerical raw thresholds against recorded endpoints. |
| Implemented | Source receipt/acknowledgment proof, future anchor persistence, freshness/refusal policy and relative force schedule. |
| Unverified | Fresh backend kinematics, overall raw sensor consistency, online OpenVINS under supported motion, reliable quality/reset/covariance, VIO→EKF2. |
| Failed / retained | New link diagnostic integration contradiction; PR40 fixed-start attempts; PR37 VIO terminal error lower bound 29.5355 m; five-camera 0.873 RTF < 0.95. |

## Research and next dependency

Reused fixed PX4 `d6f12ad` HEARTBEAT (BSD-3-Clause), pymavlink 2.4.49 and existing recorder; maintenance metadata and exact sources are retained. [Official heartbeat service](https://mavlink.io/en/services/heartbeat.html) defines liveness/armed-state information, not VIO health or guaranteed first-message latency. No new runtime dependency; adaptation is the small synchronized readiness journal and relative schedule. Arbitrary sleeps, paused lockstep, ULog backfill and bypassed gates were rejected.

Recorded repository metadata: PX4 last push 2026-10-05T20:23:20Z and pymavlink 2026-10-02T09:32:21Z, both non-archived. This indicates activity, not a support guarantee. Pymavlink's [v2.4.49 COPYING](https://raw.githubusercontent.com/ArduPilot/pymavlink/v2.4.49/COPYING) describes (L)GPL v3 for the generator and a distinct MIT exception for generated output; do not label the entire dependency MIT. Existing message decoding is reused without generation or dependency replacement.

Next inspect the pinned gz-sim `446a443` / gz-physics `189471c` Apache-2.0 update paths and actual Python component access before designing a fresh diagnostic readback. Preserve all old evidence. Prefer a fixed-input/source diagnosis first, then a separately named and frozen probe if runtime proof is required. Do not silently alter IMU values or derive estimator input from truth. Existing diagnostic safety bounds must remain, and a fresh-state gap must be addressed before claiming sensor consistency or starting the separate online OpenVINS validation.

## Publication

Draft [PR41](https://github.com/chen7509/FlyDrones/pull/41), stacked on PR40. Archive `evidence/readiness-anchor-dev-1701.zip`: 745 members, 8,162,430 bytes, SHA256 `acd5da7efa70312dbf5b75f6e1a2cbfe25ff286e1ee70e86dc9a3dba101458ba`; all member hashes and CRC verified. Snapshot at `88a38ad` precedes this publication paragraph; evidence commit `ceabfea`. No physical rerun followed review corrections.
