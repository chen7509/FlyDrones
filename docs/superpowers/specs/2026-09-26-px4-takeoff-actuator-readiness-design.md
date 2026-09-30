# PX4 起飞事务与 Gazebo 执行链路验证设计

**日期：** 2026-09-26
**状态：** 待书面规格复核
**适用分支：** `codex/vio-faults`
**范围：** 五机 PX4 SITL / Gazebo 起飞门槛、失效分类和可审计证据

## 1. 背景与已知事实

`renderer-formal-20260926-3` 的第二次 D3D12 五机试验中，2 号机在地面停留到任务超时。现有结果不能把这次失败归因于学习策略：

- 2 号机收到 MAVLink 心跳，深度流、外部视觉健康门槛和本地状态门槛均通过；
- ULog 中解锁命令 400、起飞命令 22、模式命令 176 均返回 `MAV_RESULT_ACCEPTED`；
- PX4 进入 armed、takeoff complete 和 OFFBOARD 状态，四路 `actuator_motors` 一度接近 1.0；
- PX4 本地位置和 Gazebo 原始里程计都显示高度变化不足约 0.05 m，机体没有真正离地；
- 生成的场景在出生点没有障碍物，Gazebo 日志没有对应的碰撞或电机插件错误；
- 当前控制器仍把无人机标记为飞行中并进入了约 70 秒自主任务循环。

因此，已证明的是“PX4 接受并生成了控制输出，但该机体没有物理响应”。尚未证明断点位于 PX4 Gazebo 桥发布、电机模型接收还是 Gazebo 物理求解。此次工作不调整策略权重、损失函数、课程训练或规划器参数。

## 2. 目标与边界

### 2.1 目标

1. 把起飞从固定延时调用改为有状态、有超时、有后置条件的事务。
2. 在每架机进入自主任务前证明：命令被接受、机体已解锁、实际高度持续上升、OFFBOARD 已生效。
3. 在仿真工具侧独立记录 PX4 电机命令是否到达 Gazebo Transport，以及 Gazebo 机体是否产生物理响应。
4. 失败时尽快停止自主控制，执行确定性的安全处置，并输出可定位的原因码。
5. 用重复冷启动证明该修复消除了间歇性五机起飞失败，然后从头重跑 renderer smoke 和正式配对试验。

### 2.2 非目标

- 不把 Gazebo 真值输入自主策略、安全监督器或 PX4 EKF；真值只供仿真基础设施诊断和离线评分。
- 不把真值转发称为真实相机加 IMU VIO。
- 不更换 PX4、Gazebo、机体、传感器、学习策略或任务场景。
- 不用自动重复起飞、错峰启动或放宽通过标准来隐藏故障。
- 不把本项结果表述为 HITL 或实飞证据。

## 3. 方案选择

### 3.1 采用：分层起飞事务与独立执行链路探针

飞行控制层验证 MAVLink 命令、PX4 状态和 EKF 高度后置条件；仿真工具层独立观察 Gazebo Transport 电机命令和机体里程计。两层证据互不替代，既能在真实飞行接口上保持正确边界，也能定位 SITL 特有的执行器链路问题。

### 3.2 拒绝：只增加 ACK 检查

本次失败的起飞 ACK 已经是 `ACCEPTED`。只检查 ACK 会再次放行同一故障。

### 3.3 拒绝：固定延时、盲目重试或错峰启动

这些方法可能降低复现概率，却不能证明物理链路恢复；在已解锁状态重复起飞也会引入新的安全风险和不可解释状态。

## 4. 架构

系统分为四个边界清晰的组件。

### 4.1 `MavlinkDrone` 起飞事务

`MavlinkDrone.takeoff()` 不再是无返回值的固定等待过程，而是返回结构化 `TakeoffEvidence`。它只依赖 MAVLink，不读取 Gazebo 真值。

状态机如下：

