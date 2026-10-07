# Heartbeat/IMU commit-order diagnosis and correction

## Observed failure

The immutable `study-v19/capture-v1` attempt stopped at 2.620 s simulation time with `future heartbeat simulation clock`. The independently journaled second heartbeat carried observed simulation time 2.614 s while `JournaledReadiness` still held IMU time 2.604 s. Raw IMUs at 2.608 s and 2.612 s had already arrived before the heartbeat, but the single source writer had not yet committed them to readiness. The older heartbeat at 1.616 s was still only 0.988 s behind the committed IMU and therefore remained valid under the unchanged 2 s simulation-age limit.

This is an ordering defect between the independent heartbeat observation lane and queued high-rate source commits. It occurred before the 2.619 s force anchor, so no support or lateral force was applied. OpenVINS had internal initialization but no public initialization, quality, reset or fusion eligibility. The failure is not caused by training, weights, loss, fruit-fly policy behavior or flight control.

## Correct behavior

Accepted monotonic heartbeats are retained in a small bounded history. Readiness selects the newest heartbeat whose observed simulation time does not exceed the latest committed IMU time. A newer heartbeat that is temporarily ahead remains pending evidence; it does not invalidate an older still-fresh heartbeat and is not used until committed IMU time catches up.

If no heartbeat is causally eligible, readiness returns unavailable. It does not grant readiness from a future heartbeat. The existing anchored policy then remains at zero force before anchor or fails closed if readiness is lost after anchor. The 2 s heartbeat simulation-age limit, high-rate wall limits, startup deadlines, source/native watchdogs and identity/monotonic checks remain unchanged. No frame or heartbeat is fabricated or repeated.

## Evidence and scope

An independent fixed-evidence audit reproduces the exact 10 ms lead, confirms the two already-arrived but not-yet-committed IMUs, proves the older heartbeat remained within 0.988 s, and retains all failure, ULog, runtime and no-force evidence. RED/GREEN tests cover temporary lead with a valid prior heartbeat, no eligible heartbeat, catch-up, stale history, regression, bounded history and post-anchor fail-closed behavior.

No physical rerun belongs to this correction stage. A later attempt requires a new prepare-only package, startup preflight and separately committed one-shot boundary.
