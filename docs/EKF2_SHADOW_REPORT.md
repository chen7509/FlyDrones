# 固定开发回合的 PX4 EKF2 离线影子审计（2026-10-03）

**结论：629 张 RGB 帧中有 604 帧能对齐到 100 ms 内的 PX4 局部位置、姿态和估计器状态；在本阶段预设的完整健康门槛下，0 帧合格。** 前 25 帧发生在相关 PX4 记录开始前；其余 604 帧全部被 `heading_good_for_control=false` 标记为不健康，其中前 11 帧还伴随水平位置/速度无效与 dead reckoning。这个结果是保存 ULog 的离线诊断，不是果蝇策略的失败率，也不能证明视觉里程计已送入 PX4。原回合仍为 `out_of_bounds`，控制里程计和相机位姿仍来自 Gazebo 模型真值。

输入为唯一固定的 `evidence/openvins-texture-dev-1701.zip`，SHA-256 `82f9377c1ad11f824064e1cbbc5feb834f77803af3ec83d00bfb0c8355072ddd`；归档中的 ULog SHA-256 为 `5f7cbc3c11ca53e92a64a6d58aed957f6ecf3034618756bc95f0912fac125e55`。程序验证整个归档、722 个文件的索引和内容、RGB 帧清单、ULog 清单及原结果，再把 ULog 临时解包给 `pyulog`；不修改源证据。报告 [逐帧 JSON](../evidence/ekf2-shadow-dev-1701.json) SHA-256 为 `b63df19864ecfc868449af5a0f00ddf8664c99c743907f61aece041f5b6b8af8`，保留每一帧的状态、失败原因、所用样本时间与年龄、NED 位置/速度及显式 ENU 轴变换。

| 预设指标 | 固定回合结果 |
|---|---:|
| RGB 帧，2 ms–62.8 s | 629 |
| 三项高频 EKF2 样本均存在且不晚于帧、年龄 ≤100 ms | 604 |
| 高频样本同时通过全部位置、速度、航向、姿态和滤波器健康条件 | 0 |
| 完整逐帧状态：有效 / 无效 / 缺失 | 0 / 604 / 25 |
| 失败原因：航向控制无效 / dead reckoning / XY 与水平速度无效 | 604 / 11 / 11 |
| 来源标志：GNSS / 所查 GNSS 与外部视觉位均未置位 / 标志未取得；**按全部帧计** | 593 / 12 / 24 |
| 来源标志：外部视觉 / GNSS；**按健康估计帧计** | 0 / 0 |

局部位置、姿态、估计器状态分别从 ULog 的 2.424、2.444、2.424 s 开始，最后均覆盖到 62.848 s；其对齐样本年龄中位数分别为 4、0、3 ms，最大为 8、4、16 ms。来源标志仅有 70 条，最早 2.392 s、最晚 61.856 s；被选中的来源标志年龄中位数 448 ms、最大 988 ms，故只描述稀疏控制状态，不能宣称逐帧视觉融合。报告中的 `gnss` 是 `estimator_status_flags.cs_gnss_pos`，`external_vision` 是 `cs_ev_pos`；JSON 的 `source=none` **仅表示这两个被检查的标志均为 0**，没有排除光流等其他定位来源。这里没有任何健康帧，也没有可据此宣称的健康视觉融合帧。所有失效和早期缺失都保留，未用未来样本填补。

判定阈值在实现前固定：高频样本 ≤100 ms，稀疏来源标志 ≤2 s；要求 `xy_valid`、`z_valid`、`v_xy_valid`、`v_z_valid`、`heading_good_for_control`，拒绝 dead reckoning、非零 `filter_fault_flags`、非有限状态和失范四元数。`estimate_timely` 与 `estimate_healthy` 独立统计，以免把稀疏来源标志缺失误写成高频估计器故障。对非二值或非有限来源标志显式标为无效。**`heading_good_for_control=false` 的直接物理原因尚未在本审计中确认**；在未核对 PX4 控制模式、偏航观测与重置日志前，不应归因给训练或 VIO。

此次没有相机与 IMU 时间基/外参在线标定，没有从 PX4 提供非真值的相机位姿，也没有把 OpenVINS 输出输入 EKF2；`eligible_for_live_capture=false`。下一步应在不改变原回合的条件下只读核查航向无效原因与 EKF2 源切换日志，随后才设计在线影子生产器、校准和故障注入。它不满足单机安全闭环门槛，不支持升级 5/20 机、HITL 或实飞。

复现命令在 WSL Ubuntu 中使用 `python3 tools/benchmark/audit_ekf2_shadow.py --archive evidence/openvins-texture-dev-1701.zip --index evidence/openvins-texture-dev-1701.sha256.json --output <新的空路径>`；已有输出将被拒绝覆盖。EKF2 相关针对性测试 **21 passed**，全量 Python 回归 **484 passed、2 warnings**（205.88 秒）；两个警告分别来自故意构造重复 ZIP 成员的拒绝测试，以及既有 MaleCNS 神经元组无匹配项。Ruff 与 `git diff --check` 通过。独立代码复核确认归档/报告哈希、629 帧计数、逐帧状态和样本年龄，并指出“两个来源位均未置位”不能扩大为“无位置来源”；上表与解释已修正。
