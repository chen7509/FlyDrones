# 固定 EGO 教师输入因果来源审计（2026-10-10）

**结论：现有固定 EGO 输出可以按轨迹编号关联到规划轨迹，但不能按当前消息关联到生成该轨迹时实际消费的里程计和深度图。** 因此，桥接返回的 `reference.sim_ns`、v3 录制器的同时间戳检查、命令到达顺序、以及 `trajectory_id` 本身，都不能授权把某一条指令当作指定当前 RGB-D 帧的教师标签。这是固定源码路径的只读审计；没有运行新容器、估计器、PX4/Gazebo 或训练，也没有重分类旧正式对照。

## 来源与范围

上游固定为 [ZJU-FAST-Lab/ego-planner-swarm `23a8d5a`](https://github.com/ZJU-FAST-Lab/ego-planner-swarm/tree/23a8d5a191711dd65633df689bd00f55d4dea8f9)，GPL-3.0；检查时仓库未归档，GitHub 最近推送记录为 2025-03-08，不能据此保证当前有人维护。原镜像的算法、ROS 消息和控制参数均未改动。本次从 GitHub Git blob API 读取 FSM、地图、轨迹服务和两份 `.msg`；逐文件复算 Git blob SHA-1 和 SHA-256，前三个源码的 SHA-256 又与旧独立审计一致。独立复核指出仅按预设 blob ID 抓取不足以证明消息定义属于该提交；随后通过提交对象 → 根树 `fd31a990fe5ceaf586c96e4199c2284ec4c487a8` → 五条路径/类型/blob ID 逐项核对，结果记录为 `commit-tree-binding.json`。完整字节、路径、blob ID、行数和哈希见 `source-manifest.json`。另将[固定提交的 LICENSE](https://github.com/ZJU-FAST-Lab/ego-planner-swarm/blob/23a8d5a191711dd65633df689bd00f55d4dea8f9/LICENSE) 随源码快照保存并复算 Git blob ID。本机审计脚本验证固定副本及树绑定，产出 `causal-path-audit.json`；其布尔值严格限于所查路径，不是整个上游所有执行路径的动态证明。

上游 [EGO-Swarm 论文](https://arxiv.org/abs/2011.04183) 介绍异步集群规划；它解释为何要检查时序，但本文关于固定版本的结论以源码为准。官方 [ROS 2 Humble `Odometry.msg`](https://github.com/ros2/common_interfaces/blob/humble/nav_msgs/msg/Odometry.msg) 把 twist 定义在 `child_frame_id`，与当前桥接 `base_link` 标注下发送世界速度的数值约定不同。该版 FSM 在 `ego_replan_fsm.cpp:249-257` 直接把 twist 数值赋给世界速度变量，不执行旋转。对照可以明确采用“固定 EGO 世界速度输入”兼容约定，并在非零航向开发用例检验；不能把消息描述为标准 body-frame Odometry，也不能未经等价试验修改上游规划输入。

## 已核对的来源链

| 节点 | 固定源码证据 | 能证明的事 | 仍不能证明的事 |
| --- | --- | --- | --- |
| 状态输入 | `ego_replan_fsm.cpp:249-267` | FSM 读取位姿、速度、姿态 | 回调未把 `msg->header.stamp` 或输入序号保存到轨迹 |
| 视觉地图 | `grid_map.cpp:758-792` 和 `1045-1078`，再由 `709-756` 定时应用 | 图像/位姿回调设置待更新，后续定时器执行深度投影与占用图更新 | “收到图像”不等于“本次轨迹已使用该图像”；已应用的帧 ID 未随轨迹传递 |
| 规划输出 | `ego_replan_fsm.cpp:783-830` 与 `Bspline.msg` | 成功重规划发布 `start_time`、`traj_id` 和控制点 | 消息没有 odom 样本、图像或地图修订号 |
| 控制参考 | `traj_server.cpp:27-68`、`163-172`、`209-231` 与 `PositionCommand.msg` | 轨迹服务复制 `traj_id` 到命令，定时采样并打自己的时间戳 | 时间戳和轨迹号均未指明规划所消费的输入；编号还经 `int64 → int → uint32`，必须检查无损范围和别名 |

固定上游 [`traj_server.cpp`](https://github.com/ZJU-FAST-Lab/ego-planner-swarm/blob/23a8d5a191711dd65633df689bd00f55d4dea8f9/src/planner/plan_manage/src/traj_server.cpp) 每 10 毫秒发布轨迹采样；旧轨迹在新观测到达后仍可给出合法控制参考。它不应被误标为“新观测产生的新教师标签”。桥接的上一帧迟到命令修复只消除了读取下一包时一个明显的错配窗口，未建立地图与轨迹的因果链。

## 决策与下一门槛

选择 **独立版本的上游只读诊断插桩 + 桥接会话关联**，保持固定 EGO 规划算法不变。插桩应在规划使用状态和地图时记录真实里程计样本、已应用的深度/位姿帧及地图修订号，再以 run/session、轨迹编号和开始时间绑定到 `PositionCommand`。编号必须在目标 C++ `INT_MAX` 内为正数，原始 `int64`、中间 `int` 和输出 `uint32` 严格相等且会话内唯一；缩窄或重复导致的别名必须拒绝。对于积累的地图，记录输入历史窗口，不虚构只用当前单帧。任一来源缺失、乱序、跨 reset、相机未实际入图、旧轨迹或来源健康失败，教师标签资格为 false；普通 EGO 控制参考可另按原有安全监督规则评估。新插桩镜像需提交、补丁、消息/type-support、二进制哈希及与原版轨迹数值等价的开发场景证据，才能参与公平基线。不能按未见场景调参。

已拒绝两条看似简单的路线：只比较上游 header 墙钟时间或轨迹号无法建立观测消费关系；每一帧重启规划器会抹掉地图和动态规划历史，改变对手。具体接口、故障矩阵与逐级试验见 [设计](superpowers/specs/2026-10-10-ego-causal-provenance-design.md) 和 [计划](superpowers/plans/2026-10-10-ego-causal-provenance.md)。目前 `same_observation_causality_proven=false`、新教师语料资格 false；固定 EGO 单机历史表现不因此改写。

本轮宿主空闲物理内存约 0.47 GiB，低于现有完整 MaleCNS 4 GiB 探测门槛。未启动竞争仿真或训练。未解锁 PX4/VIO 物理、完整果蝇学习、5/20 机扩展和原生 Linux/HITL/实飞仍按总路线图分别验证，不能由本报告宣称完成。
