# OpenVINS 延迟输入开发诊断

## 问题和范围

保存的单机 PX4/Gazebo 回合在 29–33 s 静止预奏内满足 EKF2 离线低速条件，但 OpenVINS 读取整个 2.5–65.9 s 相机/IMU 流时已于 26.2 s 静止初始化；当时 EKF2 估计约 0.4 m/s。需要分开检验“初始化发生在运动阶段”与“当前相机–IMU 几何/时间和视觉估计本身不足”两种解释。只使用已保存的开发回合，截取从 29.0 s 开始的同步输入；不重跑 PX4/Gazebo、不改控制器、纹理、OpenVINS 配置/库/运行器或视觉门槛，不碰正式测试世界。该诊断不能证明真实世界性能，也不能靠 Gazebo 或 EKF2 真值引导估计器。

## 依据

[OpenVINS 初始化器文档](https://docs.openvins.com/classov__init_1_1InertialInitializer.html)说明有标定时可尝试静止初始化，且可等待运动激励；[静止初始化器](https://docs.openvins.com/classov__init_1_1StaticInitializer.html)以设备静止为前提。当前冻结配置 `init_dyn_use=false`、`try_zupt=true`、`init_window_time=2.0`，因此按时间截取后需要核验实际日志，而不能仅凭配置宣称静止初始化成功。[OpenVINS 标定指南](https://docs.openvins.com/gs-calibration.html)指出相机–IMU 时间/外参误差可迅速损害动态轨迹估计，下一步仍需要独立标定。

## 设计与门槛

从已核验的 `input-v1/imu.csv` 和 `frames.csv` 逐行筛出时间戳不少于 29.0 s 的条目，保留原数值、单位、帧相对路径和时间戳顺序，最末图像不能超过最后 IMU。只允许固定 29.0 s 截点；导出目录已存在时拒绝覆盖。输出原/新流哈希、样本数、首末时间与源回合/配置/运行器哈希。对截后输入仅运行一次相同上游 OpenVINS 回放，保存 stdout/stderr/exit、states 和资源。核对首次初始化时刻与其前两秒 PX4 EKF2 速度/有效位、可视更新次数、无缩放刚体对齐 ATE、越界失败和估计速度。若未初始化或视觉无效，保留失败，不更换截点或调参来求通过。

这项实验是一个**延迟启用 VIO 的离线反事实**，不代表 GNSS 拒止起飞方案：29 s 之前的真实飞行状态仍由 PX4 自身估计/控制维持。即使估计改善，也不能将它称为 PX4 EKF2 视觉融合、安全闭环或果蝇方案胜利。
