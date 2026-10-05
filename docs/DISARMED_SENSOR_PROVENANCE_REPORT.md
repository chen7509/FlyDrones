# Disarmed sensor provenance — development evidence, 2026-10-06

This stage captured a single disarmed PX4/Gazebo sensor stream and audited its source, clocks, recording delay and ULog correspondence. It did **not** run online OpenVINS, send ODOMETRY, grant fusion eligibility or fly. Base PR33/1276201 remains sealed. It is a necessary source-validation prerequisite to the online estimator shadow, not completion of that shadow.

## Research and source choice

Research preceded implementation. Pinned source snapshots, GitHub metadata, licenses and hashes are in results/disarmed-sensor-provenance-dev-1701/research-provenance.json and source-snapshots/. An initial HTTPS EOF and a subsequent empty GitHub response are retained; later authenticated read-only retrieval succeeded without disabling certificate verification.

|Candidate|Version, license and maintenance|Interface, resources and decision|
|---|---|---|
|Gazebo sensor transport|Installed sensors8 8.2.2, sim8 8.15.0, transport13 13.6.0; Apache-2.0. gz-sensors8 maintenance snapshot8d9fef11078368622150c98688a6eda5fc7163c1, nonarchived, pushed2026-10-02; not claimed as installed package commit.|Reuse existing250Hz IMU and160×120 RGBD10Hz callbacks, no dependencies added. Explicit FLU→FRD, retain native samples and callback arrivals. Selected for this sensor-only capture; calibration/dynamic suitability for OpenVINS remains unqualified.|
|PX4 sensor_combined via uXRCE|PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4, BSD-3-Clause; existing compiled client2.4.0. Candidate Agentv2.4.3/73622810d984349b80bbac0ef55fc0b694d62222, Apache-2.0, nonarchived, pushed2026-09-03.|YAML exposes sensor_combined, but generated polling defaults10ms/100Hz. Neither Agent nor ROS exists here. Deferred: installing subscriber/runtime plus validating rate and QoS would change the integration profile; runtime resource cost unmeasured.|
|MAVLink IMU streams|Same pinned PX4, existing pymavlink2.4.49; library LGPLv3 details inherited from PR33.|HIGHRES_IMU subtracts estimated bias; SCALED_IMU quantizes integrated measurements and uses a different timestamp. Rejected as silently equivalent raw inputs. pymavlink reused solely to receive heartbeat, with no outbound messages.|
|OpenVINS|Pinned69488123ed9362dd44b6f28e7f4680abbff1442b, GPL-3.0, unchanged from PR33.|No estimator invoked or rebuilt. Its measurement/noise assumptions must be reconciled with the selected raw source before online use.|

