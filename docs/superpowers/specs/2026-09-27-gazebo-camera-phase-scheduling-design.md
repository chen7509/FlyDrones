# Gazebo 五机深度相机仿真时钟错峰调度设计

**日期：** 2026-09-27
**状态：** 待书面规格复核
**适用分支：** `codex/vio-faults`
**范围：** 五机 PX4 SITL / Gazebo Harmonic 深度相机渲染时序、调度证据和冻结对照试验

## 1. 背景与触发证据

`renderer-formal-20260927-2` 完成了 5 个 D3D12 五机任务轮次：

- 每轮均达到 `5/5` 任务完成、`5/5` 着陆和完整起飞证据链；
- 每轮尾部 p99 为 `24.099～28.862 ms`，最大尾延迟为 `67.139～85.802 ms`；
- 每轮 RTF 为 `0.9807～0.9958`；
- 所有单轮绝对门槛均通过。

正式总门槛仍失败。按时间顺序的前三个 D3D12 最大尾延迟为
`67.477 → 73.117 → 73.807 ms`，首尾增加 `6.329 ms`，触发冻结的
`d3d12_sustained_tail_degradation` 判据。该失败不能用补跑、删除结果或放宽
`5 ms` 趋势阈值消除。

当前五个深度相机使用相同 `10 Hz` 更新率，并由 Gazebo Sensors 系统在相同仿真
时间边界判断更新。待验证的单变量假设是：五个渲染传感器集中在同一更新边界，
形成周期性 GPU/渲染突发；保持每机信息量不变并将更新均匀分散到 100 ms 周期内，
可以降低最大尾延迟及其持续恶化。

这不是训练问题。本设计不修改策略权重、损失函数、课程、规划器、安全门槛或 PX4
控制器。

## 2. 目标与非目标

### 2.1 目标

1. 为五个深度相机提供可复现的仿真时钟触发模式，固定相位为
   `0、20、40、60、80 ms`，每机仍为 `10 Hz`。
2. 同时记录计划触发、实际触发发布和实际深度图像发布时间，证明错峰真正发生在
   Gazebo 传感器输出，而不只发生在控制脚本。
3. 在相同 D3D12、场景、机体、任务、策略、PX4 和安全配置下，完成同步与错峰的
   五组交替配对试验。
4. 用预注册的绝对门槛、趋势门槛和配对改善门槛决定假设是否成立。
5. 完整保留失败、ULog、时序记录、资源清理和原始文件哈希。

### 2.2 非目标

- 不降低分辨率、帧率、视场角或传感器数量。
- 不以墙钟定时器代替仿真时钟。
- 不修改 Gazebo、gz-sensors 或 PX4 上游源码。
- 不把触发发布时刻当成图像实际生成时刻。
- 不改变真值转发外部视觉链路，也不把它称为真实相机加 IMU VIO。
- 不在无故障相位门槛通过前执行 120 ms 延迟或 400 ms 断流；本阶段不执行 HITL 或实飞。
- 不把错峰结果外推到真实相机硬件，真实相机同步与总线调度需要独立验证。

## 3. 方案选择

### 3.1 采用：触发式深度相机与仿真时钟调度器

Gazebo Sensors 8.1 将 trigger 逻辑移到基础 Sensor，并为全部相机传感器启用。
触发主题使用 `gz.msgs.Boolean`。本项目运行在 Gazebo Harmonic / gz-sensors 8，
因此可以在试验副本中把深度相机配置为 triggered，并由 Python
`gz.transport13` 调度器按 `/clock` 发布触发。

优点：

- 不修改上游源码或引入新的产品运行时依赖；
- 调度基于仿真时间，暂停和慢速仿真不会造成墙钟漂移；
- 五机总帧数、每机帧率和图像内容保持不变；
- 计划时刻、发布时刻和图像时刻都可审计。

### 3.2 拒绝：本地 C++ Gazebo 系统插件调用 `SetNextDataUpdateTime`

该 API 可以直接设置传感器下一次更新时间，时序控制更接近 Sensors 内部，但需要
新增编译、ABI、插件搜索路径和部署链路。当前 Python 绑定及 trigger 接口足以验证
假设，C++ 插件的额外复杂度不会提高本轮结论强度。

### 3.3 拒绝：按墙钟延迟启动模型、订阅者或 worker

