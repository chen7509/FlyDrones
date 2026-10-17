# Source-diagnostic live-wire study declaration

## Purpose and boundary

The previous `live-wire-study-v2` declaration binds an owned Agent but cannot carry the newly staged PX4 `source-diagnostic-v1` logger list. A new `live-wire-study-v3` declaration must bind the changed logging load before any unarmed physical attempt. This stage implements and tests declaration validation only; it neither dispatches a physical run nor authenticates PX4/DDS origin.

## Contract

- v3 retains the v2 Agent requirement and unchanged 25 s, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGB-D, motion, safety, clock and timeout profiles. It uses a new development study ID and seed 27603. v1 and v2 keep their exact existing schema and commands.
- The manifest adds exact file records for the canonical repository `config/px4/source-diagnostic-v1/logger_topics.txt` and `profile.json`. The runtime binding inventory and baseline include both under a dedicated diagnostic role. The execution contract carries the existing `capture-px4-logger-profile-v1` record, including the two hashes and `PX4_PARAM_SDLOG_PROFILE=0`; all source, logger-selection and fusion qualification flags stay false.
- The expected production command adds `--logger-diagnostic-profile source-diagnostic-v1` after the owned Agent option. A missing, changed, duplicate, substituted or undeclared file or command argument fails closed. The file adapter revalidates the current canonical profile and baseline. Pure document validation remains side-effect free.
- A preparation result never grants activation. A separately frozen, resource-eligible single physical episode must still show the actual PX4 logger selection, ULog `vehicle_odometry`, owned PX4/Agent/ROS and clock/reset/camera provenance. New logging work is a changed-load diagnostic and cannot be counted as the original capacity workload.
- v3 dispatch refuses when observed host available RAM is below the unchanged 4 GiB gate. In WSL it must query Windows host RAM, not just WSL's virtual allotment; unknown or failed observation refuses. Check before writing an activation request and again immediately before dispatch. Preserve the first observation in the request and a failed request if the second observation falls below the gate.

## Evidence and acceptance

Test the new v3 happy path and negative mutations first, plus v1/v2 regression and file-adapter drift refusal. Preserve RED/GREEN, changed-file lint, the manifest/spec hashes and all failures. No test in this stage may send ODOMETRY, arm, inject EKF2 or use Gazebo truth as VIO.
