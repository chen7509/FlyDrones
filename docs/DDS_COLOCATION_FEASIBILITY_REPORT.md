# 固定 Agent 与 ROS 2 收集器同域部署可行性（2026-10-12）

**单向 UDP 可达不等于现有 WSL Agent 能与 Docker ROS 2 收集器构成 DDS 证据链。** 前阶段证明 Docker 可向 WSL 接口发送一个数据报。本阶段在无 PX4/Gazebo/OpenVINS/Agent/训练进程和无运行容器时，反向测试 WSL→Docker，并核对现有 Agent 运行包与固定 ROS 2 Humble 镜像的 ABI。未启动任何物理仿真或 ROS 2 发布者；v12 离线声明、历史失败和门槛未变。

在本机本次网络状态下，用同一固定镜像 `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`、每次 128 MiB/32 PID、非生产 UDP 端口 18890：

| Docker 接收方式 | WSL 目的地址 | WSL `sendto` | 容器实际接收 |
| --- | --- | ---: | --- |
| `--network host` | WSL 默认网关 `172.28.224.1` | 22 字节 | 8 秒超时 |
| `--network host` | Docker host 接口 `192.168.65.3` | 24 字节 | 8 秒超时 |
| 默认 bridge，`-p 18890:18890/udp` | WSL 默认网关 `172.28.224.1` | 24 字节 | 收到逐字节一致 payload，来源 `172.17.0.1` |

三个接收进程均正常退出，精确命名的自有容器均释放；只有接收端记录算交付，`sendto` 返回长度不算交付。地址会随本机网络变化，不能硬编码进后续 PX4 配置。显式发布 UDP 端口是本机可用的 **WSL→Docker 传输候选**，尚未测试双向 XRCE 会话，更没有 DDS 发现或源身份认证。

固定 WSL Agent v2.4.3 可执行文件 SHA-256 为 `ded56cf545394670effaf112c642d62e8dd0e7145e53a6c9b0593014b721fcfe`。只读 `readelf` 表明可执行文件最高需 GLIBC 2.34，但其固定 `libfastrtps.so.2.14.7` 和 `libmicroxrcedds_agent.so.2.4.3` 均需 GLIBC 2.38；固定 Humble 镜像实际提供 glibc 2.35。**现有运行包不能不经重建就搬进该镜像。** 这不是 Agent 协议失败，更不涉及果蝇学习性能。固定 Agent 源和依赖版本、许可证（Apache-2.0）及构建成本见 [离线构建报告](AGENT_OFFLINE_BUILD_REPORT.md)；固定 PX4 `d6f12ad`（BSD-3）和 ROS 2/`px4_msgs` `148bdb4`（BSD-3）的选择见 [收集器报告](PX4_ROS2_FULL_ODOMETRY_JOURNAL_REPORT.md)。本次没有替换上游版本。

最直接的后续候选是在已固定的 Humble 镜像内以相同 Agent v2.4.3 源和封存依赖另做有界构建、哈希/动态库审计，使 Agent 与类型化收集器处于同一 Docker DDS 网络；先用合成 XRCE 客户端验证端口发布和真实 DDS 类型回调。PX4 固定 `rcS` 当前只给 `uxrce_dds_client start` 指定 UDP 端口，默认本地目标与容器公开端口之间还需要事前声明且隔离的主机目标配置或受管双向转发，不能默默修改 v12。先证实真实 XRCE 客户端与 Agent 会话、DDS 发现/类型化 CDR，之后才在内存与安全门槛通过时新建一次未解锁 PX4/Gazebo 物理 study，核对 ULog、时钟、源健康和已标定相机。旧 PX4 ULog 缺 `vehicle_odometry`，如需逐字段对照还要预先配置隔离的诊断 logger，并将额外负载与公平容量测试分开。

原始命令、发送长度、接收端 payload/超时、动态库符号表、哈希及 fail-closed 审计封存在 `results/dds-colocation-feasibility-dev-1701`。两个脚本通过 `py_compile` 与完整 Ruff 检查；审计只授予本机数据报路径与 ABI 不兼容结论，`dds_discovery_verified`、`xrce_session_verified`、`px4_source_authenticated` 和 `fusion_qualified` 全为 false。宿主空闲内存复查约 2.17 GiB，仍低于原 4 GiB 全物理门槛，未启动 PX4/Gazebo。五机相机 0.873 RTF < 0.95 与 v10 首次 TIMESYNC 失败仍保留。

| 范围 | 状态 |
| --- | --- |
| 已验证 | 本机显式发布的 WSL→Docker UDP 单报文交付；两种 Docker host 地址本次超时；现有 Agent bundle 与固定 Humble glibc 不兼容；资源释放。 |
| 仅实现 | 可重复、无飞行授权的网络和 ABI 诊断与审计。 |
| 未测试 | Docker 内重建同版 Agent、真实 XRCE/DDS、PX4/Agent/ULog 同回合、相机/VIO/EKF2、学习及集群。 |
| 仍失败 | 两个 host-network 接收超时；历史 TIMESYNC 与五机容量门槛。 |
