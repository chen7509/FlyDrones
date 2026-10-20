# EGO 桥接输入边界开发报告（2026-10-10）

## 结论

固定 EGO-Swarm ROS 桥接现在会在发布 `/clock`、里程计、相机位姿或深度图之前，拒绝格式、数值、时间或图像内容不符合契约的观测。每次 reset 握手重置观测序列；连续请求必须具有严格递增的仿真时间，相机帧可按原有 10 Hz 重复但不能回退。旧合成烟测文件和全部历史对照证据未改动。**本阶段只验证本机离线输入边界，没有运行 EGO 容器、PX4/Gazebo 或 OpenVINS，也没有资格宣布教师数据因果正确或公平物理对照通过。**

## 来源和采用理由

- 对手固定为 [ZJU-FAST-Lab/ego-planner-swarm 提交 `23a8d5a`](https://github.com/ZJU-FAST-Lab/ego-planner-swarm/tree/23a8d5a191711dd65633df689bd00f55d4dea8f9)，许可证 GPL-3.0。检查时仓库未归档，远端最后推送时间为 2025-03-08；维护节奏不确定。保留已固定的镜像及上游代码，不自行仿造规划器。现有桥接和 NumPy 已在镜像挂载路径 `/benchmark` 可用，无新增运行依赖；适配成本是本地纯 Python 输入门禁与故障测试。
- 固定上游 [odometryCallback](https://github.com/ZJU-FAST-Lab/ego-planner-swarm/blob/23a8d5a191711dd65633df689bd00f55d4dea8f9/src/planner/plan_manage/src/ego_replan_fsm.cpp) 把 `twist.twist.linear` 分量直接用作规划速度；[ROS 2 Humble 的 `Odometry.msg`](https://github.com/ros2/common_interfaces/blob/humble/nav_msgs/msg/Odometry.msg) 规定 twist 在 `child_frame_id` 坐标系。当前桥接标 `base_link`，却传世界坐标速度。因上游直接消费世界速度，未在这一阶段悄悄旋转或改动消息约定；该接口语义仍须独立验证，公平资格保持关闭。
- 上游 `PositionCommand` 到达时，桥接把最近观测仿真时间附给结果；上游 header 是墙钟时间。命令到达顺序、以及本次修正后的 revision 快照，仍不能证明结果由该帧触发。正式教师语料需要另行绑定可核验的因果身份。

## 实现与验证

`tools/benchmark/ego_wire_observation.py` 是不依赖 ROS、PX4 或 Gazebo 的纯解码器：只接受精确 JSON 字段、合法 UTF-8 与有限数值，检查重复键、时间差、单位四元数、120×160 RGB-D 形状及严格 base64 字节数；正有限深度有效，NaN 仅代表缺测。错误输入不发布任何 ROS 消息。`tools/benchmark/ego_node.py` 在 reset 后启用该门禁，并在完整解码与序列校验后、发布前记录旧参考修订号，避免读下一帧时到达的旧命令直接满足新请求。新 `synthetic_client_v2.py` 只是未来开发烟测的完整 RGB-D 样例，不修改历史旧客户端。

按测试先行流程，原始解析器缺失、桥接未拦截、非单位四元数和上一帧迟到命令都先在针对性测试中失败；修正后的相邻基准/传感器/EGO 适配测试 **59 passed**。改动文件 Ruff 及 `git diff --check` 通过。审查发现的两项问题都保留了失败输出 `red-review.txt` 并加了回归测试。证据包保存源码、规格/计划、测试输出和新样例的成员哈希；封存校验不等于现场容器运行。

## 状态与下一门槛

| 项目 | 状态 |
| --- | --- |
| 精确输入格式、图像和时间序列拒绝 | 本机单元及真实桥接循环替身测试通过 |
| 固定 EGO 上游本次新桥接实机通信 | 未测试；需新的开发运行与版本冻结 |
| 世界速度与 ROS `child_frame_id` 语义一致性 | 未解决，不得称公平输入已经合格 |
| 上游命令和指定观测帧的因果配对 | 未解决，不得入教师训练语料 |
| 非真值 PX4 EKF2/已标定相机生产源 | 未接入本桥接新运行 |
| 果蝇与 EGO 新公平物理对照 | 未运行；既有失败证据保持不变 |

当前空闲内存约 0.723 GiB，低于现有完整连接组 4 GiB 资源门槛；本轮未启动抢占资源的物理仿真或训练。下一步应先用来源绑定的非真值数据解决帧/速度语义和命令因果契约，再做独立开发烟测与冻结；不能用旧封存测试场景调参。
