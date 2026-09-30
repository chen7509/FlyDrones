# Five-Camera Render Capacity Amendment 33: Zero-Time Joint Source Release

## Trigger

Time-only reset allowed three PX4 estimators to become healthy but left other
barometer and magnetometer streams permanently absent. Gazebo sensor update timers
do not reliably tolerate the backwards time jump. Pre-PX4 warmup without reset is
also incompatible with PX4's zero-time lockstep requirement.

## Correction

Start all five PX4 processes while the untouched world is paused at simulation
time zero. Issue the single final resume, then immediately require one real message
from every one of the 20 Gazebo flight-sensor sources. Continue with five bridge
logs, exact 20/20 topology, and concurrent EKF health. Remove the warmup-specific
resume, pause, and time-reset controls; preserve the 20-topic source report and the
single final resume.

## Acceptance

- Structural tests prove all PX4 launches precede the single resume, the 20-topic
  source witness follows resume, and bridge/topology/health gates follow it.
- Obsolete warmup control artifacts are not required.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- The native single-subscriber development cell is rerun with failures preserved.
