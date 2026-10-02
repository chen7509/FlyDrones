# Dynamic camera/IMU preflight

## Scope

Use a separate Gazebo-only development fixture to test whether a controlled
yaw stimulus appears with the expected sign and timing in raw camera images
and raw Gazebo IMU messages. Reuse the checked static optical fixture, make
gravity zero to keep the vehicle in view, and command link angular velocity.
Archive the generated world, raw messages or lossless frame images, actual
link poses, hashes, and failed attempts. The source PX4 mission and sealed
benchmark worlds must stay untouched.

## Measurement

Track the green center sphere's horizontal image coordinate using a fixed
color threshold. Compare its displacement with the camera-link yaw sampled
at each image stamp and with integrated raw IMU z angular velocity. Report
coverage and residuals without shifting streams to obtain a pass. A 20 ms
nearest-IMU availability threshold may be checked, but does not prove the
physical sensor time offset or PX4 ULog alignment. If the stimulus, image
track, or IMU signal is inadequate, report an inconclusive result and retain
the run.

## Gate

This preflight can validate only simulated Gazebo camera/IMU timing and axis
sign under an artificial yaw stimulus. It cannot establish an OpenVINS
extrinsic, real sensor calibration, PX4 EKF2 visual fusion, flight safety, or
the five-camera WSL performance gate. A later PX4/Ulog trial is needed before
the pinned upstream VIO offline run can be interpreted as a flight-stack
result.
