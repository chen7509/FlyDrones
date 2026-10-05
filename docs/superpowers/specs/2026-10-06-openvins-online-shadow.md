# Native OpenVINS disarmed online shadow

Continue PR35 without changing its sealed inputs. This development experiment connects raw simulated sensor callbacks to the pinned OpenVINS native library. It grants no flight or EKF2 fusion eligibility.

## Contract

The existing CausalInput releases transformed IMU and same-stamp calibrated image metadata only after an actually received later IMU. A single recorder thread owns the scheduler and one separate native process owns VioManager, including synchronous initialization and fast propagation. An image is transferred as exactly 160×120×3 RGB bytes, never a filename; its recorded PPM is closed first. No truth, attitude initialization, external reset or fabricated quality enters this interface.

The pipe has one request in flight, a maximum 512-byte header and fixed image size. Each request has a consecutive sequence, positive signed-64-bit sample/arrival/dispatch clocks, and finite IMU vectors. The native parser rejects malformed, duplicate, regressed, missing-boundary, excessive-gap and extra-field input. Images become owned grayscale matrices. A dedicated acknowledgement descriptor separates protocol data from upstream logging. Both sides retain receive/start/end/ack clocks and verify the Linux monotonic clock relationship. A two-second write/ack deadline bounds stalled workers; a separate source watchdog detects absent IMU/RGB/CameraInfo even when no camera is pending. These are research process guards, not flight safety qualifications.

Keep 25 seconds of requested simulation, 1 ms physics, 250 Hz raw IMU and 10 Hz 160×120 RGBD. Failure may terminate early and all partial evidence remains. The prospective `raw-model-zero-bias-diffusion-v1` configuration uses the maximum-axis SDF white-noise density (sample standard deviation × sqrt(.004)) and zero diffusion as an explicit ideal simulated-model assumption. It is NOT calibrated; unknown real bias dynamics and scalar approximation remain limitations. Other estimator settings remain unchanged. Freeze configuration before the live run and do not tune it to obtain initialization.

Record every camera's internal/public initialization, initializer reference, state time, regular-update time and ZUPT latch. Attempt fresh 50 Hz native propagated targets only after actual later IMU receipt, retaining unavailable targets. No repeated frames to fabricate frequency. Public initialization stays a gate; quality and reset remain unknown. No ODOMETRY network publication, arming or control command. Retain actual disarmed heartbeat/ULog evidence, all inputs, hashes, timing and process cleanup.

## Acceptance and limits

First test synthetic parser/analytic RGB, clock ordering, invalid packets, output overwrite/path protection and stalled children; then run one new online disarmed shadow. Online completion, estimator initialization, state numerical validity and fusion qualification are separate conclusions. Failed initialization or insufficient throughput is a valid retained result. Five-machine 0.873 RTF remains below 0.95; no broader swarm gate is changed. No old estimator replay or finished audit is repeated.

## Development correction after retained capture-v1

The first physical run stopped at1s simulation because the first RGB arrived4.040s after native process startup; a source2s guard conflated cold renderer startup with operational source loss. This is a harness startup failure, not an estimator failure or a passed run. Preserve v1 unchanged. Before capture-v2, separate a10s startup deadline (all three sources must appear) from the unchanged2s operational silence deadline. Record ready/start/last-source clocks and test both phases. No change to native2s processing limit, scene, physics, sensor rates, noise configuration, estimator gates or the five-machine RTF criterion. A newly named run is justified by this material lifecycle fix, not by tuning the VIO result.
