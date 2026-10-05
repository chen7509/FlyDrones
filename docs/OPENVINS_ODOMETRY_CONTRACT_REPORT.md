# OpenVINS odometry contract — development evidence, 2026-10-06

This stage implements offline native-state conversion and file-only MAVLink2 encoding for the fixed PX4 consumer. It does not send data to PX4, authorize fusion, replay the estimator or run a new physical episode. Base PR32/commit2114741 remains sealed.

## Research and choice

Sources were checked before implementation; raw source and license snapshots plus hashes are in results/openvins-odometry-contract-dev-1701/research-provenance.json and licenses/. A first sparse-checkout LICENSE lookup failed; partial snapshots are retained and the license was retrieved from the pinned Git object without changing the checkout.

|Candidate|Version/activity snapshot|License|Interface/resources/decision|
|---|---|---|---|
|OpenVINS|69488123ed9362dd44b6f28e7f4680abbff1442b; nonarchived, last push2025-11-30|GPL-3.0|Reuse native q_GtoI,p_G,v_I,w_I and approximate covariance; no new estimator or library rebuild. Constant-size matrix conversion, actual batch timing below.|
|PX4|d6f12ad1c4f70ad3230afd7d86e971421e02fef4, existing pinned build|BSD-3-Clause|Read receiver, VehicleOdometry and EKF2 consumers. No physics/runtime modification. Online acceptance still untested.|
|pymavlink|installed2.4.49; upstream20111a041f3abfeda1c4b34dae43c0cd4441ef52, nonarchived, pushed2026-10-02|Library metadata LGPLv3; generator (L)GPLv3 with generated-code MIT exception|Reuse common v2 in existing WSL; no ROS installation or socket. Windows lacks package, so real wire checks run in WSL; geometry/regression tests run on Windows.|
|MAVROS|ros2 5c68b905ab30de6ce630822dc46c33467e8f23ea, nonarchived, pushed2026-09-27|BSD/GPLv3/LGPLv3 alternatives|Useful reference. Not adopted because direct message path already exists; adding ROS2 adds integration/runtime cost. Resource use not measured.|
|SciPy Rotation/NumPy|Existing WSL1.16.3/2.5.3; no upgrade|BSD|Reuse matrix/quaternion/eigensolver implementations, with separate analytic and finite-difference tests. No claimed VIO improvement.|

