# Five-camera render-capacity amendment 23

## Triggering evidence

Run `results/camera-render-capacity/dev-native-single-20260927-223153/`
serialized all five model insertions successfully. Compared with the previous
run, every vehicle recorded IMU and estimator datasets, so the insertion gate
removed the complete sensor-loss mode. Residual failures remained: vehicle 3
lacked barometer samples, vehicle 4 lacked barometer and GPS samples, and the
renderer witness received images from vehicles 0, 1, 2, and 4 but none from
vehicle 3. All discovered topics still reported a publisher and subscriber.

After the paused world resumes, all five `gz_bridge` initializers receive their
first clock sample together and register transport callbacks concurrently.
Boolean connection presence cannot distinguish a working callback from a stale
or duplicate transport registration.

## Binding correction

1. Retain the sequential paused-world model and sensor-publisher registration
   gates from amendment 22.
2. After resume and complete topic advertisement, perform one sequential,
   bounded stop/start rebind for every PX4 `gz_bridge`, independent of the
   initial boolean topology result.
3. Preserve each initial topology classification and stop/start client exit
   code. Client timeouts remain non-authoritative; downstream evidence decides.
4. Strengthen final sensor transport attestation to require exactly one
   publisher and exactly one subscriber on every IMU, magnetometer, GPS, and
   barometer topic.
5. Retain the strict MAVLink/EKF2 gate and camera image-readiness gate. They
   remain the authoritative proof that callbacks deliver usable data.
6. Preserve Gazebo stdout/stderr and every PX4 instance's stdout/stderr in each
   run output so sensor-system and bridge failures remain auditable after
   cleanup.
7. Keep all simulation, sensor, camera, vehicle, timing, and scoring parameters
   unchanged.

This correction serializes both model registration and bridge callback binding
while tightening evidence against stale or duplicate connections.
