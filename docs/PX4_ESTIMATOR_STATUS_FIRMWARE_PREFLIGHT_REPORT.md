# Isolated PX4 status firmware: pre-build state

The fixed PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` source is now in
a new detached WSL worktree at `~/px4-status-worktrees/firmware-v1`. Its
tracked status is clean. The original `~/PX4-Autopilot` checkout retains its
unrelated `VehicleIMU.cpp` modification and flightgear submodule change; it
was not modified or used for a build. In the new worktree, the base DDS YAML,
generator, template and `EstimatorStatus.msg` still match their previously
sealed SHA-256 values. The one-topic candidate has **not** been copied into
this worktree. All 29 submodules are currently uninitialized there, including
the pinned `Micro-XRCE-DDS-Client` at `711aef423edd1820347b866d1e4164832df35d04`.
Missing submodules are a source-preparation task, not a reason to build from
the dirty original tree or fetch unrecorded revisions.

The installed WSL systemd user scope accepted `MemoryMax=4G` and
`CPUQuota=100%`. A short process inside that scope observed cgroup-v2
`memory.max=4294967296` and `cpu.max=100000 100000`, confirming enforcement
for this harmless probe. The first command combined `--scope` with `--wait`
and was correctly rejected by `systemd-run`; its failure log is retained.
The corrected accepted command and in-scope value check are separate records.
This does not prove a PX4 build can finish within the cap.

The frozen [design](superpowers/specs/2026-10-12-px4-estimator-status-firmware-design.md)
and [plan](superpowers/plans/2026-10-12-px4-estimator-status-firmware.md)
require at least 4 GiB free on both Windows and WSL, 15 GiB free disk, no
competing heavy process, one build job and a 90-minute wall limit. The
admission snapshot at 2026-10-12 02:21 UTC showed only **2.036 GiB** free on
Windows, while WSL showed about 6.8 GiB available and the destination disk
about 949 GiB available. No competing PX4/Gazebo/OpenVINS/test process was
found at that snapshot. The Windows memory gate therefore refused dispatch:
`build_dispatched=false`. No PX4, Gazebo, Agent, ROS collector, model training
or simulator was started, and no status-capable firmware binary exists yet.

The local evidence directory `results/px4-status-firmware-preflight-dev-1701`
contains the original failure, corrected cgroup probes, worktree/source and
submodule listings, resource snapshots, and the explicit admission refusal.
Its one-shot evidence archive and member hashes are verified separately.
The next work is bounded source/submodule preparation and RED/GREEN refusal
tests; an actual build waits for the unchanged resource admission. The later
unarmed live study still needs PX4/Agent/GID/ULog identity, causal clocks,
loss, rate and RTF evidence before status can affect capture eligibility.
