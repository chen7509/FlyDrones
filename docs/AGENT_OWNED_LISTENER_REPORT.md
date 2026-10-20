# 固定 XRCE Agent 的受管 UDP 监听（2026-10-12）

固定 Micro XRCE-DDS Agent v2.4.3 已在 Ubuntu WSL **独立启动并受管退出**。第二次运行的二进制 SHA-256 为 `ded56cf545394670effaf112c642d62e8dd0e7145e53a6c9b0593014b721fcfe`；`ss -H -lunp` 将 `0.0.0.0:18888` 归属到本次 Agent PID 27297。进程组经 TERM 清理，没有 SIGKILL；reap 后没有执行中的组成员，18888 监听消失。本阶段没有启动 PX4、Gazebo、OpenVINS、训练或 ROS，也没有发送 XRCE 数据包。

设计和计划见 [spec](superpowers/specs/2026-10-12-agent-owned-listener-design.md) 与 [plan](superpowers/plans/2026-10-12-agent-owned-listener.md)。复用封存的 Agent runtime bundle，而非运行 PATH 中的任意同名程序；束包 SHA-256 `4a5a104380bd320f87a3e1df1db4007287a4be4102d8ac511187ce69dd55596b`。上游固定 v2.4.3/commit `73622810d984349b80bbac0ef55fc0b694d62222`，Apache-2.0，选择和维护边界见 [source readiness](PX4_AGENT_V243_SOURCE_READINESS_REPORT.md)。读取上游 README 的 UDPv4 独立执行接口及 `ArgumentParser.hpp` 必需的 `-p` 参数；继续使用项目已验证的受管进程组清理，未引入新依赖。现有约 2.3 GiB 宿主空闲内存仍不足先前声明的 4 GiB 全模型/物理试验门槛，因此本试验只运行 Agent。

首次输出目录 `results/agent-owned-listener-dev-1701` **失败并保留**：Agent 已真实监听且完成清理，但诊断器错误要求 `ss -H -u` 输出含 `udp` Netid 列，实际输出省略此列。新增真实行形状的解析测试并修正后，在独立目录 `results/agent-owned-listener-dev-1701-v2` 重试通过。两次原始 `ss`、Agent stdout/stderr、进程组事件和结果均未覆盖；首次失败不被改写为通过。8 项解析测试与相邻进程组回归共 34 项通过，改动 Ruff 和 diff-check 通过。

**已验证：** 当前固定 Agent 可独立打开 18888 UDP 监听、套接字 PID 归属及原 owned group 正常清理。**仅实现：** 可重复的 Agent-only 诊断工具。**未测试：** PX4 v2 XRCE client 握手、DDS 主题/CDR、进程与发布者身份关联、EKF2 状态、已标定相机或 VIO 输入、完整果蝇训练与闭环飞行。**仍失败：** 既有 v10 首次 TIMESYNC 2 秒拒绝、五机相机 0.873 RTF < 0.95。下一步是在原 25 秒未解锁物理研究的资源门槛满足后，将固定 Agent 作为受管进程接入 PX4，记录会话/ULog/DDS 样本的同源证据；在此之前不能把监听成功称为数据来源合格或放行融合。