墙钟启动顺序会受 PX4 冷启动、WSL 调度和 RTF 变化影响，相位会漂移；只错开订阅者
也不能证明 GPU 渲染已经错开。该方案不能形成可复现的单变量证据。

## 4. 组件与边界

### 4.1 相机模式

试验运行器增加显式模式：

- `simultaneous`：使用现有 free-running 深度相机，`update_rate=10`；
- `phased`：试验副本在保持 `update_rate=10` 的同时增加
  `<camera><triggered>true</triggered></camera>`，由调度器触发。

默认产品路径保持 `simultaneous`。只有新相机相位 campaign 显式选择
`phased`。模式必须进入 trial manifest 和冻结哈希。

### 4.2 SDF 试验副本转换

新增纯函数转换器，只修改 PX4 运行目录中的相机模型副本：

1. 精确找到 `StereoOV7251` 深度相机；
2. 验证分辨率为 `160×120`、更新率为 `10 Hz`；
3. 在 `phased` 模式写入 `triggered=true`；
4. 禁止改变图像、视场角、裁剪范围、质量、姿态和惯性；
5. 输出转换前后 SHA-256 与结构化差异；
6. 找不到或找到多个目标传感器时 fail-closed。

仓库中的基础相机资产不被原地修改。同步和错峰试验均从同一基础资产生成运行副本，
防止前一轮状态污染后一轮。

### 4.3 仿真时钟触发调度器

独立进程订阅 `/clock`，发现五个模型各自的深度图像和默认 trigger topic。所有
预期 topic 就绪后，选择第一个不早于当前仿真时间、且对齐 100 ms 周期的
`epoch_ns`。计划时刻为：

[
t(k, i) = epoch + 100\text{ms} \times k + 20\text{ms} \times i
]

其中 `i=0..4` 为 vehicle id，`k=0,1,...` 为周期编号。单机场景只使用相位 0。

调度规则：

- 使用仿真时间判断到期；仿真暂停时不发布；
- 每次时钟推进只发布已经到期且尚未发布的触发；
- 时钟跨越多个计划时刻时，不连续补发形成新突发；记录漏触发并令证据失败；
- 仿真时间倒退、重复 epoch、未知模型或 topic 归属冲突立即 fail-closed；
- 每个事件记录 vehicle、topic、周期、计划仿真时刻、发布仿真时刻、墙钟时刻和迟到量；
- 进程通过 readiness marker 表明已发现全部 topic 并建立发布者；
- completion marker 后写入 stop 事件并退出；未正常退出使 trial 失败。

调度器不读取策略、PX4 状态或任务结果，也不向飞行控制接口发送信息。

### 4.4 独立相位观察器

同步组和错峰组都运行同一个只读观察器，以保持测量负载一致。观察器订阅：

- `/clock`；
- 每架机的深度图像 topic；
- 错峰组的触发 topic。

它记录实际图像消息的 header 仿真时间、主机接收单调时间、序号和模型归属。错峰组
额外把图像时间与对应计划触发配对；同步组只计算自然相位分布。观察器产生
`camera-phase.jsonl`、readiness marker 和干净停止证据，不向任何控制器暴露数据。

相位结论以实际深度图像 header 时间为准。调度器发布记录只证明输入，不能替代输出
证据。

### 4.5 试验生命周期

运行顺序固定为：

1. 生成世界与相机模型副本；
2. 启动 relay 和 Gazebo；
3. phased 模式启动调度器；
4. 启动相位观察器并等待全部 topic；
5. 启动 PX4 实例并完成 renderer attestation；
6. 仅当调度器、观察器、执行器探针和渲染证明都就绪后启动 worker；
7. worker 结束后执行 LAND、资源清理和 completion marker；
8. 等待调度器、观察器和现有探针写入 stop；
9. 恢复共享 PX4 文件并核验指纹。

同步模式不启动调度器，但必须启动同一观察器。任何辅助进程异常均不得被
`mission_count=5` 覆盖。

## 5. 相位证据与判定

每架机输出以下指标：

- `planned_trigger_count`、`published_trigger_count`、`image_count`；
- 平均图像频率；
- 图像间隔 p50、p95、p99、max；
- 相对 100 ms 周期的圆周相位；
- 相对目标相位的绝对误差 p50、p95、max；
- 漏触发、重复触发、未匹配图像和跨机归属错误。

