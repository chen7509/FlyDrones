# 五机 PX4 起飞与 Gazebo 渲染稳定性验证报告

日期：2026-09-27
PX4 起飞稳定性序列：`takeoff-stability-d3d12-20260927-2`
渲染 smoke 序列：`renderer-smoke-20260927-2`
渲染正式序列：`renderer-formal-20260927-2`
FlyDrones 起飞控制提交：`c59c06563bcb1992ded95bca8c9486f956601983`
FlyDrones 正式证据提交：`705f807cefa1fd97588573996f5ca07349c18405`
PX4 提交：`d6f12ad1c4f70ad3230afd7d86e971421e02fef4`
固定随机种子：`240901`

## 结论

这轮得到两个不同层级的结论：

1. **PX4 起飞/执行器准备稳定性门槛通过。** 10 次 D3D12 五机冷启动全部通过，累计 `50/50` 架次达到 `mission-ready`，`50/50` 安全着陆，`10/10` 轮清理干净。每架飞机都有 arm/takeoff ACK、解锁与 OFFBOARD 状态、连续爬升、Gazebo 电机命令与物理位移、PX4 估计器响应和着陆证据。
2. **渲染稳定性正式总门槛未通过。** 5 次 D3D12 正式轮次各自都通过全部绝对阈值，累计 `25/25` 完成任务、`25/25` 着陆；但预先冻结的趋势规则检测到前三次最大尾延迟 `67.477 → 73.117 → 73.807 ms` 连续上升，首尾增加 `6.329 ms`，超过 `5 ms` 判据，因此产生唯一的正式失败代码 `d3d12_sustained_tail_degradation`。

没有修改阈值、删除失败或追加试验来改变趋势。由于无故障 D3D12 总门槛没有通过，按协议没有执行本提交下的 120 ms 延迟与 400 ms 断流正式回归。

当前证据说明之前的间歇性不起飞问题已经被定位并修复：在 arm、takeoff 和 OFFBOARD 状态等待期间持续发送有效设定值，避免 PX4 因设定值中断退出 OFFBOARD。它不证明渲染时序已经长期稳定，也不证明真实相机 VIO、HITL 或实飞可靠性。

## 固定条件与证据边界

- D3D12 后端证明为 `D3D12 (NVIDIA GeForce RTX 3070 Ti Laptop GPU)`，并记录 `libd3d12.so`、`libd3d12core.so` 与 `libdxcore.so` 映射。
- 对照后端为 `llvmpipe (LLVM 20.1.2, 256 bits)`。
- 两个后端使用同一世界、机体、深度相机、策略权重、速度约束、PX4 接口、安全层、随机种子和任务几何。
- 每架飞机在任务开始后关闭 GNSS 融合，并用 ULog 核对任务飞行阶段内的外部视觉融合、GNSS 退出、状态有效性、创新拒绝、复位计数和着陆。
- 证据窗口在首条 `MAV_CMD_NAV_LAND` 前结束，避免把着陆阶段正常的 EKF 复位错误归因到任务飞行连续性；没有 LAND 命令时仍以日志末尾为界并保持 fail-closed。
- 当前视觉输入是 **Gazebo 位姿真值转发形成的外部视觉替身**，并非由虚拟相机图像和 IMU 求出的真实 VIO。
- 时延是本机墙钟测量；RTF 低于 1 时，墙钟延迟不能直接外推为实时飞行延迟。
- 这是 PX4 SITL + Gazebo Harmonic 物理仿真，不是 HITL，也不是实飞。

## 起飞准备修复与验证

修复前，PX4 的 OFFBOARD 状态等待与命令 ACK 等待会暂停速度/航向设定值流。PX4 可以接受命令，但在 500 ms 级别的设定值空档后退出 OFFBOARD，导致物理机体没有按任务链持续执行。

修复后：

- arm、takeoff 与 OFFBOARD ACK 等待期间持续发送零速度/当前航向保持设定值；
- OFFBOARD 状态轮询期间保持同一设定值流；
- 原有 3 秒命令期限、12 秒爬升期限、0.5 m 高度门槛和三次连续新鲜高度样本均未放宽；
- 任何已接受 arm/takeoff 后的失败仍进入 LAND 与落地确认路径，不允许盲目重试。

冻结前的三个开发场景均通过：

- D3D12 单机：`takeoff-dev-single-d3d12-20260927-6`
- D3D12 五机：`takeoff-dev-five-d3d12-20260927-6`
- stationary-physics 定向注入：4 个针对性测试全部通过

正式起飞稳定性序列 `takeoff-stability-d3d12-20260927-2` 的结果如下：

