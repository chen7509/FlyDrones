# Five-Camera Render Capacity Amendment 31: Post-Warmup Bridge Clock Release

## Trigger

The 20-topic source warmup passed, then Gazebo paused at 4 ms and all five PX4
processes started at that common time. None reached the bridge log because PX4's
lockstep bridge initialization required a new simulation clock step. Requiring the
five bridge logs before the final resume therefore became a deadlock only after
the source-warmup stage was introduced.

## Correction

Keep the successful source warmup and common-time PX4 launch. After all five PX4
processes are recorded and waiting, issue the single final world resume so all
bridges receive clock progress together. Then require five original bridge logs,
exact 20/20 transport topology, and concurrent five-vehicle EKF health. Do not add
per-instance pulses or retries.

## Acceptance

- Structural tests prove the single final resume follows all PX4 launches and
  precedes the five-bridge and exact-topology gates.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- The native single-subscriber development cell is rerun with failures preserved.
