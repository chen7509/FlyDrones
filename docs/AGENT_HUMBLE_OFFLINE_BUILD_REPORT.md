# 固定 Agent 在 Humble 镜像的离线重建（2026-10-12）

本阶段按[设计](superpowers/specs/2026-10-12-agent-humble-rebuild-design.md)和[计划](superpowers/plans/2026-10-12-agent-humble-rebuild.md)，在固定 ROS 2 Humble 镜像 `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a` 内，使用此前封存的同版 Micro-XRCE-DDS Agent v2.4.3 源码和九个本地 Git 对象库，**无网络、单作业**成功重建。构建前宿主空闲物理内存 2,770,305,024 字节，超过这项离线构建独立的 2 GiB 门槛；容器限制 1 GiB、无 swap、1 CPU、128 PID，构建限时 1500 秒。物理 PX4/Gazebo 与完整 MaleCNS 的 4 GiB 门槛没有改变。固定 `SuperBuild.cmake` SHA-256 前后均为 `9621355850e1095dcd2983a7c3573010453ec4b816350c205bdb32ebf6aaf640`。

首次尝试 `results/agent-humble-offline-build-dev-1701` 在配置后因容器 root 与 WSL 用户拥有的只读 Git 对象库触发 Git 安全目录拒绝，构建退出 2；第二次 `-v2` 在 Docker 启动前因 WSL 从 Windows 工作树解析 `.git` 指针失败，未配置或编译。两次输入、日志和失败都保留。第三次 `-v3` 仅为九个精确对象库设置 `safe.directory`，并从 WSL `/tmp` 调用 Git；CMake 配置和构建均退出 0，构建容器已清理。所有检出提交与已固定来源相符：XRCE Client `d44dc3f`、Micro-CDR `3d1b177`、Fast-CDR `757d5e4`、Fast-DDS `575d045`；Fast-DDS 子模块状态另有原始日志。镜像提供 `libspdlog1` 和 ROS Humble foonathan vendor 包，不能把它们说成这次独立源码编译。

产物 `MicroXRCEAgent` SHA-256 为 `3918279bd7c3ae3a76a5338bd1b31a52e334c4e6c1d648141b0adca65a2d6d8e`。六个生成 ELF 的最高 `GLIBC_*` 需求是 **2.34**，固定镜像为 glibc 2.35。镜像内对主程序的 `ldd` 无缺失依赖，`--help` 输出预期 CLI；在**无网络**容器内用 DDS 模式启动 UDP4 端口 18891，记录 `running...`，3 秒受控超时退出 124，容器消失。运行包 `runtime-bundle.tar.gz` SHA-256 为 `4279d999c02836e3f7076e948d2e92aefcc08bf62ea8c0e3e597dde2896c3262`；独立审计逐项比对六个 ELF 的包内哈希，重新解压到全新目录，并在同一镜像以原 `/work/build` 路径重做 `ldd`、CLI 和 18892 端口的有界监听，均通过。这个包依赖固定镜像提供的系统库及内嵌构建路径；未证明可在任意 Linux 主机直接运行。

首版 ABI 审计错误地假定镜像有 `file` 命令，并将两个系统包当作源码检出；第二版进一步发现单独对两个从属库执行 `ldd` 时缺少主程序的 RUNPATH 上下文。失败审计原样保留；第三版以显式构建库路径核查**每个** ELF 的闭包，并与主程序不设置额外库路径的启动及解压包启动分别验证。独立审计 `issues=[]`。`--help` 本身退出 1 是该 CLI 的行为；监听退出 124 是预定 `timeout`，均不冒称应用崩溃或真实会话。

| 范围 | 状态 |
| --- | --- |
| 已验证 | 同版固定源在 Humble 镜像离线构建；提交/产物哈希、glibc 与加载器、无网络受控 UDP 监听、包内重放和 owned 容器清理。 |
| 仅实现 | 可在固定镜像 `/work/build` 路径运行的 Agent 包。 |
| 未测试 | 实际 XRCE Client 会话、DDS participant/topic 可见性、`px4_msgs` 类型化采集、未解锁 PX4 与 ULog 同回合来源认证、VIO→EKF2、学习及集群。 |
| 仍失败 | 两次构建前置/配置失败和两版审计假设失败均保留；既有首个 TIMESYNC 超时及五机 0.873 RTF < 0.95 不变。 |

证据在 `results/agent-humble-offline-build-dev-1701*` 及 `evidence/agent-humble-offline-build-dev-1701.zip`，含构建限额/日志、失败尝试、源码提交、每个 ELF 的哈希与版本、独立审计和完整运行包。后续先用这个产物做有界真实 XRCE→DDS 接口检查，再研究与未解锁 PX4/相机/EKF2 的同回合来源绑定；本阶段绝不声称 DDS 链路或融合已经通过。