| 项目 | 结果 |
|---|---:|
| 冷启动轮次 | 10/10 |
| mission-ready | 50/50 |
| 安全着陆 | 50/50 |
| 完整起飞证据链 | 50/50 |
| 干净清理 | 10/10 |
| 总门槛 | **通过** |

## smoke 验证

`renderer-smoke-20260927-2` 的三个场景全部通过：

| 场景 | 结果 |
|---|---|
| default 单机 | 通过 |
| D3D12 单机 | 通过 |
| D3D12 五机启动 | 通过 |

三个场景的渲染证明、证据链和资源清理均完整。

## 正式 10 轮结果

| 轮次 | 后端 | 任务 | 着陆 | 尾部 p99 / max | RTF | 结果 |
|---|---|---:|---:|---:|---:|---|
| pair 1-1 | default | 1/5 | 5/5 | 152.972 / 285.455 ms | 0.5466 | 失败 |
| pair 1-2 | D3D12 | 5/5 | 5/5 | 24.099 / 67.477 ms | 0.9958 | 单轮通过 |
| pair 2-1 | D3D12 | 5/5 | 5/5 | 25.065 / 73.117 ms | 0.9925 | 单轮通过 |
| pair 2-2 | default | 5/5 | 5/5 | 190.949 / 251.877 ms | 0.7949 | 失败 |
| pair 3-1 | default | 1/5 | 5/5 | 194.272 / 262.547 ms | 0.5174 | 失败 |
| pair 3-2 | D3D12 | 5/5 | 5/5 | 28.798 / 73.807 ms | 0.9816 | 单轮通过 |
| pair 4-1 | D3D12 | 5/5 | 5/5 | 28.862 / 67.139 ms | 0.9831 | 单轮通过 |
| pair 4-2 | default | 1/5 | 5/5 | 208.249 / 280.727 ms | 0.4656 | 失败 |
| pair 5-1 | default | 5/5 | 5/5 | 211.612 / 247.619 ms | 0.7325 | 失败 |
| pair 5-2 | D3D12 | 5/5 | 5/5 | 26.775 / 85.802 ms | 0.9807 | 单轮通过 |

所有 10 轮都有有效渲染器证明、完整起飞链和干净资源清理。D3D12 的分布为：

| 指标 | 最小 | 中位数 | 最大 |
|---|---:|---:|---:|
| 尾部 p99 | 24.099 ms | 26.775 ms | 28.862 ms |
| 尾部 max | 67.139 ms | 73.117 ms | 85.802 ms |
| RTF | 0.9807 | 0.9831 | 0.9958 |
| 每轮任务 | 5/5 | 5/5 | 5/5 |
| 每轮着陆 | 5/5 | 5/5 | 5/5 |

default 的分布为：

| 指标 | 最小 | 中位数 | 最大 |
|---|---:|---:|---:|
| 尾部 p99 | 152.972 ms | 194.272 ms | 211.612 ms |
| 尾部 max | 247.619 ms | 262.547 ms | 285.455 ms |
| RTF | 0.4656 | 0.5466 | 0.7949 |
| 每轮任务 | 1/5 | 1/5 | 5/5 |
| 每轮着陆 | 5/5 | 5/5 | 5/5 |

## 配对差值

差值按 D3D12 减 default 计算；时延为负、RTF 和任务数为正表示 D3D12 更好。

| 配对 | p99 差值 | max 差值 | RTF 差值 | 任务数差值 |
|---|---:|---:|---:|---:|
| 1 | -128.873 ms | -217.978 ms | +0.4492 | +4 |
| 2 | -165.884 ms | -178.760 ms | +0.1976 | 0 |
| 3 | -165.474 ms | -188.740 ms | +0.4642 | +4 |
| 4 | -179.387 ms | -213.588 ms | +0.5175 | +4 |
| 5 | -184.837 ms | -161.817 ms | +0.2482 | 0 |

D3D12 对本机仿真吞吐的改善非常明确，但本实验的通过条件还要求没有持续尾延迟恶化。绝对值优秀不能覆盖冻结的趋势失败。

## 全部失败记录

D3D12 单轮没有失败代码。正式总门槛只有一个失败代码：

- `d3d12_sustained_tail_degradation`

default 对照轮的失败均被保留：

