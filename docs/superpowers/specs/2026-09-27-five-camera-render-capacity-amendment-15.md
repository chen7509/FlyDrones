# Five-camera render-capacity amendment 15

## Triggering evidence

Restarted development run
`results/camera-render-capacity/dev-native-single-20260927-214839/` stopped at
the new sequential readiness gate for vehicle 0. Its retained console had
already reported `home set`; the remaining preflight warning was `No connection
to the GCS`. PX4 does not emit `Ready for takeoff!` until it receives a GCS
heartbeat, while the launcher did not open any MAVLink/GCS connection until
after all five instances had started. The console marker therefore introduced
a circular startup dependency and could never prove the first instance ready.

## Binding correction

1. Retain sequential five-instance startup and its single 120 wall second
   budget, but replace the console `Ready for takeoff!` gate with a temporary
   vehicle-local MAVLink connection immediately after each instance starts.
2. The temporary connection sends the existing GCS heartbeat and requests the
   existing telemetry streams, then uses the same strict capacity predicate:
   estimator healthy, landed, and disarmed. Close it before starting the next
   instance.
3. Bound each per-instance telemetry wait by 30 wall seconds and the remaining
   shared startup budget. Fail closed and retain the PX4 logs on failure.
4. Keep the final concurrent five-vehicle MAVLink gate after renderer
   attestation as independent evidence.
5. Keep every PX4 parameter, sensor model, pose, trigger schedule, scoring
   window, and threshold unchanged. Preserve this failed run, update frozen
   hashes, and restart all three Task 6 checks with new identifiers.

The temporary connection supplies the prerequisite heartbeat rather than
inferring health from console text.