Primary references: [OpenVINS JPL update](https://docs.openvins.com/classov__type_1_1JPLQuat.html), [OpenVINS ICRA2020 paper](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf), [MAVLink ODOMETRY](https://mavlink.io/en/messages/common.html#ODOMETRY), [PX4 external-estimation guide](https://docs.px4.io/main/en/ros/external_position_estimation). The guide's 30–50Hz recommendation does not prove firmware acceptance or online timeliness. The OpenVINS paper motivates the estimator representation; it does not validate this uncalibrated fast covariance.

The fixed PX4 [VehicleOdometry definition](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleOdometry.msg) explicitly specifies body-frame attitude variance. Its receiver copies orientation covariance diagonals directly; it does not convert Euler variances. The adapter therefore names its `px4-d6f12ad-body-tangent` profile explicitly. This is not a generic Euler-covariance bridge and is not automatically valid for another consumer.

## Implemented behavior

For the existing identity FRD IMU/body extrinsic, S=diag(1,-1,-1), p_LOCAL=S p_G and R_BODYtoLOCAL=S R_GtoI^T. Quaternion output is Hamilton wxyz. Body velocity/angular rate stay in BODY_FRD; local heading remains arbitrary, not North. Covariance uses the full permutation/rotation Jacobian into [p_LOCAL,theta_BODY,v_BODY,omega_BODY], retaining cross terms in the evidence. MAVLink carries two6x6 blocks; pose–twist cross terms cannot be carried. Fixed PX4 retains only variance diagonals. None of these operations calibrates upstream uncertainty.

The file-only session contract requires explicit clock/session identifiers, sample-to-wire offset, observed time, reset-event total and quality. It rejects stale/future/duplicate samples, wire-time overflow, clock/session changes, reset rollback/jumps and invalid numeric data. The counter wraps255→0 only from supplied reset total256. No clock synchronization or reset detection is inferred. Quality0 stays unknown and -1 stays failed. Public initialized=false remains visible; every record always has fusion=false.

Serialization uses real pymavlink2.4.49 bytes and a real decoder. Synthetic test metadata is labeled synthetic; it is never attached to the frozen flight. No network connection is opened.

## Results and current gate

- Frozen source ZIP SHA25c50d945156e6a05e14e52afa73b9acffd048a1bb3dbdfb6d484e7685015d29 and native JSONL SHA19d468a25a2417bab08ebe19f3b00606c8b5b13f788206a0663aacdc752882d4 verified before conversion.
- All2136 entries retained:2030 geometry candidates,106 unavailable,0 wire packets from real evidence,0 fusion eligible. All202 prearm entries still have public initialized=false.
- One offline conversion batch took0.400536s including validation. This is not online latency or a repeatability claim; no performance gate was changed.
- Focused tests initially failed38/38 due to missing implementation; first geometry/session pass38/38. Failure-preservation adds one test (39 total). Mutable-wire-field rejection failed on changed frame_id before guard implementation. Real WSL wire checks then passed9 roundtrips across level/tilted attitudes and quality-1/0/80, plus9 corrupted-field rejections.
- Windows full regression passed666 tests in223.04s with2 existing warnings. The later serializer guard is exercised by the WSL wire checks, not by the Windows suite. Independent review remains pending until recorded below.

Final review found no Critical/Minor and one Important dependency compatibility issue: SciPy1.10 lacks as_quat(canonical=). Added a legacy-signature regression that failed before the fix, and used explicit quaternion sign selection without raising the dependency minimum. This is a signature-emulation regression, not an installation test of actual SciPy1.10. Final full regression passed **667 tests in205.26s**, with the same2 existing warnings; Ruff/diff checks passed. The final WSL serializer rerun passed9 roundtrips and9 corruption rejections. A conversion-only parity check confirmed all2136 exported records exactly unchanged after the compatibility fix; no estimator replay was repeated.

Reviewer-declined areas remain explicit limitations: online/fusion/flight, nonidentity mounting/other consumers, and covariance calibration. No second review was requested after the targeted fix. Full evidence, failure logs, reviewer findings and final test results are preserved rather than deleting the working evidence directory. Process checks found no related WSL simulation/replay or Windows Python/PX4/Gazebo process at their recorded check times.

|Status|Evidence boundary|
|---|---|
|Verified locally|Analytic pose/body vectors, finite-difference body-tangent Jacobian, full covariance cross terms; frozen-input geometry and unavailable-row retention; explicit clock/reset rejection; synthetic real MAVLink2 serialization.|
|Only implemented|Reusable file-only message adapter/session contract; not an online clock or reset producer.|
|Untested|Online disarmed capture, live timestamps/arrival, estimator reset detection, calibrated health/quality, EKF2 fusion acceptance and faults. No new physical validation.|
|Still failed|Earlier single physical collision/fullfly latency; five-camera WSL0.873RTF below0.95. This stage changes none of them.|

Next dependency is a disarmed online shadow producer using actual timestamp/arrival/reset evidence, after a separate researched design. It must demonstrate fresh output without repeated image frames and keep VIO→EKF2 disabled while public initialization and health gates remain unmet. No20/100-aircraft expansion, HITL or real flight qualification follows from this report.

Preparatory source inspection found HIGHRES_IMU subtracts EKF-estimated biases, while SCALED_IMU quantizes integrated data and uses a different timestamp field. Neither is automatically equivalent to the validated ULog sensor_combined input. The fixed PX4 dds_topics.yaml exposes sensor_combined; runtime support/dependency cost and timestamp correspondence must be researched next. Details and source hashes are retained in next-online-research.md and next-source-snapshots/. No online estimator or new simulator was launched for this work.

Evidence archive: evidence/openvins-odometry-contract-dev-1701.zip and its per-member SHA256 index. The archive depends on the unchanged PR32 sealed source and its prior physical evidence chain; this archive is not a standalone simulator installation. Draft PR and archive hash are recorded in the final closure commit.

Publication closure: [draft PR33](https://github.com/chen7509/FlyDrones/pull/33), implementation212bbcf and reviewed-fix/evidence87169fd. ZIP68members/2,238,411bytes, SHA256 **1bd076e12f4171306af197c72086ab821e18316ef07ccfd215a61258a62c5dde**. This closure paragraph and completed publication checkbox are later than the sealed snapshot; the archive is unchanged.
