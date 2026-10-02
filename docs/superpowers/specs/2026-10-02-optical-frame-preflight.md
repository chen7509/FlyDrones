# Optical-frame and IMU-extrinsic preflight

The development CameraInfo run measured K but did not establish the runtime
camera-link pose or the rotation from Gazebo's +X-looking camera frame to the
+Z-looking optical convention expected by visual estimators. Before any VIO
configuration, inspect the expanded vehicle in an **isolated, one-step
Gazebo-only** development fixture. Read the world poses of `base_link` and
`camera_link`, the camera sensor's relative pose and frame ID, and the PX4
base model's IMU frame. Hash all SDF inputs and save raw probe output. This
must not launch another PX4 mission or affect the frozen 20 worlds.

Use authoritative Gazebo/SDFormat frame conventions and explicitly write the
candidate link-to-optical rotation. Validate it with a known-direction image
projection test before marking the extrinsic accepted. A successful SDF pose
probe alone remains **nominal geometry evidence**. Do not feed unverified
extrinsics into OpenVINS or PX4 EKF2, and do not call shared simulation
timestamps a measured camera-to-IMU delay.

For the projection check, use an independent static fixture with colored
calibration targets at known positions, capture a raw image and camera info,
and compare observed target centroids with predictions under the candidate
transform. Preserve all mismatches and the exact model/world files. If the
probe cannot run on this host, report the failure without substituting
Gazebo truth odometry for VIO output.
