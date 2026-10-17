# WSL Agent 与 Docker ROS 2 收集器的网络边界（2026-10-12）

当前未解锁采集把固定 eProsima XRCE Agent v2.4.3 作为 WSL 内的受管进程启动；固定 `VehicleOdometry` ROS 2 收集器只在 Docker Humble 镜像中完成过合成发布者的 CDR/字段一致性测试。**这两个实现尚未在同一个 PX4 回合连接。** v12 的 Agent-inclusive 声明仍是离线准备；没有新的物理 capture、XRCE 会话、真实 DDS 样本或 EKF2 融合。

为确认部署拓扑，在无容器和相关进程时用同一固定 Docker 镜像 `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a` 运行两个 128 MiB、32 PID、有界的 UDP 发送器，WSL Python 只在非生产端口 18889 短时接收。Docker 使用本机 `--network host`：发送到 `127.0.0.1:18889` 时 `sendto` 返回 18 字节，但 WSL loopback 接收端 8 秒超时；发送到该回合 WSL 接口 `172.28.230.109:18889` 时，接收端读到精确的 23 字节 payload，发送源为 `172.28.224.1`。两次发送器 exit 0、监听器 exit 0；事后无对应容器或 18889 监听。`sendto` 成功本身不算交付，结论依据接收端记录。WSL 接口地址会变化，本次值不能写进未来固定运行配置。

这只证明本机当时 Docker→WSL 指定接口的一个 UDP 数据报可达，并观察到 Docker host 模式下 WSL loopback 没有收到数据。**不证明 DDS 发现、双向会话、Agent↔PX4 的 XRCE 身份、ROS 发布者 GID 对应 PX4、同回合 ULog 对照或相机/VIO 资格。** 因此不能只把已有 ROS 收集器放进 Docker、使用 localhost，就把 v12 Agent 监听称为 DDS 来源闭环。后一阶段须先冻结收集器与 Agent 的实际命名空间、DDS peer/domain/端口和启动顺序，在无物理的 bounded 接口试验中验证真实类型/发现，再于内存达原 4 GiB 门槛且无竞争进程时设计新 study ID 做一次未解锁 PX4/Agent/ROS/ULog 同回合试验。失败全保留，原 v12 不回填。由于 PX4 固定 logger 默认不含 `vehicle_odometry`，还须独立声明其诊断日志配置及额外负载；旧 ULog 不能做逐字段 DDS 对照。

固定实现依据：PX4 `d6f12ad`（BSD-3）的 `dds_topics.yaml` 声明 `/fmu/out/vehicle_odometry`；`rcS` 用 `PX4_UXRCE_DDS_PORT` 选择 UDP 端口，本采集设 18888。固定 Agent `73622810`（Apache-2.0）和 ROS 2 Humble/`px4_msgs` `148bdb4`（BSD-3）的许可证、版本、资源与采用原因已分别封存在 [Agent 接入报告](OWNED_AGENT_CAPTURE_INTEGRATION_REPORT.md)、[ROS 收集器报告](PX4_ROS2_FULL_ODOMETRY_JOURNAL_REPORT.md)与[合成 CDR 报告](PX4_ROS2_SYNTHETIC_V6_PARITY_REPORT.md)。本阶段复用这些固定版本，没有更新依赖、改变飞行或传感器负载。

证据位于 `results/wsl-docker-ros2-topology-dev-1701`，包括可重复探针、原始命令/回显、接收超时和精确 payload、资源释放与独立只读审计。宿主空闲内存检查仍低于全物理 4 GiB 门槛，故未启动 PX4/Gazebo/OpenVINS、训练或 Docker ROS 2 发布者。五机相机 WSL2 0.873 RTF < 0.95 和此前 v10 首次 TIMESYNC 拒绝保持失败状态。

| 状态 | 结论 |
| --- | --- |
| 已验证 | 本机指定 Docker→WSL UDP 接口可达；WSL loopback 未收到相同模式的数据报；探针进程、容器与端口已释放。 |
| 仅实现 | 可复核的非物理拓扑探针和严格不授予 DDS/飞行资格的审计。 |
| 未测试 | ROS 2 跨命名空间 DDS、同回合 PX4/Agent/ULog 身份、相机标定、VIO→EKF2、果蝇训练、集群。 |
| 仍失败 | 原 v10 TIMESYNC 门槛、五机 0.873 RTF 容量门槛；本次 loopback 接收超时。 |
