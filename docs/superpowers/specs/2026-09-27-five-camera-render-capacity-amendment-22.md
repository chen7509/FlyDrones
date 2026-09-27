# Five-camera render-capacity amendment 22

## Triggering evidence

Run `results/camera-render-capacity/dev-native-single-20260927-222659/`
proved that all 20 required sensor topics had a publisher and a PX4 transport
subscriber, yet ULog evidence remained asymmetric:

- vehicle 0 received none of IMU, magnetometer, barometer, or GPS data;
- vehicle 1 received IMU, barometer, and GPS but no magnetometer;
- vehicle 4 received IMU and GPS but no magnetometer or barometer;
- vehicles 2 and 3 received all required streams and reached ready-for-takeoff.

All five rebind logs state that initial topology was complete, so no bridge was
changed. Topic discovery therefore cannot establish that Gazebo's sensor
systems are producing data for every concurrently inserted model.

PX4's local `px4-rc.gzsim` shows that each process sends an EntityFactory create
request, sleeps one second, then starts `gz_bridge`. The capacity launcher was
starting processes 250 ms apart while the world was paused, allowing multiple
model insertions and sensor registrations to overlap.

## Binding correction

1. Keep Gazebo paused.
2. Start PX4 instances in numeric order. After each process is registered, wait
   until that model's IMU, magnetometer, GPS, and barometer topics are all
   advertised before starting the next process.
3. Bound each per-model advertisement gate and fail closed with that instance's
   logs if it expires or the process dies.
4. After all five sequential gates pass, retain the existing all-process bridge
   barrier, world resume, initial subscriber inspection, targeted bounded
   rebind fallback, final 20-topic attestation, strict EKF2 health gate, camera
   evidence, and ULog preservation.
5. Keep all models, poses, parameters, sensor rates, camera timing, score windows,
   and thresholds frozen.

This correction removes concurrent EntityFactory insertion from the experiment
without weakening any downstream gate.
