# Five-camera render-capacity amendment 13

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-214003/` passed the
five-camera renderer witness with 11 images per stream at approximately 10 Hz,
and its revised scheduler emitted 1,078 consecutive triggers without a missed
slot. The launcher then failed the unchanged PX4 gate after its fixed 10 wall
second telemetry loop: vehicles 0 and 1 were healthy, vehicles 2 and 3 had not
yet emitted `ESTIMATOR_STATUS`, and vehicle 4 reported an unhealthy estimator.
Retained PX4 logs for vehicles 2 through 4 still showed preflight sensor/EKF
initialization at shutdown. The five PX4 instances start sequentially and the
measured simulator runs slower than real time, so a fixed 10 wall second wait
does not give every later instance the same adequate simulated convergence
window.

## Binding correction

1. Extract the capacity telemetry wait into a deterministic helper with a
   30 wall second default deadline.
2. Keep the acceptance predicate exact: estimator healthy is `True`, armed is
   `False`, and landed is `True` for every vehicle. Unknown and false values
   continue polling and fail closed at the deadline.
3. Keep all five vehicle checks concurrent. Do not change PX4 parameters,
   estimator flags, sensor models, trigger timing, readiness timeout, or any
   performance threshold.
4. Preserve this failed run, update launcher/runner frozen hashes, and restart
   all three Task 6 development checks with new identifiers.

The 30 second wait remains inside the existing 180 second setup deadline and
does not add time to the 30 simulation second scored window.
