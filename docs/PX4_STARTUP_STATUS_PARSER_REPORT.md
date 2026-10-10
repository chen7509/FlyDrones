# 固定 PX4 启动状态解析：离线阶段（2026-10-10）

**仅实现并验证了 `mavlink status` 关键身份字段的严格离线解析；尚未连接受管 PX4、改变启动顺序或重跑物理。** 这是 v10 单次物理失败后两阶段启动门禁计划的第一步，不能把解析器测试当成新的 TIMESYNC、VIO 或 EKF2 证据。v10 的 3 毫秒失败和全部旧证据原样保留。

固定 PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` 的 `px4-rc.gzsim` 在检测 Gazebo 世界之前不会继续，而 `rcS` 后续才 source `px4-rc.mavlink` 建立 Onboard UDP 链路。`Mavlink::get_status_all_instances()` 返回每个实例的独立区块，若无实例返回非零。由此，已能连上的 PX4 UNIX 命令套接字并不证明 UDP 14588→14548 的 Onboard 链路已经存在。固定源码、SHA-256、BSD-3-Clause 许可、维护时间和官方文档列在[规格](superpowers/specs/2026-10-10-px4-startup-phase-gate-design.md)中；安装 checkout 有无关改动，不声称整树洁净或源码与二进制完全等价。

新 `parse_mavlink_status()` 只接收有界 ASCII 原始 stdout 和严格整数退出码。退出码 1 且空输出仅表示 `no-instances` 待就绪；退出码 0 时，逐个区块检查连续的实例号、恰好一个 `mode` 与 `transport` 字段，且同一区块的 Onboard UDP 本地端口 14588 和远端端口 14548 必须同时匹配。错误端口、跨区块拼接、重复、截断、NUL 尾部、非 ASCII、异常退出与超限均拒绝。解析成功仍返回 `authority=false`、`fusion_qualified=false`；它没有套接字、进程、日志或飞控副作用。

测试先在缺模块时收集失败（`ModuleNotFoundError`，不是行为断言 RED），实现后边界用例通过。首次 GREEN 命令因 32769 字节参数自动测试 ID 在 Windows 上过长而在 pytest setup 阶段报错；缩短测试 ID 后，复核发现非目标实例的畸形 UDP 字段仍可被略过，新增反例先实际失败再修复为整条响应拒绝。最终 **20 项解析用例通过**；与现有 listener/启动诊断/runner 的相邻测试合计 **77 passed、1 skipped**，改动文件 Ruff 和 `git diff --check` 通过。该固定输出是源码格式构造，未声称从真实 PX4 `mavlink status` 捕获。仍需真实 owned socket、原文/退出码、日志首次可见性、进程身份、有限启动上限与原 2 秒/8 秒门槛的端到端验证。

下一步按[计划](superpowers/plans/2026-10-10-px4-startup-phase-gate.md)实现有界的受管只读状态探测和 startup→cold 两阶段切换，并先在普通进程与固定输入上做故障矩阵。任何新物理回合必须使用新的事前冻结研究 ID、检查资源且只运行一次；25 秒、1 毫秒物理、250 Hz IMU、10 Hz 160×120 RGB-D、未解锁门禁和全部原安全阈值不变。已有五机 0.873 RTF < 0.95、硬件/原生 Linux/实飞缺口不受本解析器影响。
