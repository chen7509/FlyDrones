# 固定 Agent 在 Humble 镜像重建的资源前置检查（2026-10-12）

已完成 [设计](superpowers/specs/2026-10-12-agent-humble-rebuild-design.md)和[执行计划](superpowers/plans/2026-10-12-agent-humble-rebuild.md)，但**没有启动构建容器，也没有产生新的 Agent 二进制**。要将固定 Agent v2.4.3 与 ROS 2 Humble 类型化收集器放在同一 Docker DDS 网络，不能直接复制旧 WSL 运行包：已封存的 [部署可行性报告](DDS_COLOCATION_FEASIBILITY_REPORT.md)证实两个动态库需要 GLIBC 2.38，而固定镜像只有 2.35。下一候选是相同源、相同已封存依赖在该镜像内无网络重建，绝不改名换版本。

本次严格前置检查在未创建容器前观察到宿主可用物理内存 **562,184,192 字节（约 536 MiB）**，低于针对 1 GiB 限额、单作业离线构建预定的 2 GiB 宿主空闲条件，因此状态为 `preflight_refused`。Docker 当时无运行容器；固定 Humble 镜像摘要与前次封存一致；只读 WSL 源中已经审计的 `SuperBuild.cmake` 补丁 SHA-256 仍为 `9621355850e1095dcd2983a7c3573010453ec4b816350c205bdb32ebf6aaf640`。没有 CMake 配置、编译、XRCE、DDS、PX4、Gazebo、训练或飞行。这个拒绝是资源边界，不是 Agent 源码或果蝇算法失败。原全物理 4 GiB 门槛也未改变。

前置脚本和原始命令/内存响应保存在 `results/agent-humble-rebuild-preflight-dev-1701`；独立只读审计确认所有构建、DDS 与 PX4 来源资格仍为 false。脚本 `py_compile` 和完整 Ruff 检查通过。未来仅在宿主空闲达到独立 2 GiB 构建前置条件、无竞争容器且源/镜像重验通过时，才新建输出目录并按计划尝试一次限额构建，保留配置/编译/清理全部结果。即使构建通过，还需真实 XRCE 客户端、DDS 类型化收集器与未解锁 PX4/ULog 的逐级证据。v12 只有离线准备，五机相机 0.873 RTF < 0.95 及 v10 首次 TIMESYNC 失败原样保留。

| 范围 | 状态 |
| --- | --- |
| 已验证 | 固定源补丁和镜像身份、无运行 Docker 容器、内存低于独立构建门槛、启动前拒绝。 |
| 仅设计 | 同版 Agent 在 Humble 镜像的有界离线重建及后续 ABI/进程审计。 |
| 未测试 | 新构建、XRCE/DDS 真实接口、PX4/Agent/ULog 同回合、VIO/EKF2、完整学习及集群。 |
| 仍失败 | 本次构建前置资源拒绝；历史 TIMESYNC 与五机容量门槛。 |
