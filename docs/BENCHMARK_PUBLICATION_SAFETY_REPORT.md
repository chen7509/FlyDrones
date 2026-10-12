# Benchmark 私有发布与失败传播保护（2026-10-12）

旧 benchmark 的 `_send_local_ned` 绕过公开 PX4 位置观察门禁，后台发送异常又被吞掉；停止等待可能被当作已经发送成功，随后继续推进物理。本阶段修复这些软件路径，保留原 LOCAL_NED、速度 m/s、航向角速度 rad/s、ignore mask 和配置限幅。没有运行 PX4/Gazebo、网络连接、训练、完整 MaleCNS 或硬件。

## 改动与原因

四维 SI 命令必须是有限、可用 float32 表达的数值；拒绝布尔、错维度、NaN、无穷与溢出。公共 shaping 校验上一状态和限制，稳定向量范数避免巨大有限向量溢出后变成悬停。数值／来源／发送失败锁存并通知等待者，记录首个错误；Facade 错误中止旧命令流，后续 advance/observe/restart 拒绝。没有通过旧归一化 BODY_NED API 改变控制尺度。

每次私有发送先调用实际 `MavlinkDrone.require_position_observation()`。来源回调、设定值、心跳读取和 LAND 由同一 MAVLink RLock 串行化。首个失败先锁存，再尝试 LAND；发送与降落错误分别保存，不以成功调用证明 LAND ACK 或已着陆。原控制记录序列保存失败记录，因此 episode 已有输出路径可保留原因。

后台异常不再变成成功 ACK。ACK 是本机发送调用返回，**不是 PX4 回执**；等待结束仍检查失败／停止／worker 存活及原 0.5 秒本机期限。最后期限检查保守拒绝已及时发送但等待者太晚恢复的情况。动态障碍准备可能阻塞，准备结束后再次检查，然后才允许同步物理步进入；步中已发生的异常保留该步记录并拒绝下一步。

独立复核发现三处缺口：晚到 ACK 被接受、准备期间失败后仍启动物理、close 的 timed join 后 LAND 未串行化。三个确定性反例实际 RED 后全部 GREEN。close 的 LAND 使用有界锁；取不到锁记录 unavailable 并跳过 LAND／hook 移除，不谎称所有回调结束或降落完成。一个已经允许进入的同步发送／物理步仍可能完成，不能把保护称为硬实时取消。

新增位置读取会过滤 HEARTBEAT。固定 pymavlink v2.4.49 的 `post_message` 在 `recv_match` 类型过滤前调用 `message_hooks`，因此复用官方解码 hook；只在启动 OFFBOARD 验证后安装，close 串行移除该 owned hook。同一个消息对象被 hook 与 drain 看见时不重复更新时间，绝不靠读取缓存刷新心跳。两项实际行为反例 RED→GREEN。没有创建第二个竞争读取器。

## 验证与证据

最终 `final-v2`：**221 passed**，其中本阶段31项。覆盖正常 SI/frame/mask、数值与源拒绝、失效／停止／缺 publisher／超时 ACK、线程错误传播、来源回调期间取消、物理准备／步中故障、cleanup 锁不可用、过滤心跳与无缓存续期，以及来源、相机、ULog、prelude、heading、采集输入邻近回归。改动 Python Ruff 和 diff-check 退出0，四份源码／测试运行前后 SHA 相同。没有重跑全库，不能外推整库 lint 或测试通过。

初始19失败／1 overflow warning、物理异常／重启2反例、独立复核3反例、hook2反例，以及中间38／166／170／73／124通过日志全部保留。最初 RED 是现场测试输出；原 gateway 的 Git 源码副本是事后导出，不能冒称运行前冻结。新增 cleanup 锁超时覆盖直接 GREEN，未声称新的 RED 修复。最终独立只读复核没有遗留 Critical/Important；其31项 fake 测试与主验证分开记录。

封存 `evidence/benchmark-publication-safety-dev-1701.zip` 与同名 SHA256 文件：研究源、版本、原始失败日志、最终源码／测试／规格／计划／报告、复核与成员 SHA／CRC。最终验证器在 `results/benchmark-publication-safety-dev-1701/final-v2/execution.json` 记录准确命令和前后 SHA。

## 资格与剩余缺口

| 分类 | 结论 |
|---|---|
| 已验证 | 假连接、确定性时钟与有界 Python 线程下的拒绝、失败传播、邻近回归、源码 SHA、独立复核 |
| 仅实现 | benchmark 私有发送使用已有位置观察门禁；本机发送 ACK、串行化、失效 LAND 尝试与解码心跳 hook |
| 未测试 | 真实物理使用新路径、pymavlink 安装版本等价、源生成／网络到达与积压、EKF2健康／重置、真实标定 VIO/相机、LAND ACK／落地、所有回调清理 |
| 保留失败 | 所有本轮 RED；既有 RX 首包无 ancillary、NS metadata、首2秒 TIMESYNC、五机 0.873 RTF < 0.95 与物理历史失败 |

来源仍是旧 **0.5 秒解码推进观察策略**，递增的延迟积压仍可通过；心跳记录是解码时的仿真时刻，不是源生成或内核到达。慢速／暂停仿真造成软件门禁拒绝不能当作果蝇策略失败。backend 的 `odometry_source` 与 `camera_pose_source` 仍明确为 Gazebo model truth，未获得真实 VIO／公平 teacher／训练资格。不能把本阶段称为完整安全闭环。

本轮宿主可用内存约 2.3 GiB，低于 EGO 2500 MiB 与物理／完整 MaleCNS 4 GiB 原门槛；Docker 无运行容器。WSL 只读进程记录含无关 sandbox／defunct 进程，未终止它们，也未以名称或列表称所有进程组已清空。资源记录只是快照；没有降低负载或启动门槛。

下一步：继续源样本时间／真实接收／积压与 EKF2 状态的 provenance 契约，独立声明后验证；资源不足时完成学习／推理／公平基线中不依赖物理的工作。EGO teacher=false、规划器完整构建未完成，masked MaleCNS 工件未训练；单机→5→20、硬件/HITL/实飞仍各有门槛。不要求安装原生 Linux，完整用户目标仍未完成。

## 上游与选择

沿用固定 PX4 d6f12ad（BSD3）、pymavlink2.4.49（LGPL3+）和已有协议。新增固定源 `mavutil.py` SHA `da6f010fed963a63d4b819e734a938c0db84293ccf12e6a427882bfd19b8593b`；维护活跃度／安装等价未新证明。成本是数值检查、现有遥测轮询与一个同步 decode hook，没有新依赖、估计器或相机负载。缓存续期、第二读取器和归一化 BODY_NED 改道均拒绝。

[固定 pymavlink 源码](https://github.com/ArduPilot/pymavlink/blob/v2.4.49/mavutil.py)、[MAVLink SI 消息](https://mavlink.io/en/messages/common.html#SET_POSITION_TARGET_LOCAL_NED)、[PX4 Offboard](https://docs.px4.io/main/en/flight_modes/offboard)用于接口依据；首次无 v 前缀源 URL 404 保留在工具记录，随后正确 tag 正常 TLS 下载。没有改变算法；VIO 论文不能证明这个协议发布保护的物理安全。
