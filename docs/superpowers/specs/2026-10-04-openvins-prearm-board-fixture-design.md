# 预解锁可见纹理板开发场景设计

## 目的与当前证据

固定的种子 1701 PX4/Gazebo 采集有 4.022 秒预解锁静止 RGB/IMU 窗口，但 [逐帧诊断](../../OPENVINS_INIT_FEATURE_TRACE_REPORT.md)显示 40 次 OpenVINS 初始化尝试的特征库全为 0；原飞行越界，离线 VIO 初始化迟于预解锁窗口且 ATE 很大。下一步只回答一个小问题：**在机体和估计器完全相同、静止时相机确实看见近距离纹理时，固定上游 OpenVINS 能否在起飞前获得两半时间窗所需的轨迹并完成初始化？** 不以改变正式世界或降低门槛来“修好”对照结果。

## 上游与选择

沿用 [OpenVINS 固定提交](https://github.com/rpng/open_vins/tree/69488123ed9362dd44b6f28e7f4680abbff1442b) `69488123ed9362dd44b6f28e7f4680abbff1442b`（GPL-3.0，C++/OpenCV；已在本机编译，2026 年仍有上游活动）及其[静止初始化说明](https://docs.openvins.com/classov__init_1_1StaticInitializer.html)；不用新特征网络或 PPO，更不改变 15/15 特征数及视差阈值。复用项目现有的 `write_sdf`、`has_route`、`make_vio_texture_fixture` 和 PX4 runner。SDF 1.9 的[官方形状规范](https://sdformat.org/tutorials/specification/spec_shapes/)区分视觉、碰撞和材质；本实验选择**视觉与碰撞一致**的静态板，避免只渲染一个不会碰撞的假障碍。相比开发新渲染器/跟踪器，此方案不增加运行依赖，主要代价是一回合约数分钟的 WSL 慢速物理仿真和一回合离线回放。

## 独立场景

严格从原种子 1701 的公开开发世界复制，保留物理步长、风、原柱体、起终点、相机内外参、PX4 和控制器。仅在起点前方 `x≈-5.5 m`、中心航道两侧增加两块静态薄板：左板 `x=[-5.52,-5.48], y=[-1.55,-0.75], z=[0.1,1.4]`，右板对应 `y=[0.75,1.55]`。中间净宽 1.5 m，超过已定义的 0.37 m 机体包络的双侧要求；仍需用项目 `has_route` 检验并在 SDF 中逐块核对碰撞/视觉。现有 deterministic 地面/障碍物纹理函数给两块板着色；不添加新的纹理算法。这样它们在低位前向相机约 2.5 m 处占据足够像素，但“预计可见”只是几何假设，必须用实采 RGB 验证。

新增一次性 `make_prearm_board_fixture.py`：仅接受未改的种子 1701 开发世界，拒绝已有输出目录，在全新目录写 `world.json`、`world.sdf`、两张纹理及来源/生成哈希；原世界和正式冻结场景只读。仍由现有 `run_episode.py` 的 `--development-prearm-stationary-s 4 --development-texture-dir ... --record-rgb --record-camera-info` 采集，不能加 freeze manifest。测试初始状态保证没有本实验遗留 PX4/Gazebo 进程，然后只启动一回合。离线导出/回放使用与前次相同版本、配置和日志补丁，保留原始图像、IMU、ULog、失败轨迹、状态和逐帧诊断，不覆盖旧证据。

## 判定与边界

先验证两板确实在预解锁图像中出现，40 张 RGB 与 IMU 连续性、EKF2 低速和有效状态维持；再看预解锁期的真实 OpenVINS 特征库、两半 15/15 数量门槛、最终初始化时刻和离线 VIO 误差。若板在图像中不可见，记为**场景接入失败**；可见而特征仍为 0，记为**前端特征缺口**；特征足够仍不初始化，继续查 IMU/静止/标定，不能只加训练；初始化成功也不等于定位精度或 PX4 闭环成功。所有结果保持“单机 PX4/Gazebo 采集 + 离线 VIO”标签，禁称 HITL、实飞或正式 20 个未见场景。即使本开发场景有改善，也必须另做真实场景泛化、故障注入和安全闭环。
