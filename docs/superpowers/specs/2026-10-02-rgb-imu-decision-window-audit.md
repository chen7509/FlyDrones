# RGB/IMU decision-window coverage audit

The existing development episode retained all camera frames, PX4 ULog IMU
samples, and every controller decision with its observed frame timestamp.
Before launching another simulation, audit that immutable evidence. Distinguish
the raw capture interval from the interval actually presented to the
controller, from the first to the last decision's observed RGB frame. This is
a **data-availability preflight** and does not establish calibration, VIO,
real-time throughput, task success, or estimator safety.

Inputs are the archived frame manifest, one verified ULog, and result JSON.
Reject missing/changed evidence, nonmonotonic decisions, an unrecorded
decision frame, or a window with fewer than two distinct camera frames. Keep
all raw frames in the archive. Within the decision window, report frame and
IMU counts, first/last timestamps, counts before/inside/after the IMU range,
maximum nearest IMU difference, and largest adjacent IMU gap. A development
coverage pass requires every window frame within the IMU range and both timing
metrics at most 20 ms. This bound is a **predeclared engineering check**, not
a camera/IMU synchronization or VIO accuracy specification. Leave the full
capture's 27 early and one trailing unpaired frames visible.

First add normal, missing, boundary, and nonmonotonic unit tests. Extend the
existing offline analyzer without changing its v1 full-capture fields or the
archived original result. Save the new analysis separately, with hashes back
to the original sources. If the old evidence meets this narrow gate, avoid a
redundant PX4/Gazebo run; move next to camera intrinsics/extrinsics/time
calibration research and a pinned upstream VIO offline smoke test.
