# Five-Camera Render Capacity Amendment 30: Gazebo Sensor Source Warmup

## Trigger

An external in-run witness subscribed directly to all 20 Gazebo flight-sensor
topics. Nineteen delivered a message, while vehicle 2's magnetometer delivered
none within 15 seconds. In the same retained run, PX4 also lacked IMU data on
vehicles whose Gazebo IMU topics did deliver. Exact endpoint cardinality therefore
proved transport registration but did not prove that every sensor source had
initialized before PX4 consumption began.

## Correction

Before starting any PX4 process, resume the statically preloaded Gazebo world for
a bounded source warmup. Subscribe concurrently to IMU, magnetometer, GPS, and
barometer topics for all five models and require at least one real message from
each. Preserve a 20-topic source-warmup report, then pause the world. Attach all
five PX4 processes at that common frozen simulation time, require exact 20/20
transport topology, and issue the existing single scored resume. Preserve both
warmup world-control responses. Do not retry or mask a missing source.

## Acceptance

- Structural tests prove the warmup resume, 20-topic source report, and warmup
  pause all occur before the first PX4 process is recorded.
- The three warmup artifacts are mandatory trial evidence.
- Focused tests, Ruff, Bash syntax, and diff checks pass.
- The native single-subscriber development cell is rerun with failures preserved.
