# Five-Camera Render Capacity Amendment 32: Reset Warmed World Time

## Trigger

All 20 Gazebo sensor sources passed warmup, but PX4 processes then attached at the
paused 4 ms warmup time. Their lockstep schedulers reported that nonzero initial
absolute time and all five estimators were unhealthy or indeterminate. Earlier
zero-time attachment allowed a subset to initialize, showing that source warmup
and PX4's zero-time lockstep requirement must both be satisfied.

## Correction

After the successful source warmup and pause, issue a bounded Gazebo WorldControl
time-only reset while remaining paused. Preserve the reset response. This retains
the initialized sensor systems and model state while returning simulation time to
zero before any PX4 process attaches. Keep the common final clock release and all
source, topology, health, and scoring gates unchanged.

## Acceptance

- Structural tests prove warmup pause precedes the time-only reset and the reset
  precedes the first PX4 launch.
- The reset response is mandatory trial evidence.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- The native single-subscriber development cell is rerun with failures preserved.
