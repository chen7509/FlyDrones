# v10 在线接线单次物理诊断：启动阶段拒绝（2026-10-10）

**结论：v10 的唯一物理尝试失败，不具备在线接线、VIO、EKF2 或飞行性能资格。** 研究输入仍是事前封存的 `live-wire-dev-1701-v10`，研究清单 SHA-256 `2fb2a200a5a70a2f4ec4874f2e0ac3cb2275fbd2332607cfcbeac1177387be01`，启动诊断声明 SHA-256 `c554414ac0de5925ecbec1c0daeaf11f89866d3a4b04f2fd64161c7e9ce19718`。资源检查通过后只启动一次。`dispatch.json` 标记单次实际尝试，`completion.json` 记录 `physical_run=true`、capture/命令返回 2、`fusion_eligible=false`、资源清单为空。没有覆盖 v6、v7、v8、v9 或 v10 离线准备的历史结果。

PX4 命令套接字 `/tmp/px4-sock-8` 连接到了本次受管 PX4 进程。首次 `listener timesync_status -n 1` 的原始响应为 `never published\n`，随后没有完成首个 TIMESYNC 样本。冷启动状态机的 `empty_snapshot` 时间为 monotonic `109410991130575 ns`，`bootstrap progress timeout` 拒绝为 `109412992214730 ns`，相隔 **2.001 秒**。该 2 秒上限来自固定的进展看门狗，8 秒总就绪上限没有因此视为通过。期间 MAVLink interval baseline `get` 已发送，但没有确认；恢复检查也未证实。因此不能声称 TIMESYNC 收敛、间隔配置已恢复或安全地继续传输。

独立日志观察器首次看到 `Gazebo world is ready` 为 `109414186861418 ns`，比冷启动拒绝晚约 **1.195 秒**；首次看到 `[mavlink] mode: Onboard` 为 `109414858769006 ns`，晚约 **1.867 秒**。观察器开始到 Gazebo 就绪可见约 26.98 秒，但包括启动前准备，且时间戳是**日志首次可见**时间，不是 PX4 内部事件时间。这些数据支持“首次查询/2 秒进展门槛与本次 PX4 启动时序冲突”的诊断，不足以单独证明 PX4 或仿真引擎内部根因，也不能归因为果蝇学习策略。

仿真只推进 **3 毫秒**（`end_sim_ns=3000000`），远小于冻结的 25 秒。相机和 IMU 只有启动样本：源双路提交 2 条、原生估计器接受 1 条，没有可用视觉状态或轨迹精度结论。wire 分段日志保留 103 条，首轮 500 样本没有开始；`timesync_listener_complete=false`、`network_authorized=false`、`fusion=false`。失败被源健康门禁传播，后续输入被拒绝，没有发网络 ODOMETRY、EKF2 注入或解锁。有效 ULog 一份，SHA-256 `1f5cdded48e54633cbd28e454c8c94a7f4fd8cde6e321a1d64e37f4b0fb13644`；只读解析 `vehicle_status.arming_state` 唯一一条为 1（未解锁）。ULog 仅覆盖该短时失败，不是闭环证据。

受管 worker 返回 2。监督器的原进程组清理记录显示最终无执行成员、组消失、未发送 SIGKILL；新检查也未发现相关 PX4/Gazebo/OpenVINS 或运行中的 Docker 容器。清理资格仅覆盖原受管进程组，不能推断逃逸会话后代。运行时声明文件稳定、局部资源图通过，但本次失败太早，PX4 owned-map 阶段未完整覆盖，`runtime_mapping_coverage_verified=false`、`runtime_closure_qualified=false`。生产全量审计器正确在 `capture` 阶段以 `inconsistent capture status` 拒绝，不能将它当作一个完整合格回合。

原始 `study-v10` 目录的 184 个文件（包括 `activation-request`、`dispatch`、`completion`、启动观察、完整 `capture-v1`、wire 分段、ULog、逐进程监督记录和失败输出）封存在 `evidence/live-wire-v10-physical-attempt-dev-1701.zip`。包内 `SHA256-MANIFEST.json` 的逐文件长度/SHA-256 与 ZIP CRC 已重新读取验证；整包 SHA-256 为 `118df50f27466654579e717e8bc17e7d695e5687cc57ca14c9059ed2d0b3a5e3`，大小 1,232,803 字节。封包不改变原始结果；旧 v10 离线准备包另行保留。

下一依赖是独立设计启动阶段与在线运行阶段的时钟/健康门禁：研究固定 PX4 启动与 TIMESYNC 源码，明确何时才有资格启动首个 2 秒进展看门狗，同时保持有限启动上限和原 2 秒运行中失联拒绝，记录真实进程身份、日志可见性与首个有效样本。不得事后把本次失败算作通过，也不得简单延长原门槛或用旧帧补频。任何修正需新研究 ID、事前清单与故障测试；资源允许且无占用时再进行单次新物理诊断。与此并行，可继续不依赖物理资源的真实非真值 EKF2/相机/EGO 采集来源与完整果蝇模型工作。五机 0.873 RTF < 0.95 和硬件/原生 Linux/实飞缺口仍独立存在。
