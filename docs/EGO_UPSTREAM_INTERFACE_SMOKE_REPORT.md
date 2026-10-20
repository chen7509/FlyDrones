# 固定 EGO-Swarm 镜像的 ROS 接口启动核查（2026-10-09）

**结果：固定上游规划器与轨迹服务在 Docker 内启动，现有桥接的四个关键话题名称与消息类型在实际 ROS 图中出现；没有生成教师轨迹，也没有运行 PX4/Gazebo 对照。** 主机可用内存检查前后约 1,167/945 MiB，故未同时启动物理仿真或完整连接组。Docker 已退出本次临时容器，`docker ps` 为空。

固定镜像 `fly-ego-benchmark:humble` 的 ID 为 `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`；镜像身份和内部 checkout 的既有核查见 [EGO_TEACHER_IMAGE_INSPECTION_REPORT.md](EGO_TEACHER_IMAGE_INSPECTION_REPORT.md)。本次从上游固定提交 `23a8d5a191711dd65633df689bd00f55d4dea8f9` 的 GitHub Git blob API 读取四个源码文件，保存 blob ID、字节数和 SHA-256。`grid_map.cpp` 在收到 `TYPE_32FC1` 时转换为 `CV_16UC1` 并使用 `k_depth_scaling_factor_`，所以现有桥接发布 `32FC1` 本身不是编码不匹配；这只是源码契约核对，未证明实际深度帧已进入地图。`traj_server.cpp` 发布绝对 `/position_cmd`；现有 launch 使用相对 `position_cmd` 重映射。受限容器中的真实 ROS 图显示它解析为 `/benchmark/ego/position_cmd`，无需根据源码表象改动重映射。

只运行 `ego.launch.py`，限制 768 MiB、2 CPU、128 进程和独立 `ROS_DOMAIN_ID=198`，挂载桥接目录只读。实际节点为 `/drone_0_ego_planner_node` 与 `/drone_0_traj_server`；话题包含 `/benchmark/ego/odom` (`nav_msgs/Odometry`)、`/benchmark/ego/camera_pose` (`geometry_msgs/PoseStamped`)、`/benchmark/ego/depth` (`sensor_msgs/Image`) 和 `/benchmark/ego/position_cmd` (`quadrotor_msgs/PositionCommand`)。轨迹服务报告 ready；规划 FSM 仍是 `INIT`，明确显示没有 odom、正在等触发。话题存在不等于发送过观测、地图完成、轨迹有效或公平对照通过。`run_batch.py` 的正式工作流为每个 EGO 回合单独启动并停止容器；本次没有运行该工作流。

原始只读源码摘要、实际 ROS 图与启动日志在 `results/ego-upstream-source-audit-dev-1701/`。`validate.py` 对固定提交、源码转换、四个话题、两个节点和 ready 日志进行离线断言；`validation.json` 分别标记 `interface_startup_verified=true`、`trajectory_generated=false`、`px4_gazebo_run=false`、`teacher_fairness_qualified=false`。它不声称证明 publisher/subscriber 的数据流或估计器输入来源。

下一步仍是一个全新开发回合的真实上游教师轨迹采集，使用部署可见状态与相机数据、冻结镜像和场景、保留全部失败，然后才谈正式语料与完整 MaleCNS 训练。单机 VIO→EKF2 与安全门禁未因本次启动核查获得额外资格；v7 未解锁物理诊断输入保持封存且未执行。不能以 Docker 已启动推断物理仿真已通过。