1. `preflight-ready`：心跳、位置、姿态、估计器状态新鲜，PX4 报告可解锁。
2. `arm-sent`：发送解锁命令并等待相同命令、相同目标系统的 ACK。
3. `armed`：ACK 允许后仍须观察到 armed 状态。
4. `takeoff-sent`：发送 `MAV_CMD_NAV_TAKEOFF`，记录命令参数和发送时间。
5. `takeoff-accepted`：等待匹配 ACK；`IN_PROGRESS` 只作为中间状态，拒绝、失败或超时立即终止。
6. `climb-confirmed`：以起飞前 EKF 高度为基线，在 12 秒内连续三个新鲜样本达到至少 0.5 m 高度增量，并且 PX4 不再报告 landed。
7. `offboard-primed`：以配置频率连续发送零速度设定值至少 1.5 秒。
8. `offboard-confirmed`：模式命令 ACK 被接受，并从 PX4 心跳/状态确认 OFFBOARD 已生效。
9. `mission-ready`：只有到达此状态才把 `flying` 标志设为真并允许任务控制输出。

每个状态事件记录单调时钟、PX4 系统/组件 ID、命令、ACK 结果、armed、landed、导航状态、OFFBOARD 状态、高度和状态样本年龄。

### 4.2 分布式工作者任务门槛

`run_distributed_px4_agent` 接收 `TakeoffEvidence`，并在任务开始前执行硬门槛：

- 事务必须到达 `mission-ready`；
- 起飞后的 VIO 和 PX4 状态必须重新达到新鲜健康状态；
- 任何失败都不得进入 `escaping`、策略调用或规划器循环；
- 结果 JSON 包含完整起飞摘要和确定性失败原因。

现有“解锁超时后直接再次调用整个 `takeoff()`”逻辑将被移除。只有在命令未被 PX4 接受、无人机仍明确处于 disarmed 与 landed 状态时，才允许一次有限重试。已 armed、已接受起飞或状态不确定时禁止重试。

### 4.3 Gazebo 执行链路探针

新增仿真专用、只读的执行链路探针。它不参与飞行决策，记录：

- 每架机唯一模型名与 `/MODEL/command/motor_speed` 主题拓扑；
- 独立 Gazebo Transport 订阅者实际收到的电机命令时间、频率、四路值和最大值；
- `/flydrones/odometry_raw` 中每架机的原始位置、高度变化和时间戳；
- 试验前后的发布者/订阅者拓扑快照；
- 探针自身丢帧、解析错误和退出状态。

PX4 ULog 的 `actuator_motors` 证明飞控内部生成输出；独立电机主题探针证明输出到达 Gazebo Transport；原始里程计证明物理机体响应。三份证据共同构成执行链路。

### 4.4 ULog 与汇总器

ULog 汇总增加逐机提取：

- `vehicle_command` / `vehicle_command_ack`；
- `vehicle_status`、`vehicle_control_mode`、`vehicle_land_detected`；
- `actuator_armed`、`takeoff_status`、`actuator_motors`；
- `vehicle_local_position` 与 `vehicle_local_position_groundtruth`。

试验汇总必须逐机对齐 MAVLink 事务、ULog、Gazebo 电机主题和 Gazebo 里程计，不允许只用聚合的 5/5 数字掩盖单机缺证。

## 5. 失效分类与安全处置

| 原因码 | 证据 | 处置 |
|---|---|---|
| `arm-command-rejected` | 解锁 ACK 为拒绝/失败 | 保持地面，不重试任务 |
| `arm-state-timeout` | ACK 接受但未观察到 armed | 保持或恢复 disarmed，终止 |
| `takeoff-command-rejected` | 起飞 ACK 为拒绝/失败 | 若已 armed 则请求 LAND，确认地面后解锁 |
| `offboard-command-rejected` | 模式 ACK 拒绝或状态未进入 OFFBOARD | 请求 LAND，等待 landed |
| `gazebo-motor-command-missing` | ULog 有输出，独立 Gazebo 主题无命令 | 判为桥/Transport 故障，终止试验 |
| `actuator-response-timeout` | Gazebo 收到显著电机命令，但机体高度未上升 | 判为电机插件/物理故障，请求 LAND；地面确认后解锁 |
| `estimator-response-timeout` | Gazebo 机体上升，但 PX4 EKF 高度未响应 | 判为传感器/估计器故障，请求 LAND |
| `takeoff-state-stale` | 关键状态超过年龄门槛 | 停止控制输出并请求 LAND |

