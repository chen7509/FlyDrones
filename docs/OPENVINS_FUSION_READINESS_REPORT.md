# OpenVINS 到 PX4 EKF2 的融合前置审计（2026-10-03）

**结果：当前离线 VIO 轨迹不具备接入 PX4 EKF2 的证据条件。** 已保存的单机开发回放虽然在全程离线、无缩放刚体配准后有 0.341 m ATE RMSE，但两次连续的逐帧位移在 46.1–46.3 s 产生 4.68 和 5.63 m/s 表观速度。现有输出只有姿态与位置，缺少速度、协方差、重置事件、质量、坐标系、在线到达时间与经验证的相机–IMU 标定。审计器一律给出 `eligible_for_px4_fusion=false`，没有发送 MAVLink 或修改 PX4。

## 固定来源与复核方法

- 源重放仍是 [延迟输入诊断](OPENVINS_DELAYED_FEED_REPORT.md)的一次 OpenVINS 离线回放，上游提交 `69488123ed9362dd44b6f28e7f4680abbff1442b`。`states.csv` SHA-256 为 `422a0e507aa6568d752942b1019732dfd00618224da66cc5c7506f536867e080`；回放命令 JSON SHA-256 为 `81a12a53c9b863af25230a40446798316cfa4e1a347c8b8678a35833c4b2e8c3`。
- 审计脚本仅读原始 `states.csv`；不导入真值，也没有 PX4、Gazebo 或 OpenVINS 新回放。原指令速度上限 0.8 m/s，配置 SHA-256 为 `316db1b30fc2aaaebdebb5c4d6446a42eb9a0a6af571f53579627ae89298474f`。把其两倍 1.6 m/s 预先选为**明显异常筛查阈值**，不把它解释成飞行许可门槛或机体物理速度上限。
- [审计原始 JSON](../evidence/openvins-vio-fusion-readiness-dev-1701.json) SHA-256 为 `807a5702247d5f27d7aeb481dcda82f0a30c7a238031691ba4e94cab738fd99`，包含源文件哈希、阈值、全部异常帧和缺项。输出目录已存在时 CLI 拒绝覆盖；原始重放和上一阶段 reviewed 归档保持不变。

| 帧区间 | VIO 位移 / 表观速度 | 同期 Gazebo 评分真值位移 / 速度 |
|---|---:|---:|
| 46.1→46.2 s | 0.468 m / 4.680 m/s | 0.0569 m / 0.569 m/s |
| 46.2→46.3 s | 0.563 m / 5.632 m/s | 0.0579 m / 0.579 m/s |

真值仅在审计**完成后**从原保存回合 `result.json`（SHA-256 `4fe7bd9b62a5f021e0816d9fd22cfb4448562ec8483bd6b8602137c6ef42c380`）读取，用于独立说明异常；它没有进入估计器或审计器。VIO 坐标系与世界坐标系不同，所以这里比较的是逐帧位移模长，不是绝对位置。不能凭这两次突变确定具体原因是特征修正、标定误差、时间同步还是估计复位；当前输出没有相应内部状态可判别。

## 进入在线融合前的缺口

[PX4 EKF2 文档](https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf)要求明确定义外部视觉融合分量，并使用合适的视觉不确定性；[MAVLink `ODOMETRY`](https://mavlink.io/en/messages/common.html#ODOMETRY)可携带姿态/速度协方差、重置计数和质量。[OpenVINS 边缘协方差 API](https://docs.openvins.com/classov__msckf_1_1StateHelper.html)提供提取候选数据的上游接口，但本项目的 ROS-free 离线运行器还没有输出这些字段。下一小节应先从**上游真实状态**提取速度/协方差/重置线索并核对坐标系和时间基，不能补固定“好看”的协方差；再做独立相机–IMU 时间/外参标定和多运动/光照开发数据验证。只有经过这些门槛，才可在单机 shadow 模式设计受健康门控的 PX4 `ODOMETRY` 输入，并用 ULog 检查视觉融合、创新、估计复位和故障降级。

目前原飞行结果仍为 `out_of_bounds`，控制策略用的是 Gazebo 真值里程计，VIO 从未反馈给 PX4。此次只是离线开发审计，既不证明自主安全，也不能作为 5/20 机扩展门槛。

实现验证：针对性测试 `5 passed`，全量回归 `392 passed、1 warning`（197.37 秒），Ruff 和 `git diff --check` 通过。warning 是既有 MaleCNS 神经元组无匹配项，与本次审计无关。测试覆盖帧定位、输入损坏和拒绝覆盖；它们不代替在线融合与故障注入试验。
