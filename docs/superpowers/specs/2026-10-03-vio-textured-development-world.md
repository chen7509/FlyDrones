# Textured development world for VIO interface validation

## Purpose

The existing single-vehicle development-world `1701` produced camera images
with at most nine FAST-20 corners per 160x120 frame; the pinned OpenVINS
initializer never initialized. Create a separately identified, deterministic
**development fixture** with additional visual texture to test whether the
same RGB/PX4-IMU capture and research adapter can process feature-rich input.
This does not alter any frozen evaluation world or measure fly policy quality.

## Design

Read an existing development world JSON and SDF, preserving the JSON bytes and
all SDF collision, pose, physics, sensor and plugin elements. Add relocatable
PBR albedo-map references only to the ground and static obstacle visuals.
Generate the PNG assets deterministically from a fixed seed; store the
generator version, source hashes and asset hashes. The episode runner snapshots
only JSON and SDF, so copy the asset PNGs into the episode output directory
before launch; relative paths in the copied SDF then resolve. Verify this
copying explicitly rather than assuming a texture was rendered.

Measure the actual captured images with the unchanged pinned FAST-20 diagnostic
before attempting OpenVINS. Preserve every failed fixture/capture attempt and
the full resulting images, ULog and logs. Keep OpenVINS commit, calibration,
config and adapter fixed relative to the preceding offline smoke test. Report
the first complete attempt regardless of outcome. Never tune against sealed
20-world evaluation scenes, infer VIO quality from synthetic texture alone,
or feed Gazebo truth to OpenVINS. The existing controller may still consume
Gazebo-truth odometry for this data collection, which must remain explicit.

## Validation gates

1. Unit tests prove deterministic assets and unchanged world/physics/collision
   elements, plus invalid-input rejection.
2. Gazebo SDF parses; a camera image contains visible mapped texture and
   materially more FAST-20 corners than the old development image. A reference
   render with the original SDF distinguishes a true material effect from
   incidental camera movement.
3. Only after those gates, run one PX4/Gazebo single-vehicle development
   capture with RGB, camera info and ULog; verify per-file hashes and no
   stranded PX4/Gazebo process. A collision or low RTF remains a failure.
4. Run the pinned OpenVINS adapter once with fixed config on the IMU-overlap
   subset. Initialization, trajectory, covariance, image/IMU timing and EKF2
   fusion are separate claims with separate evidence.

Gazebo SDF PBR texture URI guidance:
https://gazebosim.org/api/sim/10/migrationsdf.html#textures