- pair 1-1：`mission_count_not_5`、`normal_run_vio_gate_triggered`、`per_vehicle_post_gnss_evidence_rejected`、`per_vehicle_gnss_disable_not_injected`、`raw_vio_max_not_below_250_ms`、`clock_max_not_below_250_ms`、`tail_p99_above_100_ms`、`rtf_below_0_95`、`operational_continuity_failed`
- pair 2-2：`raw_vio_max_not_below_250_ms`、`tail_p99_above_100_ms`、`rtf_below_0_95`
- pair 3-1：`mission_count_not_5`、`normal_run_vio_gate_triggered`、`per_vehicle_external_vision_evidence_rejected`、`per_vehicle_post_gnss_evidence_rejected`、`per_vehicle_gnss_disable_not_injected`、`raw_vio_max_not_below_250_ms`、`tail_p99_above_100_ms`、`rtf_below_0_95`、`operational_continuity_failed`
- pair 4-2：`mission_count_not_5`、`normal_run_vio_gate_triggered`、`per_vehicle_post_gnss_evidence_rejected`、`per_vehicle_gnss_disable_not_injected`、`raw_vio_max_not_below_250_ms`、`clock_max_not_below_250_ms`、`tail_p99_above_100_ms`、`rtf_below_0_95`、`operational_continuity_failed`
- pair 5-1：`tail_p99_above_100_ms`、`rtf_below_0_95`

default 在所有轮次均安全着陆，因此这些失败没有被删除或误报成坠机。

## 证据窗口修正

第一次完整重跑 `renderer-formal-20260927-1` 在最后一个 D3D12 轮被判失败。原始证据显示 GNSS 在仿真 86.916 秒关闭，LAND 在 98.616 秒发出，水平速度复位发生在 102.804 秒，地面接触约 103.524 秒，着陆状态约 104.196 秒。复位量只有约 `(+0.0022, -0.0075) m/s`，且发生在 LAND 后。

旧证据窗口把 LAND 后复位算入任务飞行连续性。修正按照独立设计补充 `86b2718` 完成，并在 `705f807` 中实现和测试：证据截止首条 LAND 命令；无 LAND 时保持原先的日志末尾 fail-closed 规则。旧失败原始目录保留，只读重评分通过后仍从头执行了新的 10 轮正式序列，没有拼接旧结果。

## 故障回归

本轮没有执行 120 ms 延迟和 400 ms 断流正式回归。冻结协议要求无故障 D3D12 稳定性总门槛先通过；本轮因趋势判据失败，所以在该边界停止。历史故障测试不能替代本提交和本冻结配置下的正式回归。

## 软件验证与资源释放

- 快照与 campaign 的 13 个定向测试通过；此前控制、证据与渲染相关的 190 个测试通过。
- 完整 pytest 采用已记录的既有间歇测试隔离执行：主套件 `543 passed, 1 deselected`；`tests/test_distributed_stress.py::test_four_independent_udp_processes_converge` 单独执行 `1 passed`。因此不能声称单次全量调用完全无间歇。
- 变更 Python 文件的 Ruff 检查通过，`git diff --check` 通过。
- 10 轮起飞稳定性、3 轮 smoke、10 轮正式试验都记录了 owned-process cleanup；最终核查未发现遗留的 PX4、Gazebo、relay、probe、worker 或训练进程。
- 紧凑证据包含每轮关键 JSON、清单和大型原始文件 SHA-256/大小索引；摘要中的长序列保存长度、原始序列 SHA-256 与首尾各四项。ULog、逐条 CSV/JSONL 和完整日志仍保存在本机原始结果目录。

## 下一步

下一个单变量候选是 **相机更新相位调度**：把五架相机/视觉更新在仿真周期内错峰，观察是否消除连续尾延迟恶化。它需要新的独立规格、冻结配置和从头运行的 smoke/正式序列；不能在本次冻结实验上事后调参。

只有新的无故障 D3D12 序列通过绝对门槛与趋势门槛后，才执行 120 ms 延迟和 400 ms 断流回归。随后应把 Gazebo 真值转发替换成真实的虚拟相机图像 + IMU VIO，再进入 HITL 和实飞。

## 证据位置

- 起飞稳定性紧凑证据：`docs/results/px4-takeoff-stability/takeoff-stability-d3d12-20260927-2/`
- 起飞稳定性原始证据：`results/px4-takeoff-stability/takeoff-stability-d3d12-20260927-2/`
- smoke 紧凑证据：`docs/results/vio-renderer-stability/renderer-smoke-20260927-2/`
- smoke 原始证据：`results/vio-renderer-stability/renderer-smoke-20260927-2/`
- 正式紧凑证据：`docs/results/vio-renderer-stability/renderer-formal-20260927-2/`
- 正式原始证据：`results/vio-renderer-stability/renderer-formal-20260927-2/`
- 每个紧凑目录中的 `raw-artifact-index.json` 记录未纳入 Git 的原始文件哈希与大小。
