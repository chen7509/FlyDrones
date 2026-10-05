# 固定输入50 Hz IMU传播与接入契约

沿用用户持续授权：验证果蝇集群的真实传感器闭环依赖，不扩展机数，不请求逐项批准。前置PR31只证明41帧起飞前内部状态可诊断。下一依赖选上游已有 `Propagator::fast_state_propagate`，先导出并严格审计50 Hz原生传播输出，保留原10 Hz图像、250 Hz IMU、场景和配置。此阶段不发送MAVLink，不飞行，不宣称完整接入已实现。

## 研究与选择

已查源码OpenVINS GPL-3.0 `69488123ed9362dd44b6f28e7f4680abbff1442b`，固定库SHA `532ae57a6a952a0137cc1de291bc47ad556d419c7524fbb23b7a90c00addab5b`。仓库未归档，2026-10-05 API所见最后推送2025-11-30，不宣称持续活跃。Propagator.h/cpp明确接口13维(q_GtoI,p_IinG,v_IinI,w_IinI)、12×12协方差(theta_I,p_G,v_I,omega_I)，维护独立缓存而不直接更新滤波状态；普通视觉和ZUPT路径使缓存失效。源码承认快速离散协方差和角速度相关项近似，不把数值半正定当校准完成。论文仍为[OpenVINS ICRA2020](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf)。

[PX4官方外部定位说明](https://docs.px4.io/main/en/ros/external_position_estimation)建议30–50Hz；这是文档指导，不能据此断言固定固件硬拒绝10Hz。候选：①复用已有fast propagation，增加O(15³)小矩阵运算和序列化，实际RSS/耗时需测；②提高相机频率会改变冻结负载，拒绝；③复制旧位姿只改时戳不能产生新观测，拒绝。不升级上游或增加ROS运行时。

未来传输候选：已装pymavlink2.4.49（LGPLv3，生成代码例外不能当整库MIT），上游master `20111a041f3abfeda1c4b34dae43c0cd4441ef52`，未归档，最近推送2026-10-02；可复用MAVLink2序列化，无新ROS依赖。MAVROS ros2 `5c68b905ab30de6ce630822dc46c33467e8f23ea`，BSD/GPLv3/LGPLv3多许可，未归档，最近推送2026-09-27，作为坐标转换参考；部署ROS2增加适配与资源成本，本轮不采用。两者运行资源未实测。固定PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` mavlink_receiver.cpp支持LOCAL_FRD/BODY_FRD，但直接复制body-to-local姿态，必须在发送侧证明转换；[ODOMETRY定义](https://mavlink.io/en/messages/common.html#ODOMETRY)还要求时间、协方差、reset和quality语义。

## 调度与证据

在既有probe新增可选fast JSONL输出，默认路径行为不变。从第一帧到最后帧，20ms整纳秒网格。在每个网格时刻先馈入截至其后第一条IMU边界样本（与原相机馈送规则相同），再尝试传播；若同时有图像，则传播先于这张图像更新。记录last_camera_ns和available_imu_ns，禁止未来图像，边界IMU可能比状态目标晚≤4ms，必须明示这是离线缓冲依赖而非在线到达时延。原CSV仍在每张图像更新后生成，要求与封存SHA逐字节一致。

每行精确字段：target_ns、last_camera_ns（未见图像时null）、available_imu_ns、filter_time_s、camera_imu_offset_s、internal_initialized、public_initialized、success、filter_unchanged、propagation_wall_s、state13和covariance12。未初始化/传播失败时后两项null，保留失败行。内部已初始化才能调用传播，但不更改公共initialized门禁。比较调用前后滤波状态值、时间与IMU边缘协方差，发现任何改变直接失败；缓存变化不算滤波状态改变。

本固定配置CAM→IMU offset必须严格0；上游实现和注释的时间基语义存在非零offset需另核对的风险，本轮显式拒绝非零值，不把零offset验证推广。目标必须晚于滤波参考时刻。审计要求整数纳秒完整网格、实际IMU边界来自原CSV、last_camera精确等于目标前已处理的图像、有限数据、单位四元数±0.01、协方差对称/PSD1e-8。已有诊断成功之前允许非健康null行；丢失初始化/非健康传播保留拒绝。视觉年龄≤100ms、可用IMU比目标晚0–4ms、滤波参考不超前且≤100ms陈旧，作为本数据的结构性条件，不是通用飞行门槛。预解锁15.68–19.70秒应202个50Hz目标，逐行计数，不能丢尾帧。

## 未来消息契约与当前边界

本轮固定原生接口并测试健康/时间/形状；不完成或伪造PX4帧转换。未来消息必须证明JPL q_GtoI→Hamilton body-to-local wxyz、任意水平原点LOCAL_FRD而非未经证明的North、机体速度BODY_FRD、姿态误差协方差到消息坐标的雅可比及打包。时间需统一采样时刻与在线接收时刻；quality未知不能随意赋100，reset_counter必须来源于可跟踪会话/重置。完整契约验证前所有报告 `eligible_for_px4_fusion=false`，不生成可发送的伪造消息。依次完成固定输入传播、坐标/消息转换测试、在线未解锁影子、单机EKF2闭环。

冻结开发输入沿用PR30/31，输出新目录results/openvins-fast-propagation-dev-1701，所有失败保留；一次主回放证明调度/CSV奇偶性，异常审计使用其副本，不启动PX4/Gazebo。独立复核后封存ZIP/哈希和草稿PR，报告已验证/实现/未测试/失败及所有实际性能限制。
