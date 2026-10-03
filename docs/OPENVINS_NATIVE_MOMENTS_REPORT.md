# OpenVINS 原生速度与协方差离线审计（2026-10-03）

**结果：取得了固定上游 OpenVINS 的真实滤波器速度和 15×15 IMU 状态边缘协方差，但仍不能送入 PX4。** 新研究运行器对同一保存的开发回合只重放一次，325 帧原姿态/位置输出的 SHA-256 与上一回放**逐字节相同**（`422a0e507aa6568d752942b1019732dfd00618224da66cc5c7506f536867e080`）。所有新矩阵在原生误差排列下通过有限性、对称性和半正定结构审计。这个结果只证明读出接口和离线结构检查，没有证明协方差统计一致性或飞行安全。

## 上游与固定输入

研究适配器 [openvins_native_moments_probe.cpp](../tools/benchmark/openvins_native_moments_probe.cpp) 在原 runner-v3 的相同 IMU/相机输入顺序和原状态 CSV 写法之外，只读 `state->_imu->vel()` 与 [OpenVINS `StateHelper::get_marginal_covariance`](https://docs.openvins.com/classov__msckf_1_1StateHelper.html)。OpenVINS 上游提交仍为 `69488123ed9362dd44b6f28e7f4680abbff1442b`（[上游仓库](https://github.com/rpng/open_vins)，GPL-3.0），诊断库 SHA-256 `31e8a063018f256a32fe4027de37c146e49e2a3859a117e897f7eee6339921ae`；配置 SHA-256 `eaa40224f0de2f4c5b0f1d33504d215670544b9cc000252a0e92f404478360e6`，29 s 截取的相机/IMU 未改。新运行器源码/二进制 SHA-256 分别为 `d8ccc18d4fc7af8b7c90506e8a6ef7757dd9b2daa22de90c506ad4873d71f834` / `80526bd718aac0d5f25704ac60a28cd5ff0a196ed5f3bc67011d90dd517b652d`。首次编译漏加 `ov_init/src` include 而失败，没有运行回放；第二次补上 include 后编译成功，仅一次回放退出码 0。

原生 15 维误差排列由固定版本的 `ov_core/src/types/IMU.h` 确认为 `dtheta, dposition, dvelocity, gyro_bias, accel_bias`，每组 3 维。这里的 `dtheta` 是 OpenVINS 误差状态，不是 MAVLink `ODOMETRY` 的欧拉角协方差；整个矩阵也尚未转换到 PX4 所需的 [参考系和机体系](https://docs.px4.io/main/en/ros/external_position_estimation)。禁止把它直接填入 MAVLink 的协方差字段。

## 原始发现

新 `moments.csv` SHA-256 为 `bbefe17c716c20d725ebd1e5c0b5bfee441f32988cdb3028ee8f55343bb52e77`，保存 325 帧的三维原生速度和完整 15×15 边缘协方差。独立 [结构审计](../tools/benchmark/audit_openvins_native_moments.py)逐帧匹配原状态图像时间，记录的最小协方差特征值约 `5.30×10⁻⁹`；位置方差分量范围 `0.00276–2.239 m²`，速度方差分量范围 `0.0000624–0.0605 (m/s)²`，原生速度模长范围 `0.137–0.835 m/s`。结构通过不等于所报不确定性覆盖真实误差的比例已通过验证。

| 图像时间 | 前置审计中的相邻位置表观速度 | OpenVINS 原生速度模长 | 原生位置方差 x/y/z (m²) |
|---|---:|---:|---|
| 46.1 s | — | 0.403 | 0.871 / 0.346 / 0.0521 |
| 46.2 s | 4.680 m/s（46.1→46.2） | 0.469 | 0.471 / 0.0820 / 0.0519 |
| 46.3 s | 5.632 m/s（46.2→46.3） | 0.600 | 0.105 / 0.0336 / 0.0129 |

同一时段的保存 Gazebo 评分真值位移对应约 0.569/0.579 m/s，**只用于上一阶段独立评分**，没有进入本审计或估计器。位置差分与 OpenVINS 原生速度显著不一致，且滤波器自报位置方差在此时下降；这提示视觉更新造成了状态修正，但当前输出没有创新、重置计数和连续在线时钟，不能据此断言跳变的唯一原因，也不能认为方差下降代表估计正确。

重放的 `/usr/bin/time -v` 记录墙钟约 13.25 秒、用户 CPU 0.69 秒、系统 CPU 0.36 秒、最大常驻内存约 68 MB；这是 WSL 上读取已保存图像的离线进程指标，不包含 Gazebo/PX4 实时链路、图像传输、机载温度或整条控制决策延迟。

可复核证据的源、二进制、配置、输入清单、逐帧状态/矩阵、日志、资源、失败编译摘录和每个文件的 SHA-256 收在本阶段归档；[来源清单](../evidence/openvins-native-moments-dev-1701-provenance.json)记录 WSL Ubuntu 24.04.4、g++ 13.3.0、准确编译命令和一次回放。约 293 MB 的诊断共享库仅按哈希引用，所需上游插桩补丁保存在上一阶段 reviewed 归档（SHA-256 `bddd5f7999421b121c16ab1bc0bba655c75b077a2fe9b1275ddf488e80d0b3f6`）；单凭本阶段小归档不能逐字节重建该动态库。

验证：新审计针对性测试 `10 passed`，全量回归 `408 passed、1 warning`（204.79 秒）。唯一警告是项目已有的 MaleCNS 神经元组无匹配项。C++ 研究运行器成功构建并完成一次冻结输入回放；审计修正版在不重放的情况下重新核算，两个审计 JSON 逐字节一致。Ruff、归档成员哈希和 `git diff --check` 另行核验。

## 尚未满足的门槛

[PX4 EKF2](https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf)可消费外部视觉位置/速度/姿态及其不确定性，但当前原生矩阵尚未验证坐标转换与误差参数化、采样/到达时钟、实际相机–IMU 外参/时间标定、估计重置/失锁与质量、在线异常健康门控。这里没有发 MAVLink `ODOMETRY`，没有 PX4 EKF2 视觉融合 ULog，也没有 GNSS 丢失/相机暂停闭环。原回合仍为 `out_of_bounds`，控制器仍使用 Gazebo 真值；该读出不能提升其安全证据等级或作为 5/20 机门槛。下一步依赖是用开发轨迹验证相机–IMU 标定和帧/时钟转换，再做不驱动控制的在线 shadow 管线与健康失效注入。
