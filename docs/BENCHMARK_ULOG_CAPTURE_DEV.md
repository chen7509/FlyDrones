# Fly/EGO 开发回合 ULog 采集（2026-10-01）

本分支在历史对照归档 `2022e6c` 之后新增证据采集；**没有重跑或修改已冻结的 20 个正式世界**。根据 [PX4 上游日志说明](https://docs.px4.io/main/en/dev_log/logging)，PX4 默认在解锁后启动 ULog。新回合使用独立 PX4 runtime，进程退出后从该 runtime 复制全部 `.ulg`，记录大小、SHA-256 与文件头；无日志、头无效或复制失败使回合退出码为 2，同时保留任务终局和失败证据。这个门槛只证明日志文件被保存，不代替 EKF2、安全控制和完整 ULog 语义检查。

单机接入验证使用既有开发世界 `1701`、完整果蝇原始版与 PX4/Gazebo；没有使用正式测试世界。回合任务终局是 **out_of_bounds**，仿真时间 20.9 s、墙钟 275.81 s，因此不能作为策略成功或实时性通过。采集到的 ULog 为 14,219,204 字节，SHA-256 `81de68ef3db6108b1a0860826bd7eca45de8638a7b3f9f3d7a41ab00e6a4b94b`。`pyulog` 能解析 88 个数据集，其中 `estimator_status` 4,732 条、`vehicle_local_position` 5,914 条、`trajectory_setpoint` 238 条、`vehicle_command_ack` 5 条；`vehicle_status` 有 OFFBOARD（14）67 条、AUTO_LOITER（4）51 条，`failsafe` 样本为 0。`estimator_status_flags` 中 GNSS 位置融合有 52 个样本，外部视觉位置融合为 0，符合本回合**没有真实 VIO** 的范围。

原始开发回合的 12 个文件（含 ULog、结果、逐步轨迹、世界和 PX4 日志）在 `evidence/fly-ego-ulog-dev-1701.zip`，逐文件 SHA-256 在同名 `.sha256.json`；ZIP SHA-256 为 `840dc43dc9bfe0e8bf2c92120882539f40de13ac0dea934ae809689d1301ecf7`。这次运行中结果 JSON 的旧字段 `evidence_accepted=true` 仅表示**ULog 复制及文件头门槛**；运行后代码已改用明确的 `px4_ulog_capture_accepted` 名称，避免误读为飞行安全通过。

版本限制：本次开发运行的 PX4 HEAD 为 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`、Gazebo Sim 为 8.15.0；PX4 工作树并不干净，`src/modules/sensors/vehicle_imu/VehicleIMU.cpp` 的运行时文件 SHA-256 为 `a73997eaf14a5c1b224dcb4f13648874a02863d63608c60b73d8d3dc01a983a1`，Gazebo 子模块含未跟踪的模型/世界文件。因此这次开发回合不能仅凭 PX4 提交号复现，也不能作为正式对照。EGO-Swarm 并未参与此回合。

本分支全套回归 292/292 通过；随后补充了正式报告的 ULog 哈希复核门槛，benchmark 针对性回归 81/81 和相关 Ruff 检查通过。新的正式报告会拒绝没有可复核 ULog 的回合，历史 60 回合仍保留在独立归档中作为有限的旧结果。开发回合退出后未见残留的该回合 PX4 或 Gazebo 进程。ULog 的完整语义与 EKF2/控制闭环仍需新的开发回合逐字段验收，本次仅完成主题存在性和基本状态核对。之后才能在新冻结配置下做未见场景对照。当前没有图像+IMU VIO、故障注入和稳定五机证据，不应推进 20/100 机。
