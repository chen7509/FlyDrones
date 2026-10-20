# Estimator-heartbeat corrected physical attempt design

## Authorization and immutable target

The user has authorized continued autonomous execution. `study-v13` passed its prepare-only audit before and after its production startup preflight, and again after the sealed evidence commit. A separate stage may therefore run exactly one physical development attempt at the new `study-v13/capture-v1` destination. The target, dispatch, completion and all partial outputs are immutable. Any precondition failure stops before dispatch; once the destination exists it is never overwritten or automatically retried.

## Frozen workload and gates

Execute the command already declared in `study-v13/study-manifest.json` without changing its workload: 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGB-D, fixed vehicle, gravity, board textures, supported-motion and 26 N lateral-force profiles, 200 ms future anchor, 8 s initial readiness limit, unchanged 250 ms causal dependency stages, 2 s source/native/fan-out watchdogs and 300 s worker/supervisor bounds. Use the pinned OpenVINS binary/configuration and native-reference module.

Before dispatch require the current committed head, passing `study-v13` post-startup package audit, passing production startup audit, exact future destination, absent destination and dispatch/completion files, and an empty active-resource scan. Do not lower load, extend deadlines, tune estimator/noise/force, use Gazebo truth for estimator initialization or correction, publish ODOMETRY, arm, bypass PX4 or relax safety/fusion gates.

## Evidence and interpretation

Preserve success or failure: command, head, all audits, resource scans, supervisor journal, runtime mappings, ULog, sensor/fan-out/native/estimator records, reference/physics/motion traces and terminal errors. Cleanup conclusions remain restricted to the owned original process group; escaped descendants require separate evidence.

Completion of 25 s and public initialization do not by themselves qualify VIO. Accuracy requires the frozen trajectory gauge and complete reference interval; health also requires causal state continuity, regular updates, reset/quality/covariance evidence and failure-injection rejection. Any platform, runtime, source, estimator or safety refusal must be classified at its first supported cause and may not be called a fruit-fly learning failure. This single-machine attempt cannot qualify EKF2 injection, flight, five vehicles, twenty vehicles or the final open-source comparison.
