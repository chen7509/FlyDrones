# EGO 原始消息与规划诊断的离线关联

本阶段把已存在的桥接 CDR 日志接到固定 EGO 规划器和轨迹服务的离线诊断关联器。它核对桥接器保存的 odometry、depth、camera-pose 发布字节摘要及收到的 PositionCommand 字节摘要，与诊断记录中的摘要、**日志自报的**采样时间、会话和进程身份是否一致。接口先调用日志内部完整性审计，要求每次已记录的发布意图都有返回记录、命令接收有解码记录；重复的输入摘要及时间导致歧义时拒绝。命令元数据中的 `ready`、轨迹编号与选中规划记录也必须一致。

来源始终保留桥接日志的 `unattested_socket` / `unattested_ego_server` 和 `truth_used=unknown`。投影只是离线核对内部接口，不把这些值改写为 `px4_ekf2`、已标定相机或已核验 EGO 服务。独立复核发现日志审计只核对不透明 CDR 字节摘要，**没有独立解码字节中的时间戳、轨迹号与 ready 状态**；合成测试本身甚至使用了任意字节。因此输出仅给 `digest_identity_candidate=true`，保持 `identity_match=false`、`stamp_binding_verified=false`、`cdr_payload_fields_verified=false`，并使 `runtime_source_verified`、`clock_domain_verified`、`planner_numerical_parity_verified` 和 `teacher_qualified` 为 false。`cdr_journal_internal_complete=true` 仅指已记录行的字节、顺序和闭合条件通过；离线审计无法发现一个完整发布对连同行号一起被删去。它也不证明 DDS 交付、规划器消费或实际 ROS 类型支持。候选模式保留原公开接口，未审计的合成记录不能选择 CDR 模式。

这延续固定上游 [EGO-Swarm `23a8d5a`](https://github.com/ZJU-FAST-Lab/ego-planner-swarm/tree/23a8d5a191711dd65633df689bd00f55d4dea8f9) GPL-3.0 的只读诊断路线，以及 ROS 2 Humble 官方 [`rclpy` 序列化源码](https://github.com/ros2/rclpy/blob/humble/rclpy/rclpy/serialization.py)。上游在先前审计时未归档、最后记录推送为 2025-03-08，不能因此断言当前仍活跃。此阶段未增依赖、未改变 EGO 规划算法、未编译或运行带插桩的 ROS 规划器；平台资源门槛下也未启动 PX4/Gazebo、Docker 或训练。原始字节日志增加的运行时负载仍需将来在单独开发场景测量。

新用例先因关联模块不存在而 RED；随后针对复核发现的资格误报和公开入口绕过又观察到 2 个 RED。测试覆盖摘要候选、重复深度、缺发布回执、来源伪装、命令未就绪/轨迹号或时间错配、字节篡改、跨会话拒绝。最终六个 EGO 相邻测试文件合计 **127 passed**；改动 Python 文件 Ruff 与 `git diff --check` 通过。运行输出及独立复核意见保存于 `results/ego-cdr-diagnostic-join-dev-1701/`。复核修正后，独立再审未发现当前收窄范围内余留的 Critical/Important。这些均是合成 CDR 和诊断记录测试，不是实际 ROS 网络、PX4 EKF2 源、真实相机或新训练语料证据。

状态：**已验证**日志已记录行的内部一致性与该合成摘要匹配故障矩阵；**仅实现**桥接日志到规划诊断的无来源资格候选投影；**未测试**真实 patched EGO ROS 二进制/type-support、独立 CDR 字段解码、DDS 到达、`/clock` 绑定、与原版数值等价、非真值 PX4/已标定相机生产端及完整果蝇训练；**仍失败或阻碍**的历史 PX4 首次 2 秒 TIMESYNC、五机相机 0.873 RTF 低于 0.95 以及旧任务失败全部保留。下一门槛是隔离构建固定 EGO patch，核对 CDR 跨语言字节和字段一致及相同开发输入下的轨迹等价；再接入有 ULog 与相机标定证据的真实未解锁生产端。现阶段不能写入合格教师标签或宣称公平物理对照完成。
