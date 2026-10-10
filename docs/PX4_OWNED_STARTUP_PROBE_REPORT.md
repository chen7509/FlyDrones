# PX4 启动只读探针阶段（2026-10-10）

**已实现并在普通进程夹具中验证受管 AF_UNIX `mavlink status` 查询；没有接入 PX4 捕获流程，也没有启动新的物理仿真。** 本阶段属于[启动两阶段规格](superpowers/specs/2026-10-10-px4-startup-phase-gate-design.md)的查询适配器部分。v10 在 3 毫秒模拟时间因原 2 秒进度门槛拒绝的失败及其证据保留，不能由此阶段改写。

固定 PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` 的 [daemon server](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/platforms/posix/src/px4/common/px4_daemon/server.cpp) 在命令输出末尾写入两字节 `{0, retval}`；本适配器只发送 `mavlink status\0`，保留全部原始输出、两字节尾标和退出码。空输出且退出码 1 是 `no-instances` 待就绪；完整输出且退出码 0 仍需通过上一阶段的严格同实例 Onboard UDP 14588→14548 解析器。多余尾标、截断、其他退出码、异常状态文本均拒绝。选择现有 owned socket/SO_PEERCRED 检查，是为了复用受管进程身份，不通过心跳猜测具体 PX4 命令实例。固定 PX4 许可为 BSD-3-Clause；本次没有更新上游版本或更改飞控参数。

每次查询用原始单调时钟限制在 2 秒以内，并在连接、发送、接收、EOF 前后核对进程和 peer。非阻塞部分发送与分段回复被记录；超时、时钟回退、身份变化、日志写入或关闭失败会锁定拒绝。所有成功与待就绪结果都保持 `authority=false`、`fusion_qualified=false`。探针没有 TIMESYNC、ODOMETRY、姿态/速度设定值或网络 MAVLink 发送能力。其事件日志是普通 flush 级证据，不是 fsync 或实时无阻塞保证；连接和文件日志操作仍需外部 supervisor 的总时限。

测试先因缺实现而失败；补入最小类后，测试在预期的构造参数行为上 RED，随后 12 项通过。复核又发现发送系统调用成功、随后读取时钟异常时会丢失返回事件；新增反例实际 RED，再补为先记系统调用结果和时钟错误后拒绝。最终相邻测试 **119 passed**、改动 Ruff 与 diff-check 通过。此前完整套件在设置项目 `src` 路径后 **4369 passed、37 skipped、4 warnings**；这次末尾的返回事件修复之后重跑了受影响的 119 项，而没有把更早的完整结果冒称为修复后完整重跑。最初未设置 `PYTHONPATH` 的完整测试在收集时因 `flydrones.benchmark` 导入失败，该环境错误也保留。WSL 中一个普通受管 Python 子进程用真实 AF_UNIX/SO_PEERCRED 发送拆分回复，得到 `phase=ready`、退出码 0、事件 9 条并正常退出；这是普通进程夹具，**不是 PX4 实测**。

本阶段尚未实现源文件身份绑定的 PX4 成功启动标记、spawn 锚定的有限 startup phase、从 startup 到原 8 秒/2 秒冷 TIMESYNC 的切换，也未验证当前 25 秒、1 毫秒物理、250 Hz IMU、10 Hz 相机回合。下一步先写源日志/阶段故障测试，再接入捕获回调且保持原安全门槛；只有资源和启动证据齐备，才以新研究 ID 运行一次未解锁物理诊断。此次空闲内存核查曾仅约 416 MiB，故没有竞争 PX4/Gazebo。五机相机 0.873 RTF 低于 0.95 的旧失败仍然有效。