LAND 后必须等待 landed 与 disarmed 证据；超时则保留明确的清理失败，不把“已发送 LAND”写成“已安全落地”。`emergency_stop` 不作为自动恢复手段。

## 6. 数据与产物

每架机结果新增 `takeoff` 对象，至少包含：

- `terminal_stage`、`accepted`、`failure_reason`；
- `baseline_altitude_m`、`maximum_altitude_gain_m`；
- `arm_ack`、`takeoff_ack`、`offboard_ack`；
- `armed_at_s`、`takeoff_accepted_at_s`、`climb_confirmed_at_s`、`offboard_confirmed_at_s`；
- `target_system`、`target_component`；
- 有限、按时间排序的 `events`。

试验目录新增：

- `actuator-link.jsonl`：逐帧电机命令与机体响应；
- `actuator-link-summary.json`：逐机链路判定；
- 每个 PX4 实例的 `out.log`、`err.log`；
- 扩展的 `trial-manifest.json` 哈希清单；
- 原始 ULog 和已有控制器 CSV/JSON。

紧凑快照只保存摘要、失败附近的有限时间窗、清单和哈希；大型 ULog 与逐帧日志继续留在原始结果目录。

## 7. 测试与验收

### 7.1 自动化测试

测试先于实现，覆盖：

- ACK 匹配、无关 ACK 过滤、`IN_PROGRESS`、拒绝和超时；
- armed、landed、OFFBOARD 与高度连续样本门槛；
- 已 armed 后无升力时禁止重复起飞；
- 起飞失败时策略和规划器调用次数为零；
- LAND、landed、disarmed 的安全顺序；
- 五个模型的电机主题严格映射，禁止跨机混用；
- ULog、Gazebo 电机命令和里程计的四类失效分类；
- 老结果缺少新字段时显式标记为 legacy/unverified，而不是误判通过。

### 7.2 开发场景

1. 单机 D3D12 正常起飞、OFFBOARD、降落。
2. 五机 D3D12 正常起飞、短时悬停、降落。
3. 自动化注入“PX4 有输出但物理高度不变”，验证 `actuator-response-timeout`、零任务调用和安全处置。

开发场景可用于修正接线错误；完成后冻结阈值和配置。

### 7.3 稳定性门槛

冻结后执行 10 次独立五机 D3D12 冷启动起飞/降落循环，共 50 次单机起飞：

- 50/50 达到 `mission-ready`；
- 50/50 有匹配的 PX4、Gazebo 电机命令和物理高度证据；
- 50/50 安全落地并解锁；
- 无跨机主题、系统 ID 或证据归属错误；
- 每次清理均证明本次拥有的进程已退出。

任何一次失败都原样保留并停止稳定性门槛，不在同一冻结批次中调参。修复后以新批次从第 1 次重新开始。

### 7.4 后续正式试验

稳定性门槛通过后，以新提交和新试验 ID 从头运行 renderer smoke，再运行完整正式配对试验。不得补跑旧批次中失败的一项来替代完整批次。

## 8. 上游调研与依赖选择

| 候选 | 许可证/维护 | 接口与成本 | 决定 |
|---|---|---|---|
| 现有 `pymavlink` + PX4 MAVLink/ULog | `pymavlink` 为 LGPL-3.0-or-later、生成代码为 MIT；PX4 为 BSD-3-Clause；上游仍维护，项目已依赖 | 可直接匹配 `COMMAND_ACK` 并读取现有状态流；无需新增运行时 | 采用 |
| MAVSDK Action/Telemetry | BSD-3-Clause；活跃 | 起飞 API 更高层，但替换当前速度控制连接、五端口和故障注入接口成本高，仍不能证明 Gazebo 电机插件响应 | 拒绝本阶段引入 |
| ROS 2 `rclpy` / Micro XRCE-DDS 控制面 | 两者均为 Apache-2.0；PX4 上游支持 | 可读取 uORB 映射，但会新增代理、QoS 和多机命名空间变量 | 拒绝本阶段引入 |
| Gazebo Transport Python 探针 | Gazebo Sim Apache-2.0；项目已有同版本绑定 | 复用现有 `gz.transport13` 与消息类型，资源开销低；只读旁路 | 采用 |