错峰证据硬门槛：

- 五个目标相位必须精确为 `0、20、40、60、80 ms`；
- 每机平均图像频率在 `9.5～10.5 Hz`；
- 每机相位误差 p95 不超过 `8 ms`；
- 任意相邻目标相位的实际中位间距误差不超过 `8 ms`；
- 漏触发、重复触发、未匹配图像和跨机归属错误均为 0；
- 日志必须包含 start、topology、ready 和 stop；
- 调度器、观察器和 owned-process cleanup 全部干净。

`8 ms` 容差对应当前 `4 ms` Gazebo physics step 的两个时间步。它在 live 结果
出现前冻结，不能根据结果扩大。

同步组记录相同指标，但不要求目标相位。它必须证明五机各自保持 `10 Hz`，并报告
同一 10 ms bin 中同时出帧的最大相机数，供配对解释。

## 6. 冻结试验设计

### 6.1 不变量

同步组和错峰组保持完全一致：

- D3D12 NVIDIA renderer；
- 同一 PX4、Gazebo、Mesa 和驱动版本；
- 同一世界、五个 x500、相机成像参数和动力学；
- 同一策略权重、任务、安全层、速度约束与随机种子；
- 同一 VIO 真值替身、GNSS 关闭过程、起终点和任务时限；
- 同一 runtime、GPU、执行器、ULog、清理和相位观察器；
- 每轮独立冷启动，不复用 Gazebo/PX4 进程。

唯一自变量是 `camera_schedule_mode`。

### 6.2 开发场景

1. phased 单机：验证 triggered 深度相机、10 Hz、任务与着陆。
2. phased 五机：验证五个目标相位、完整任务、渲染证明和清理。
3. 调度器故障注入：自动制造漏触发或提前退出，验证 worker 不启动或进入安全着陆，
   且证据明确失败。

开发场景只修正接口和证据错误。通过后冻结代码、配置和全部预期哈希。

### 6.3 smoke

使用新 campaign id 依次运行：

1. phased 单机；
2. simultaneous 五机；
3. phased 五机。

三轮必须通过各自模式的证据、全部现有安全门槛、renderer attestation 和清理门槛。

### 6.4 正式配对

正式序列为五组、十轮 D3D12 五机冷启动，并交替顺序：

| 配对 | 第 1 轮 | 第 2 轮 |
|---:|---|---|
| 1 | simultaneous | phased |
| 2 | phased | simultaneous |
| 3 | simultaneous | phased |
| 4 | phased | simultaneous |
| 5 | simultaneous | phased |

任一轮缺少完整工件、渲染证明、起飞链、相位证据、`5/5` 任务、`5/5` 着陆或干净
清理时，保存该轮并停止 campaign。同步组发生趋势恶化可以作为对照现象继续统计，但
同步组的单轮绝对门槛仍必须通过。

## 7. 预注册通过标准

### 7.1 单轮硬门槛

每个 simultaneous 和 phased 正式轮都必须满足：

- `5/5` mission-ready、任务完成和安全着陆；
- 完整 PX4、执行器、Gazebo 物理与 EKF 证据；
- GNSS 关闭后的任务阶段 EV 健康；
- 尾部 p99 `<=100 ms`；
- 最大尾延迟 `<250 ms`；
- RTF `>=0.95`；
- 渲染器、探针和资源清理证明完整。

phased 轮还必须满足第 5 节的相位硬门槛。

### 7.2 假设支持门槛

只有以下条件全部成立，才写为“相机错峰假设得到支持”：

1. 五个 phased 轮全部通过单轮硬门槛；
2. phased 最大尾延迟序列不触发既有连续三轮、首尾增加超过 `5 ms` 的恶化判据；
3. 五个配对中至少 `4/5` 的 `phased - simultaneous` 最大尾延迟小于 0；
4. 五个配对差值的中位数不高于 `-5 ms`；
5. phased 的尾部 p99 中位数相对 simultaneous 不恶化超过 `2 ms`；
6. phased 的 RTF 中位数相对 simultaneous 不下降超过 `0.01`。

若只满足绝对门槛而不满足配对改善门槛，结论为“可运行但未证明优于同步更新”。若
相位门槛失败，不能用性能数字判断假设。

