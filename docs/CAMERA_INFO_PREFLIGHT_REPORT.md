# 单机相机信息预检（2026-10-02）

在原 1701 **开发**世界再次运行完整果蝇控制器，增加可选 Gazebo
`/benchmark/rgbd/camera_info` 原始 protobuf、稳定参数和哈希记录；现有 RGB
和 PX4 ULog 采集保留。没有改变世界、机体、控制限值、正式 20 场景或五机负载。
本次任务以 **`collision`** 结束（仿真任务 12.65 s、墙钟 167.49 s），不能称为
算法或安全通过；与上一回合 `out_of_bounds` 的差异不用于调参。
本分支全套回归 **312 项通过**（另有一条既存果蝇神经元映射警告），相关
Python 文件 Ruff 检查通过。

| 证据 | 本回合观测 | 判断 |
|---|---|
| RGB | 417 帧，单路 160×120、10 Hz；无逆序或重复 | 原始采集成功 |
| Gazebo `CameraInfo` | 417 条，稳定字段变化 0；首条原始 protobuf 已哈希保存 | 运行时内参可复核；相同消息数不证明逐帧时间配对 |
| 内参 `K` | `fx=fy=108.12401050876075, cx=80, cy=60` | 与 SDF 的 1.274 rad 水平视角公式一致 |
| 投影和畸变 | `P` 的焦距/主点一致；枚举模型 0、五个 0 系数 | 仅是 Gazebo 发布值，不是物理相机标定 |
| 完整采集对 IMU | 392/417 帧在 ULog `sensor_combined` 时间范围；25 帧过早 | 全程覆盖仍未通过；全部失败帧保留 |
| 决策窗口 | 29.0–41.5 s 的 126 帧全部在 IMU 范围；3126 个 IMU，最大间隔 4 ms | 20 ms 数据可用门槛通过，不证明校准或 VIO |
| PX4 ULog | 11,705,517 字节、9790 个 `sensor_combined`；基本主题门槛通过；外部视觉融合 0 | 仍使用 GNSS/其他现有融合，不是 VIO 闭环 |

运行时相机 `frame_id=camera_link`。仓库 `OakD-Benchmark/model.sdf` 指定
`rgbd_camera`、名义 160×120/10 Hz/1.274 rad；包含它的
`x500_benchmark/model.sdf` 指定安装位姿 `.12 0 .242 0 0 0` 和到
`base_link` 的固定关节。本机 PX4 `x500_base/model.sdf` 的 IMU 标注
`gz_frame_id=base_link`。这些文件**尚不能独自证实** Gazebo 渲染光学坐标
到 IMU 坐标的完整旋转、SDF merge 后的实际变换或相机–IMU 时间偏移。
Gazebo [相机 API](https://gazebosim.org/api/sdformat/15/classsdf_1_1SDF__VERSION__NAMESPACE_1_1Camera.html)
也区分 Gazebo 朝向 +X 的相机框架与其他视觉工具朝向 +Z 的框架；在验证
投影方向前不能直接把 `camera_link` 传给 OpenVINS。

原始证据在 `evidence/fly-ego-camera-info-preflight-1701.zip`，逐文件 SHA-256
见同名 `.sha256.json`；独立解包核对 **434/434 文件**，ZIP SHA-256 为
`b9250516b8504640d0eb75fc6b77033b5c28abb4b57a88caf572f7ac7802a5c2`。
相机首条 protobuf SHA-256 为
`6d2ed00a687f29103f8c48e5f49fedd4b0b903852682cc2c8b6592eb6e3b1437`；
ULog SHA-256 为 `1d012d6494b94cc8d76281945255aa4929f704a875e43cdf29bc4bc06faf1b86`。
PX4 源码 HEAD 是 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`，工作树有
`Tools/simulation/flightgear/flightgear_bridge`、`Tools/simulation/gz` 和
`src/modules/sensors/vehicle_imu/VehicleIMU.cpp` 三处本地修改，故单凭 HEAD
**不能**复现二进制；本次 PX4 可执行文件 SHA-256 为
`e8af7cbcac255ec3c79bb5fa278459fd0b130b4b189de9269e3689cb9789f4cb`。
相机 SDF、机体 SDF、PX4 基础机体 SDF SHA-256 分别为
`806c532bd2a22e9caa85d79bf5fd974d7ce02b1eb660df7802c1fc557f4ae5fe`、
`ff8eaa1dbb73b77d693e1d29908bc0ebee6ffa64311951e133db38fda82e7ee9`、
`e807dca3406f7cd5cb3d545898601c3ec17e0e5242e25cf467a69df1812cf436`。

本阶段依然没有实际图像推算位姿、协方差或 PX4 EKF2 外部视觉融合。下一步
需要在**开发**世界作光学框架到 IMU 的投影与变换核验，取得明确的时间偏移
和测量噪声配置；随后才可把固定上游版本的 OpenVINS 用于离线烟测。所有
控制器现仍用 Gazebo 模型真值里程计，WSL2 五机相机均值约 0.873 RTF 的
容量门槛仍失败，不能因单机信息采集成功而更改结论。
