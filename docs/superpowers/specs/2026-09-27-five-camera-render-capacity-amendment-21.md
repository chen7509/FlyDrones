# Five-camera render-capacity amendment 21

## Triggering evidence

Run `results/camera-render-capacity/dev-native-single-20260927-222056/`
reached the post-resume rebind stage but timed out after 180 wall seconds. Only
vehicle 0's rebind log existed and it was empty. Vehicle 0's ULog was much
shorter than the other four, proving that the external `px4-gz_bridge stop`
request stopped the module but its client did not return. The unconditional
rebind loop therefore never issued vehicle 0's start request or reached the
remaining vehicles.

## Binding correction

1. Retain amendment 20's advertised-topic gate and final 20-topic attestation.
2. Before changing a bridge, inspect the four required sensor topics for that
   vehicle. Skip rebind when all four already have a publisher and subscriber.
3. Rebind only vehicles with incomplete initial topology.
4. Bound external stop requests to two wall seconds and start requests to ten
   wall seconds. A client timeout is diagnostic rather than authoritative
   because the server-side command can already have taken effect.
5. Treat the final 20-topic publisher/subscriber attestation, PX4 process
   liveness, and strict MAVLink/EKF2 health gate as authoritative. Fail closed
   if any of those checks fail.
6. Preserve a per-vehicle log stating whether rebind was skipped or attempted,
   including stop/start client exit codes.
7. Keep all simulation, sensor, vehicle, timing, and scoring parameters frozen.

This amendment prevents a control-client wait from consuming the readiness
budget while retaining evidence-based failure handling.