### 7.3 后续故障回归

只有第 7.2 节通过后，才以同一冻结提交运行 120 ms 延迟和 400 ms 断流回归。未通过
时应报告负结果，并选择新的独立假设；不得在当前 campaign 中改变相位、频率、容差
或配对顺序。

## 8. 测试策略

实现遵循 TDD，至少覆盖：

- SDF 转换只增加 trigger 配置，拒绝错误传感器数量和参数漂移；
- `epoch` 与五机相位计算；
- 仿真暂停、重复时钟、时间倒退和跨周期跳跃；
- 不允许漏触发后的补发突发；
- topic 发现、跨机映射、ready/stop 生命周期；
- 图像 header 时间与计划触发的配对；
- 相位圆周统计、100 ms wrap-around 和 4 ms 量化边界；
- 同步组与错峰组使用同一观察器；
- 调度器异常时 worker 不启动或安全结束；
- campaign 顺序、不可覆盖、resume、冻结哈希与 fail-fast；
- 原有 simultaneous 默认路径行为不变；
- 紧凑快照保留相位摘要和全部原始文件 SHA-256/大小。

live 前执行完整 pytest、目标 Ruff 和 `git diff --check`。live 后重新执行相同门槛，
并检查无 PX4、Gazebo、relay、scheduler、probe、worker 或训练进程残留。

## 9. 上游依据与依赖

| 组件 | 许可证与状态 | 用途 | 决定 |
|---|---|---|---|
| Gazebo Sim / Sensors / Transport | Apache-2.0，Harmonic 与 Sensors 8 仍维护 | triggered camera、仿真时钟、Boolean trigger、图像订阅 | 采用现有安装 |
| SDFormat 14 | Apache-2.0，Harmonic 配套 | 相机 `triggered` 配置 | 采用现有安装 |
| 本地 C++ System Plugin | 可用 Apache-2.0 接口实现 | 直接控制 next update time | 本阶段拒绝 |
| ROS 2 / ros_gz | Apache-2.0 | 转发 trigger 和图像 | 本阶段拒绝，不新增桥接变量 |

主要可核验依据：

- [Gazebo Harmonic Sensors 教程](https://gazebosim.org/docs/harmonic/sensors/)说明
  `update_rate` 控制传感器数据生成频率；
- [gz-sensors 8 变更记录](https://github.com/gazebosim/gz-sensors/blob/main/Changelog.md)
  记录 8.1 将 trigger 逻辑移入基础 Sensor 并启用全部相机传感器；
- [官方 triggered camera SDF](https://github.com/gazebosim/gz-sensors/blob/main/test/sdf/triggered_camera_sensor_topic_builtin.sdf)
  展示 `<camera><triggered>true</triggered></camera>`；
- [官方触发测试](https://github.com/gazebosim/gz-sensors/blob/main/test/integration/triggered_boundingbox_camera.cc)
  使用 `gz.msgs.Boolean` 发布 trigger；
- [Gazebo Sensor API](https://gazebosim.org/api/sensors/7/classgz_1_1sensors_1_1Sensor.html)
  说明 next update time 和 update rate 的时序边界。

实现前必须在本机安装的 gz-sensors 8 上完成最小兼容性测试，证明
`DepthCameraSensor` 接受 trigger 并只在触发后发布。若本机版本不支持，该事实构成
设计边界，必须回到独立的 C++ 插件方案评审，不能静默退化为墙钟方案。

## 10. 证据边界与完成定义

本设计验证的是本机 Gazebo D3D12 五机渲染负载调度。它不验证真实相机曝光同步、
USB/MIPI 带宽、机载 VIO 计算、HITL 或实飞。

本阶段完成要求：

1. 规格和实施计划获得复核；
2. 自动化测试与最小本机兼容性测试通过；
3. 三个开发场景通过并冻结代码与配置；
4. smoke 三轮通过；
5. 正式十轮从头完成，所有失败均保留；
6. 按第 7 节给出支持、未证明或拒绝假设的明确结论；
7. 若假设支持，在同一冻结提交上完成 120 ms 延迟和 400 ms 断流回归；若不支持，明确记录未执行原因；
8. 发布紧凑证据、原始文件哈希、实际时延限制和资源释放证明；
9. 不修改策略训练结果，不把 Gazebo 真值称为真实 VIO。