主要上游依据：

- PX4 Offboard 文档规定进入和维持 OFFBOARD 前必须持续提供超过 2 Hz 的外部设定值；本设计保留 1.5 秒预热，并增加模式确认。
- PX4 多机 Gazebo 文档规定实例号与唯一模型名的对应关系；探针按该映射逐机归属证据。
- PX4 `GZMixingInterfaceESC` 将输出发布到模型级 `command/motor_speed`；Gazebo `MulticopterMotorModel` 从该主题接收电机命令。
- Meier、Honegger、Pollefeys 的 PX4 架构论文说明飞控内部采用模块化发布订阅架构，因此飞控输出与外部仿真执行器响应应作为两个边界分别验证。
- Meyer 等人的 ROS/Gazebo 四旋翼仿真工作以及 Flightmare 工作均强调动力学、传感器、渲染和控制边界；本设计据此明确区分飞控接受、Transport 传递和物理响应。

可核验来源：

- [PX4 Offboard Mode](https://docs.px4.io/v1.17/en/flight_modes/offboard)
- [PX4 Multi-Vehicle Simulation with Gazebo](https://docs.px4.io/v1.15/en/sim_gazebo_gz/multi_vehicle_simulation)
- [PX4 GZMixingInterfaceESC](https://github.com/PX4/PX4-Autopilot/blob/main/src/modules/simulation/gz_bridge/GZMixingInterfaceESC.cpp)
- [PX4 x500 Gazebo model](https://github.com/PX4/PX4-gazebo-models/blob/main/models/x500/model.sdf)
- [Gazebo multicopter motor example](https://github.com/gazebosim/gz-sim/blob/main/examples/worlds/quadcopter.sdf)
- [pymavlink license and maintenance](https://github.com/ArduPilot/pymavlink)
- [MAVSDK license and maintenance](https://github.com/mavlink/mavsdk)
- [Gazebo Transport license and maintenance](https://github.com/gazebosim/gz-transport)
- [PX4 architecture paper](https://people.inf.ethz.ch/~pomarc/pubs/MeierICRA15.pdf)
- [Flightmare paper](https://proceedings.mlr.press/v155/song21a/song21a.pdf)

本设计不新增产品运行时依赖，也不修改 PX4 或 Gazebo 上游源码。

## 9. 风险与控制

- **状态流被 ACK 等待消费：** 所有阻塞等待按消息类型和命令号过滤，并在单一 MAVLink 读取边界内更新缓存。
- **PX4 landed 误判：** 本次证据表明 landed 可在机体未移动时变为 false，因此必须同时满足连续高度增量。
- **Gazebo 探针影响时序：** 探针只订阅低体积的电机命令和既有里程计流，记录自身 CPU、丢帧和退出状态。
- **仿真真值污染控制器：** 模块边界禁止探针数据进入 `MavlinkDrone`、工作者观测或安全监督器。
- **重复试验耗时：** 先用短起降循环验证执行链路，通过后才运行完整 70 秒任务和正式故障场景。

## 10. 完成定义

本项只有在以下条件同时成立时完成：

1. 自动化测试和仓库既有回归测试通过；
2. 起飞事务失败不会进入自主任务；
3. 三个开发场景通过并冻结配置；
4. 10 次五机冷启动稳定性门槛全部通过；
5. renderer smoke 与完整正式配对试验以新批次完成；
6. 报告准确区分单元测试、Gazebo 物理仿真、HITL 和实飞；
7. 所有原始失败、ULog、进程清理证据和哈希可追溯。
