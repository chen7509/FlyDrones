# Connectome capture input gate

The v2 course may save student sequences only after the controller observation
comes from deployment-visible localization and timestamped RGB-D. The current
`NativeGazeboPx4Backend.observe()` uses Gazebo model truth for body and camera
pose; it remains valid for the historical simulator comparison but must fail
this capture gate. `score_sample()` may still use truth for independent scoring.

Add a small, read-only gate before the first teacher step or sequence write.
Its evidence names the backend's actual odometry and camera-pose sources, the
estimator and camera-pose sample times in the simulation-clock domain, EKF2
position/height/heading validity, a validated camera extrinsic digest, and the
inspected upstream EGO commit/image identity. Reject mismatched source labels,
truth or unknown sources, stale/misaligned frames and estimates, bad numeric
observations, unvalidated calibration, or uninspected teacher identity. A
synthetic passing test proves only the rule, not that PX4 currently supplies
the required evidence. No capture is authorized until the live producer is
wired and validated in PX4/Gazebo development scenes.

Use the existing fixed camera and control rates to set explicit conservative
limits: image and estimate no more than 100 ms old, camera pose within 50 ms
of the image. Calibrated EKF2/GNSS localization can be identified separately
from VIO; it does not count as external-vision fusion. The camera–IMU
extrinsic currently in the project is provisional, so it cannot satisfy the
validated-calibration flag.

Primary contracts: [PX4 EKF2](https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf),
[MAVLink local position and odometry](https://mavlink.io/en/messages/common.html),
[OpenVINS calibration](https://docs.openvins.com/gs-calibration.html).