Primary references: [PX4 uXRCE-DDS](https://docs.px4.io/main/en/middleware/uxrce_dds), [Agent documentation](https://micro-xrce-dds.docs.eprosima.com/en/latest/agent.html), [Gazebo IMU API](https://gazebosim.org/api/sensors/8/classgz_1_1sensors_1_1ImuSensor.html), [OpenVINS ICRA2020 paper](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf). The paper supports the estimator architecture, not equivalence of these sensor paths or calibrated uncertainty for this fixture.

Pinned GZBridge rotates FLU vectors to FRD and replaces the simulator sample stamp with its callback hrt time. VehicleIMU trapezoidally integrates and applies calibration; sensor_combined reports an interval average, not an instantaneous raw sample. Calibration storage can also be informed by estimator bias in PX4, so it is not generally an estimator-independent raw interface. Here integral periods are4000µs, accelerometer relative timestamp0, clipping0, accelerometer calibration_count0 and gyro calibration_count1. The count alone does not prove a nonzero correction.

## Implementation and physical evidence

The standalone capture avoids the existing backend's auto-arm path. It uses a private transport partition/runtime, unchanged sealed PR30 development world/textures, pinned PX4 binary SHA e8af7cbcac255ec3c79bb5fa278459fd0b130b4b189de9269e3689cb9789f4cb, 1ms physics and unchanged250Hz IMU/10Hz RGBD. Bounded recording rejects overflow, duplicate/regressed samples, invalid values, unexpected fields, armed heartbeats and file overwrite. IMU orientation/pose ground truth is not admitted. Depth records establish timing/resolution only; depth pixel arrays are not saved or consumed by an estimator.

One25s simulated capture completed:6251 IMU,251 RGB frames,251 depth records,251 camera-info messages,24 unarmed heartbeats. ULog has50 actuator-armed records, all false; arming states are[1]. PX4 exited0. GCS-not-connected/initial-height warnings are retained, not classified as flight readiness. Queue maximum5. No repeatability or aircraft-capacity qualification is inferred from this single short stationary run.

Captured ULog is7,051,474bytes, SHA256 **90bfa3b80fb752d07667012fde6275b51e5e4db82f6fdb1e1c83c2433477555a**. The audit verifies its hash, RGB/camera metadata and per-event derived fields/order. Auditv1 precedes added record-level hardening; auditv2 checks the same immutable physical input. The producer was not rerun after adding the read-only audit function. A contemporaneous producer-module hash was not recorded; archived final code is therefore not misrepresented as a pre-run source seal.

IMU intervals are4ms after the initial3ms interval; RGB/depth100ms after initial98ms. No nonmonotonic samples. All6025 ULog sensor_combined timestamps exactly match raw IMU sample timestamps in this capture. Direct instantaneous comparison shows gyro max difference0.002551rad/s and acceleration0.020657m/s². A separate source-derived diagnostic using the previous/current trapezoidal mean, **without fitting offsets, changing input or retiming**, reduces maxima to1.06e-9rad/s and2.84e-6m/s². This supports axis/time correspondence and identifies integration as the dominant difference here; it does not validate dynamic coning/calibration, raw-input noise parameters or universal source equivalence.

Callback-to-writer P95: IMU3.825ms, RGB0.311ms. Callback-to-record-preparation maxima: IMU16.722ms, RGB17.608ms. These exclude sensor-generation/transport-before-callback and estimator processing; they are not end-to-end VIO latency. Capture/cleanup wall29.350s, outer process32.11s, peak RSS797272KB. This scope is not the five-camera capacity benchmark.

## Validation and limits

Initial14 targeted tests failed before implementation and passed afterward. A later audit-corruption regression failed before its API existed and then passed, making15 targeted tests. Tests cover axis/time handling, invalid values, forbidden fields, duplicate data, queue/I/O failures, output protection, known non-equivalent IMU data and recorded-field tampering. Full regression and independent review results are recorded in the closure below.

|Status|Boundary|
|---|---|
|Verified locally|One unchanged-load disarmed physical sensor capture; matching RGB/depth timestamps; ULog disarm evidence; exact timestamp/axis correspondence and stationary integration diagnostic; recorder fault rejection.|
|Only implemented|Reusable recording and audit utilities. No online estimator or reset detector.|
|Untested|Dynamic source equivalence/calibration, actual online OpenVINS arrival-to-output delay, reset/health evidence, public-initialized prearm availability, EKF2 injection/fusion and recovery.|
|Still failed|Earlier physical collision and full-fly decision latency; five-camera0.873RTF below0.95. No20/100-aircraft, HITL or real-flight gate passed.|

Next: design a distinct raw-Gazebo-IMU input profile with explicit units/extrinsics/noise provenance and causal image/IMU buffering; verify fixed-input fault rejection before a disarmed online OpenVINS shadow. Retain real sample/arrival/processing/reset timestamps and unknown health. Do not feed PX4 bias-corrected IMU back into VIO, reuse old images for frequency, relax public initialized, or send ODOMETRY until its separate gate is met. DDS remains an alternative requiring explicit dependency/rate validation. No native Linux installation is required.

Rulings: this bounded source stage precedes estimator shadow because silently switching source would invalidate the prior contract (cost: an extra stage); preserve working evidence and failures as authorized (cost: disk usage). Existing physical failures remain intact.

Full Windows regression: **682 passed in214.32s**,2 existing warnings; Ruff and diff checks passed. Independent review pending. No claim of online VIO follows from these tests.
