# XRCE 后续采集的受管 Docker daemon 身份门禁

本阶段补上合成 XRCE 类型化试验独立复核发现的**前瞻性清理归属缺口**。新只读模块经同一 `wsl -d Ubuntu -- docker` 命令入口检查 daemon ID、context 与精确受管容器名，要求启动前与清理后身份一致、所有查询成功且受管名称缺席；故障即拒绝，并随异常返回已执行查询供未来执行器保留失败。它不启动或删除容器，不修改 PX4、Gazebo、Agent 或 ROS，且不检查或终止无关容器。

2026-10-12 的一次只读双探测记录于 `results/xrce-owned-daemon-identity-dev-1701`：两次均为 daemon `6629cb9a-7501-4f8c-8512-b36360787f36`、WSL context `default`，试验名称 `flydrones-px4-source-1701` 未出现。`intervening_capture_verified=false`、`px4_source_authenticated=false`、`fusion_qualified=false` 明确保留。它**不能追认**历史 v8–v10 的 Windows `docker` 检查与 WSL `docker run` 是否在当时使用同一 daemon，也不能证明两次只读查询之间发生过任何运行。

首次环境检查约 2.29 GiB 空闲，后续记录为 1,423,437,824 字节；均低于原 4 GiB 物理启动门槛。当前另有 12 个无关容器。没有启动物理仿真或训练，也没有操作这些容器。现有 v10 首次 TIMESYNC 两秒失败及五机相机 0.873 RTF 小于 0.95 的历史门槛仍然有效。

测试先因模块不存在 RED；首轮实现后 5/7 通过，两个测试的预期值/正则过窄而失败并保留，修正后 7/7 通过。独立只读复核没有 Critical/Important，指出容器名中点号须转义和 `ps` 退出码须严格为整数；新增三个反例先 RED，再修正到 10/10 通过。相邻 XRCE 与类型化收集器回归随后重跑，最终 **69 通过、1 跳过**；跳过是固定 WSL 客户端编译 smoke 未在本次环境标志下运行，不能计入通过。改动文件 Ruff 通过。修正后的点号/退出码规则只经合成测试，未把首次真实只读结果冒称为修正后重新采集。该门禁仅为将来真实未解锁 PX4→Agent→ROS 同回合采集的必要条件之一；还需独立的 PX4 进程/客户端会话与套接字归属、Agent 实际实体、ROS GID/CDR、同回合 ULog（旧两份 ULog 均无 `vehicle_odometry`）、时钟/reset、相机标定、EKF2 健康及受管清理证据。即便将来 daemon 门禁通过，也不得据此直接开放训练、融合、解锁或多机扩展。

固定 PX4 `d6f12ad`、Agent v2.4.3、Client `d44dc3f`、ROS Humble/`px4_msgs` 的版本、许可证、维护边界与适配选择沿用 [合成 XRCE 报告](XRCE_TYPED_ODOMETRY_DIAGNOSTIC_REPORT.md) 及其封存上游引用。此模块复用已有 Docker CLI，不引入依赖；其资源成本是三次短时只读 CLI 查询各两轮。设计与执行约束见 [spec](superpowers/specs/2026-10-12-xrce-owned-daemon-identity-design.md) 和 [plan](superpowers/plans/2026-10-12-xrce-owned-daemon-identity.md)。

| 范围 | 结论 |
| --- | --- |
| 已验证 | 当前两次 WSL Docker daemon/context 相同、精确受管名缺席；合成拒绝矩阵和相邻回归。 |
| 仅实现 | 可供未来受管捕获调用的只读前后门禁；尚未集成到真实 PX4+ROS 同回合执行器。 |
| 未测试 | 真实 PX4 XRCE 发布来源、同回合 ULog/DDS 字段对照、相机/VIO→EKF2、受管运行后的 daemon 探测。 |
| 仍失败/不足 | v8–v10 历史 daemon 同一性未知；物理内存低于 4 GiB，12 个无关容器仍运行；历史 TIMESYNC 与五机容量门槛未过。 |
