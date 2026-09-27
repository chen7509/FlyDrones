# Gazebo Camera Phase Scheduling — Amendment 5

Date: 2026-09-27

## Trigger

The preserved single-vehicle development run
`results/camera-phase/dev-phased-single-20260927-5` passed camera phase, mission,
landing, ULog, renderer and resource-release gates. The actuator probe wrote a
complete stop event with zero callback errors and unsubscribed all topics, but
its process then exited `-6`. Its stderr records a pybind11 `dec_ref` assertion:
a Gazebo Transport callback tuple was destroyed when the Python GIL was not
valid.

The actuator probe creates each motor callback inline for `Node.subscribe` and
retains only topic names. This leaves callback ownership and destruction timing
to the binding. It is the same callback-lifetime boundary already proven unsafe
for the phase observer, now exposed during interpreter teardown rather than
during message delivery.

## Correction

The actuator probe will retain strong Python references to every motor and
odometry callback for the full subscription lifetime. It will unsubscribe every
topic first, then explicitly clear the references while Python still owns the
GIL, and only then write the final stop event and return.

No actuator data, PX4 command, controller, camera or scoring behavior changes.
The complete development suite must again use new identifiers after this cleanup
correction.

## Frozen boundaries

All camera timing targets, thresholds, dispatch correction, drain behavior,
flight gates and failure-preservation rules remain unchanged. The abnormal-exit
run remains preserved and cannot be reused as smoke or formal evidence.
