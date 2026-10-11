# EGO causal diagnostic clock candidate v2

Date: 2026-10-11. This version preserves the immutable v1 patch and evidence while adding event-time fields needed for a later bridge/source join. It remains a **static candidate**, not a qualified EGO teacher or a compiled planner.

## Change and rationale

The v1 patch tied completed occupancy mutations and a published B-spline to one planner process and session, but lacked the actual node-clock instants of those two events. `Bspline.start_time` describes a trajectory, not the time that the map update or plan publication completed; the trajectory server's command stamp is another clock. The versioned `tools/benchmark/ego_causal_readonly_v2.patch` therefore adds `map_apply_node_ns` after completed depth projection/raycast, `plan_publish_node_ns` after B-spline publication, node-clock values for depth/pose, odometry and cloud callbacks, and a `std::chrono::steady_clock` value on every diagnostic JSONL event. The steady value supports later arrival/processing analysis but is not a PX4 or camera timestamp.

The node-clock fields are **not yet certified simulation timestamps**. The fixed launch requests `use_sim_time=true`, but a future runtime must bind the actual launch, `/clock` stream and session before interpreting them as simulation time. The bridge still needs to journal exact serialized ROS image, pose, odometry and received command bytes. Its observation sequence and the planner's depth-receive sequence are independent; neither can be substituted for the other. The fixed offline `EgoCausalJoin` intentionally requires a conservative same-observation match and remains `teacher_qualified=false`.

## Evidence status

- `build_patch.py` checked the same eight fixed upstream Git blobs and generated a new 10-file patch. The v2 SHA-256 is recorded in `patch-manifest.json`; its predecessor is v1 SHA-256 `cb09eb97ede4d79a90b2ddef5ed8e6448a7ec67b11f037c18d8d490bbbd9f5b6`.
- The v2 patch passed `git apply --check`, application to an isolated copy and exact byte comparison of all 10 resulting files. The original pinned EGO checkout was not edited.
- Three small source-contract checks passed. Before the edit, the missing map field and missing steady-clock field each produced a failing check; those observed failures are not a ROS execution test.
- Native C++ writer compilation, ROS package/type-support build, patched binary identity, actual `/clock` binding, server/bridge hash parity, and patched-versus-unpatched trajectory numerical parity are **not yet verified**. No teacher label, physical baseline comparison, training data or safety qualification is granted.

Host free RAM fell as low as roughly 0.33 GiB while an unrelated regression process remained live. A new Docker ROS build, native compile or PX4/Gazebo run was not started under that constraint. The next resource-gated step is to run the native writer test, build this exact patch in an isolated pinned Humble environment, freeze its dynamic dependencies/type support and compare trajectories on identical development input. Only a separate source-attested bridge and owned capture can later test online causality. All prior failed TIMESYNC, WSL2 capacity and old EGO evidence remain separate.
