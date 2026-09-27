# Five-camera render-capacity amendment 10

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-212448/` passed the
native five-stream renderer witness, renderer attestation, native selected
observer readiness, and exact one-subscriber topology. The PX4 gate then
reported all five vehicles connected, landed, and disarmed, but vehicles 1, 2,
and 4 still had `estimator_healthy=false`.

The health sampling loop exited as soon as estimator, armed, and landed fields
were non-null. A reported false estimator value therefore ended the wait
immediately instead of allowing EKF convergence during the existing ten-second
deadline.

## Binding correction

1. Early health readiness requires exactly `estimator_healthy is True`,
   `armed is False`, and `landed is True`.
2. Any false or unknown field continues polling until the unchanged ten-second
   per-vehicle deadline. The final observed state is still preserved and the
   gate remains fail-closed if convergence never occurs.
3. Keep the concurrent five-vehicle sampling, MAVLink endpoints, timeout, and
   final gate unchanged.
4. Restart all Task 6 development checks with new identifiers and retain the
   failed run.

No PX4 parameters, EKF settings, sensor inputs, or performance thresholds
change.
