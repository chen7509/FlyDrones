# 固定 XRCE Agent 接入未解锁采集流程：实现与独立运行阶段（2026-10-12）

**已将固定 Agent 作为 opt-in 受管资源接入原单机采集代码；实际 PX4↔Agent/DDS 闭环尚未运行。** 新 `--agent-runtime-config` 只接受固定 v2.4.3 二进制、封存 bundle、精确 13 个库别名/文件与 UDP 18888。配置进入实际执行声明；运行时资源清单必须在原有物理/估计器初始化前包含配置、bundle、二进制和每个库路径。每次运行前重新核对文件身份，不靠 PATH 中同名程序或已存在的外部监听。

Agent 在 PX4 spawn 之前建立新 POSIX 进程会话，5 秒内要求 `ss` 把 18888 套接字指向本次 PID；采集循环检查进程身份、存活和有界套接字观测，读线线程也拒绝已退出的 Agent。既有 PX4 停机优先于 Agent 停机；每次保留 stdout/stderr、socket 行、进程组信号/扫描、退出码和端口释放记录。未知或错误归属、多个监听、文件漂移、超时、进程退出和清理失败均不能获得来源资格。旧 capture 配置不指定 Agent 时保持原路径，`launch.json` 对新配置只写“请求运行”、不预先冒称已启动。无 ODOMETRY 发布、EKF2 注入、解锁或动作目标。

[设计](superpowers/specs/2026-10-12-owned-agent-capture-design.md)和[计划](superpowers/plans/2026-10-12-owned-agent-capture.md)沿用 [PX4 v1.17 uXRCE-DDS 官方说明](https://docs.px4.io/v1.17/en/middleware/uxrce_dds)、固定 [eProsima Agent v2.4.3](https://github.com/eProsima/Micro-XRCE-DDS-Agent/tree/v2.4.3) 源码（Apache-2.0，commit `73622810d984349b80bbac0ef55fc0b694d62222`）与本仓库[构建审计](AGENT_OFFLINE_BUILD_REPORT.md)。固定 v2 的后续维护、跨主机动态库可用性和资源占用没有由本试验证明；不采用最新 v3 代替 PX4 v2 客户端。实现复用现有 `CaptureJournal`、`RuntimeBinding` 和 `GroupEvidence`，不引入新依赖。

固定文件诊断在 WSL 中针对真实解包运行包验证 16 个选择路径：声明、bundle、二进制和 13 个库名。首次因手录 `libmicroxrcedds_agent` 哈希不符正确拒绝；从原封存逐库 SHA 修正后通过，首次失败不回填。第一次普通进程夹具因缺 `PYTHONPATH=src` 在导入阶段失败；改正环境后在新目录启动真实 Agent，第二次用最终代码在独立 `agent-only-v2` 目录再次成功：PID 33415，2 次套接字检查，TERM 后无运行组成员、无 SIGKILL、端口已释放。另以真实 Agent 注入错误的 PID 观测，`agent-wrong-owner-v1` 记录 `capture_failed`，仍完成 owned group 清理并释放 18888，PX4 未启动。该注入不证明 PX4/DDS 身份，只证明失败拒绝和清理边界。

先在缺实现时观察测试导入/契约 RED；后续独立复核发现多监听被误当“暂未出现”，以及组清理异常时主进程可能滞留，均加入反例并修复。最终相关采集契约、启动运行器、线协议、前置资源、受管进程组及 Agent 测试 **163 passed、2 skipped**；改动 Ruff 与 `git diff --check` 通过。两个跳过属于本机 Windows/POSIX 能力边界，不计作通过。测试结果是合成/固定输入；完整 25 秒 PX4/Gazebo 物理回合尚未执行。

| 范围 | 当前结论 |
| --- | --- |
| 已验证 | 固定文件身份、Agent-only 实际进程/端口/清理、错误 PID 拒绝、合成采集顺序及旧模式回归。 |
| 仅实现 | Agent 接入真实 capture 的 opt-in 执行与资源绑定；尚无同回合 PX4/Agent/DDS 现场证据。 |
| 未测试 | PX4 v2 XRCE 会话、ROS DDS/GID 与 ULog 同源、时钟/重置、已标定相机来源、VIO→EKF2 接受、飞行与集群。 |
| 仍失败 | v10 首次 TIMESYNC 的 2 秒拒绝；五机相机 0.873 RTF 低于 0.95；既有首次夹具与哈希配置失误原样记录。 |

当前宿主空闲内存约 2.6 GiB（运行前快照），低于原 4 GiB 全模型/物理探测门槛，没有启动 PX4/Gazebo。下一阶段必须生成新的事前冻结 study ID、含 Agent 角色与全部已选文件的新 runtime binding，复核端口/内存/并行进程后才做一次未解锁单机物理运行，连同 PX4、Agent、DDS/CDR、ULog、传感器/相机时钟和失败轨迹审计。单次启动成功不能单独宣称 DDS 来源、EKF2 融合或果蝇策略通过。
