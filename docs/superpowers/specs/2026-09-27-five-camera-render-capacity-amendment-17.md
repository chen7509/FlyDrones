# Five-camera render-capacity amendment 17

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-215742/` passed
strict sequential MAVLink startup health for vehicles 0 and 1. Vehicle 2 had
home and position initialization but still reported an unhealthy estimator at
the per-instance 30 wall second cutoff, with the retained PX4 log identifying
the remaining compass preflight condition. The outer setup and auxiliary
readiness budgets had not expired.

The new sequential gate had both a shared startup budget and a second fixed
30 second per-instance cap. That cap could discard otherwise available setup
time and fail before a slow sensor instance had used the experiment's defined
pre-score readiness allowance.

## Binding correction

1. Use one 150 wall second shared budget for all sequential PX4 health checks.
2. Give the current instance the remaining shared budget rather than applying
   a second 30 second cap. A slow instance may consume the budget, in which
   case later instances fail closed without starting.
3. Keep the outer capacity setup limit at 180 seconds, leaving 30 seconds for
   final topology, renderer attestation, observer handoff, and the independent
   concurrent five-vehicle MAVLink gate.
4. Keep the exact estimator-healthy, landed, and disarmed predicate and every
   PX4, sensor, camera, scoring, and performance parameter unchanged.
5. Preserve this failed run, update frozen hashes, and restart all three Task 6
   checks with new identifiers.

This reallocates existing pre-score time; it does not extend or alter the
scored window.
