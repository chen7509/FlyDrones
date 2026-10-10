# EGO-Swarm 参考消息数值边界（2026-10-09）

**已修复一个可复现的输入校验缺口；没有运行 EGO 规划、PX4/Gazebo 或公平物理对照。** 当前 `EgoController.step()` 先解析 ROS 桥接器返回的 JSON 参考，再交给 `track_reference()` 生成速度意图。之前 `validate_reference()` 将布尔值和数字字符串交给 NumPy 转成浮点数，并接受负的采样时间和上游时间。异常消息因此可能被当作合法参考进入后续速度整形。既有 ROS `PositionCommand` 的正常有限浮点输出保持接受，跟踪增益、动力学和安全层均未改变。

修改仅限 `src/flydrones/benchmark/ego.py` 的参考消息边界：两个时间字段须为非负整数；位置、速度和航向率须为 JSON 数字（不接受布尔值或字符串）且有限。未触动上游固定镜像或将其重实现；上游身份和局限见 `docs/EGO_TEACHER_IMAGE_INSPECTION_REPORT.md`。这种校验仅说明收到的参考格式有效，不能证明它来自真实上游规划器，也不能证明使用了部署可见的定位和相机数据。

五个针对性反例先全部失败：负 `sim_ns`、负 `upstream_stamp_ns`、布尔位置、字符串速度和布尔航向率；修复后既有与新增 EGO 适配器测试 9 项通过。相邻 runner、传感器、评分和来源测试合计 38 项通过，改动文件 Ruff 和 `git diff --check` 通过。本阶段未作完整仓库回归或物理试验，未改变历史正式结果。

当前 Docker 镜像身份仍为 `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`，但没有运行中的容器；宿主可用物理内存约 700 MiB。v7 PX4 启动诊断仍未运行，已有首次 TIMESYNC 失败没有被此格式修复重分类。教师轨迹、完整连接组训练、陌生场景公平对照及五机门槛仍待独立证据。

本阶段封存包 `evidence/ego-reference-validation-dev-1701.zip` 含 8 个成员，逐成员 SHA-256 与 ZIP CRC 通过，整包 SHA-256 `fe4af260950c0843bda805bc3af842453fc3c96d7f7a9a020bb84e7c836bc529`；包内报告是封存前版本。
