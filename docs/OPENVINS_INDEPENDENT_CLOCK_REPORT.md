# Independent simulation-clock evidence

The new `JournaledSimulationClock` accepts the existing TestFixture PostUpdate shape and preserves simulation time, local callback observation, journal return and later reply selection separately. It does not obtain time from a TIMESYNC request, wall-time extrapolation, a pose or an estimator. This is an **offline implementation and validation stage**, not a live PX4/Gazebo clock measurement. No historical producer was changed or rerun, and the new lane is not yet registered in capture.

## Source and design evidence

Pinned PX4 d6f12ad GZBridge receives Gazebo's world clock, initially sets REALTIME and subsequently MONOTONIC; the lockstep drv_hrt path feeds/reads the scheduler clock. Refetched GZBridge and drv_hrt bytes match both the previous sealed sources and the currently installed checkout's inspected files. This does not establish a running binary's behavior or a clean entire checkout. The installed default `gz.sim8.UpdateInfo` value exposes timedelta sim_time/dt, int iterations and bool paused. Only this value type was constructed: no Server, TestFixture, Node or estimator. Its paused zero defaults are not a valid running observation.

Use the existing PostUpdate interface because it provides an independent clock without another subscription/discovery queue. The fixed zero-origin development profile is explicit: 25s, 1ms, iterations1..25000 with exact simulation increments. Late attachment, missing iterations, pause, time reset/jump and malformed types refuse; this is not a general-purpose Gazebo clock adapter. Existing bootstrap8s/500 and source2s limits are unchanged. A current simulation sample may be selected after UDP receipt to form reply-preparation time; it is not asserted to be the simulator's time at packet receipt or PX4's current HRT.

Research uses [pinned PX4 GZBridge](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/simulation/gz_bridge/GZBridge.cpp) and [Gazebo UpdateInfo API](https://gazebosim.org/api/sim/8/structgz_1_1sim_1_1UpdateInfo.html). PX4 BSD3 and Gazebo Apache2 licenses, pinned source hashes, current nonarchived repository metadata and exact last-push observations are retained. New metadata is not a new installed version claim. Initial HTTPS download failed with TLS EOF; a normal TLS retry succeeded. No TLS validation was disabled. No new numerical algorithm/paper result is claimed; existing OpenVINS references remain applicable.

## Failure semantics and cost

One writer records an attempted observation to the supplied journal, then publishes only after successful return, guard and freshness checks. Journal payload is copied; immutable committed objects are separate. Return time/acceptance appear in exported evidence, not retroactively in a previously written journal record. This does not imply fsync or durable transaction semantics.

A reader can obtain a previously committed fresh sample while the next one is being journaled. Pending data is never released. A later fault cannot retroactively revoke a snapshot; integration must recheck before a side effect. Guards and callbacks require outer bounded supervision. Capacity is 25000 samples plus bounded attempts/refusal information; memory/export-copy cost is proportional to that count, not a measured real-time performance result. No new dependency/background worker/transport is added.

## Review and tests

Initial RED was a missing-module collection error. Initial implementation passed40 tests. Self-review then produced two assertion failures: guard duration was excluded from callback age. Both were corrected, reaching42 tests.

Independent read-only review found two Important findings and no other confirmed Critical/Minor: a writer waiting for the reader's state lock could acquire a falsely late callback timestamp; the post-journal clock invocation bypassed clock reentry protection. A deterministic two-thread counterexample and injected reentry test failed before the fix and pass afterward. Entry is now sampled before waiting for the state lock, and every injected clock invocation has per-thread recursion protection. Production fix: dcc54fb. A first counterexample used a writer-entry signal; a second retained run uses a state-lock-attempt signal to remove scheduling ambiguity.

Final new suite: **44 passed**. Related Windows regression: **133 passed, 2 skipped** (real pymavlink modules unavailable in Windows). Corresponding WSL real pinned-codec wire/bootstrap regression: **67 tests, OK**. New tests use injected UpdateInfo/journal/clock and ordinary threads; WSL regression uses existing simulated connections/sinks, not actual PX4 or network traffic. Changed-file Ruff and diff-check pass. This stage did not rerun the entire repository; the previous3236-pass confirmation and its preserved first-run timeout remain historical evidence, not a fresh full-suite claim.

## Status and next dependency

- **Verified offline:** exact sample sequence/shape, timestamp ordering, source freshness, callback/guard/journal refusal, pending publication isolation, lock-wait age, clock reentry, reset/pause rejection, immutable evidence and actual RemoteMonotonicClock composition without request-derived time.
- **Implemented but not exercised live:** PostUpdate lane with externally supplied session guard. Session comparison and a callback-shaped object are not process authentication.
- **Still untested:** actual registration in owned capture, socket descriptor/session binding, timing relative to PX4's separate clock subscription, real receive-to-reply integration, actual filter convergence and EKF2 injection. runtime_source_proven/px4_clock_consumption_proven/network_authorized/fusion_qualified remain false.
- **Failures retained:** initial collection error, two self-review failures, two independent-review failures and the first research TLS error summary. All old simulation failures remain; five-camera0.873RTF still fails0.95.

Next: compose this lane with the already supplied-socket receiver and owned wire lifecycle in one explicitly frozen source/session contract. Check the actual selected callback and descriptor identity, and preserve timestamp/health checks through the final send boundary. Do not create another generic process/resource subsystem. No new physical/network experiment is authorized by these offline results. Full fruit-fly learning/division, fair baseline comparison and staged swarm verification remain downstream work, not completed by this interface.

Evidence is sealed separately as evidence/openvins-independent-clock-dev-1701.zip with external SHA/member manifest. Existing archives are not altered.
