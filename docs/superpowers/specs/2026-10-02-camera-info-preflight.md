# Gazebo camera-info preflight for the single-vehicle VIO dataset

The decision-window RGB/IMU availability check passed on existing raw data,
but actual camera intrinsics, optical frame convention, and camera-to-IMU
transform are not validated. In one new **development** episode, capture the
Gazebo RGBD sensor's `CameraInfo` protobuf from its published transport topic,
alongside existing RGB and PX4 ULog evidence. Keep this opt-in so the frozen
20-world results and prior development archive are untouched.

Save the first raw protobuf with a hash, a JSON summary of image dimensions,
intrinsic/projection matrices, distortion and header frame ID, total message
count, and the count of changes to those stable fields. Fail the camera-info
preflight if no message arrives, matrices or dimensions are invalid, or stable
fields change during the run. Never infer or store Gazebo pose truth as VIO.
Record the exact topic, model SDF hashes and PX4 revision. Compare the
published intrinsics against the SDF's nominal horizontal FOV as a check,
not a replacement for camera information. Inspect the IMU frame in the PX4
model and the camera optical frame orientation; do not supply a VIO extrinsic
until the full transform has been resolved and verified.

Use tests for valid/missing/mutated camera information and hash verification.
Run one world-1701 development episode only after checking that no competing
PX4/Gazebo run exists. Preserve failure, task status, ULog and all frame data.
The preflight does not prove OpenVINS, EKF2 fusion, 0.95 RTF or flight safety.
