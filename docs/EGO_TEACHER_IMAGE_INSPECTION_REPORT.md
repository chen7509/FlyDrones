# EGO-Swarm 教师镜像身份检查（2026-10-09）

**结论：镜像身份与内部上游副本检查通过；教师轨迹、PX4/Gazebo 采集和完整连接组训练仍未运行。**

Docker Desktop 已运行。检查固定镜像 ID `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`，在只读、无网络、256 MiB/0.25 CPU、限定进程数的临时容器中读取上游 Git 提交、工作树、原始本地远端配置、ROS 可执行文件和两个安装二进制的 SHA-256。命令使用 `--pull=never`，容器有独立名称和 15 秒内部期限；宿主命令输出按 64 KiB 上限流式读取，超时清理只针对本次容器。完整命令及输出见封存证据。

上游副本为 `ZJU-FAST-Lab/ego-planner-swarm`，提交 `23a8d5a191711dd65633df689bd00f55d4dea8f9`，工作树无改动，原始 `remote.origin.url` 只有 `https://github.com/ZJU-FAST-Lab/ego-planner-swarm.git`。`ros2 pkg executables ego_planner` 列出 `ego_planner_node` 和 `traj_server`。安装二进制 SHA-256 分别为 `7d3a4a03c6d0da40e53a13d649aabf4583ffa82a43d651527149a9047634d6af` 和 `f000be1f92859905dcc77eadc3f4572a91f1bd30e2453ed69dd9011ddabccfca`。这些哈希是现场观测值，不是独立预期摘要；这项检查不能证明二进制由该 checkout 构建，也不能证明规划效果。

针对身份漂移、重复/改写远端、镜像/进程错误、超时、超大输出、无法确认的容器清理及无效摘要进行了拒绝测试。清理失败时，原命令的有限输出与清理命令、返回码会一同留在 `inspection.json`，并拒绝通过。相邻测试 **49 passed**；改动文件 Ruff 与 `git diff --check` 通过。最终真实 Docker 检查记录为 `results/ego-image-inspection-dev-1701-v3/inspection.json`。先前 v1/v2 结果保留；v3 是故障证据加固后新执行，不回填旧检查。

**仍关闭的门槛：** `validate_capture_input()` 的 `teacher_image_inspected` 目前仍是调用者提供的布尔值，尚未绑定本次证据；没有真实教师 `position_ref` 或可用于学生的部署可见 PX4 EKF2/标定相机位姿采集器。因此 `student_capture_authorized=false`，不启动 54 条正式语料或完整 MaleCNS 训练。当前宿主可用物理内存检查约 0.5–0.8 GiB，低于全连接组训练的 4 GiB 前置要求；本阶段未与正在进行的测试或仿真竞争资源。下一项依赖是让实际采集器产生可验证的非真值状态、相机位姿与教师轨迹，再把本检查身份绑定到采集前门；先做单个开发回合并保留失败。
