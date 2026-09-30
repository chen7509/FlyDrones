# Five-camera render-capacity amendment 11

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-212709/` failed
the temporary native five-camera renderer witness after its 30-second readiness
deadline. The retained `renderer-phase.jsonl` contains 148 received triggers for
each vehicle, no image at all for vehicle 0, and 138, 119, 102, and 86 images
for vehicles 1 through 4 respectively.

The witness subscribed to all five trigger topics even though its setup-only
job was to prove five rendered image streams. Those subscriptions satisfied
the scheduler publishers' boolean `HasConnections()` gate before every
triggered camera sensor had necessarily connected. The scheduler could
therefore start publishing while a camera trigger endpoint was absent, and the
witness itself made the false readiness condition persistent and
indistinguishable from a real sensor connection.

## Binding correction

1. Add an explicit native observer option, `--observe-triggers 0|1`, defaulting
   to `1` so the scored native observer contract remains unchanged.
2. The temporary renderer witness must pass `--observe-triggers 0`. It listens
   only to `/clock` and the five depth image topics, so scheduler publisher
   connectivity during setup can only be supplied by the triggered camera
   sensors.
3. Do not change scheduler timing, warmup count, readiness deadlines, scoring
   windows, camera models, PX4 settings, or performance thresholds.
4. Preserve this failed run, rebuild and re-hash the native executable and
   trial runner, and restart all three Task 6 development checks with new
   identifiers.

This correction separates renderer attestation from trigger observation. The
selected observer still records triggers during the scored phase.
