# Heartbeat simulation-time readiness design

## Problem

The immutable `study-v15/capture-v1` attempt proved that the OpenVINS initializer handoff works, then refused at simulation time 4.647 s because the last PX4 heartbeat was 2.000774305 s old in host wall time. The same heartbeat was only 0.968 s old in simulation time. PX4 and Gazebo were running in lockstep and the next 1 Hz simulation-time heartbeat was not yet due. This is a clock-domain mismatch in the readiness gate, not a VIO, learning, training, or flight failure.

PX4's Gazebo bridge advances PX4 time from Gazebo simulation time, and the official documentation explicitly allows simulation to run slower or faster than real time. MAVLink heartbeat loss thresholds are channel policies, while MAVSDK also warns that setting a watchdog exactly at a nominal interval is vulnerable to scheduling jitter. Raising the existing wall timeout or scaling it dynamically from observed real-time factor would hide real source failures and make the policy workload-dependent, so both options are rejected.

## Contract

`JournaledReadiness` keeps host monotonic-wall freshness for IMU, RGB and CameraInfo receipts. Queue reconciliation, native processing, source writer, pending-observation and supervisor deadlines remain wall-time watchdogs. Only heartbeat liveness uses simulation time: the newest journaled, wall-fresh IMU observation is the current simulation reference, and the newest journaled heartbeat must be no more than 2 s old in that domain.

Heartbeat and IMU simulation stamps must be positive integers. Heartbeat simulation stamps must not regress; a future heartbeat relative to the current IMU, a regressed heartbeat, or a simulation age above 2 s refuses readiness. Equal simulation stamps remain valid because more than one receiver observation can occur before lockstep simulation advances. Wall age of the heartbeat remains recorded as a diagnostic and does not grant or revoke readiness by itself. Identity, arming, journal ordering and failure latching are unchanged.

The returned proof records both clock domains and the fixed 2 s limits. No timeout is increased and no real-time-factor estimator is introduced.

## Verification boundary

First use synthetic RED/GREEN cases for slow healthy simulation, actual simulation silence, stale high-rate sensors, future/regressed simulation stamps and unchanged heartbeat identity/arming rejection. Then replay the immutable `study-v15` terminal values without starting PX4, Gazebo, OpenVINS, training or any physical process. The replay must show that the former wall-age refusal becomes ready while a counterfactual IMU simulation advance past 2 s refuses.

This stage does not rerun the physical attempt and does not qualify VIO accuracy, quality, reset handling, covariance, fusion, ODOMETRY, EKF2, flight, fruit-fly learning or swarm behavior. A later physical attempt requires its own sealed design and unchanged workload.
