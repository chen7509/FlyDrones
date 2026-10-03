# Frozen OpenVINS clone motion audit

The previous development-world geometry audit found 178/183 positive-depth
tracks using an offline PX4 EKF2 reference, but OpenVINS rejected every visual
candidate. Compare the actual camera clone poses used by upstream OpenVINS to
EKF2 short-window relative motion without changing estimator inputs, parameters,
or safety gates. This is a root-cause diagnostic, not a VIO or flight pass.

The [OpenVINS ClonePose API](https://docs.openvins.com/structov__core_1_1FeatureInitializer_1_1ClonePose.html)
defines `R_GtoC` as global-to-camera rotation and `p_CinG` as camera position in
the estimator global frame. Its [feature initializer](https://docs.openvins.com/classov__core_1_1FeatureInitializer.html)
uses these clones for triangulation. PX4
[VehicleAttitude](https://docs.px4.io/main/en/msg_docs/VehicleAttitude) is FRD
body-to-NED; [VehicleLocalPosition](https://docs.px4.io/main/en/msg_docs/VehicleLocalPosition)
is NED with validity and reset counters. Compare rotations, camera-frame
translation directions and baseline magnitudes over identical observation
timestamps. These are gauge-invariant within a window and require no global
alignment or scale fit.

Extend the isolated GPL-3.0 OpenVINS diagnostic build at upstream commit
`69488123ed9362dd44b6f28e7f4680abbff1442b` with logging-only output of
the camera clone pose for each of the 1001 post-clean track observations. Replay
the same 604 RGB frames and PX4 IMU input with identical config and runner;
require state CSV SHA-256 unchanged. Parse exactly 183 candidate attempts and
1001 clone poses, match every `(window, feature ID, camera, observation time)`
without silently dropping repeats or failures, and retain raw logs and hashes.

Use the previous frozen EKF2 interpolation and camera extrinsic for the
reference. Report the OpenVINS-clone-based ray geometry and the EKF2-based
geometry per attempt, but do not equate the independent ray solver's condition
number with OpenVINS's internal threshold. Preserve unscored cases and reasons.
Report where short-window relative rotation, translation direction and metric
baseline differ, including temporal stratification and degenerate baselines.
Neither estimator is ground truth; the controller in the episode used Gazebo
truth, but that truth must not enter this diagnosis. No threshold relaxation,
new simulation, model training, or test-set tuning occurs in this stage.

The result should identify the next *single* testable hypothesis, not assert a
unique cause from one development flight. Formal benchmark, PX4 EKF2 visual
fusion, multi-aircraft gate, HITL, native Linux, and real flight remain closed.
