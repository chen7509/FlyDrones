# OpenVINS 初始化轨迹合格数诊断设计

## 问题与边界

已封存的单机纹理板开发回合在预解锁期每帧约有 207 个 OpenVINS 数据库特征，却在前/后半窗各最多只有 9 条可用于视差判定，低于上游硬编码的 15/15 门槛。未修改的预解锁 RGB/IMU 与 ULog 在 PR #25 的校正版证据中。仅凭这两个总数不能判断特征是被过滤、只有一帧观测、跨窗不连续还是因别的上游条件失格。本阶段只观察，绝不调整 `num_pts`、FAST 阈值、相机参数、初始化窗口、15/15 门槛、PX4 或果蝇控制器，不重启物理仿真。

## 上游依据与选择

固定 [OpenVINS 提交 `69488123`](https://github.com/rpng/open_vins/tree/69488123ed9362dd44b6f28e7f4680abbff1442b)，许可证 GPL-3.0，沿用本机既有 C++/OpenCV 构建和 ROS-free runner。其 [FeatureHelper API](https://docs.openvins.com/classov__core_1_1FeatureHelper.html)及该提交 `ov_core/src/feat/FeatureHelper.h` 的 `compute_disparity`，逐相机轨迹要求在指定半窗取得两个有序像素观测；`InertialInitializer.cpp` 对前后半窗分别调用，并各要求至少 15 条。[静止初始化器文档](https://docs.openvins.com/classov__init_1_1StaticInitializer.html)说明静止假设，不能用晚于起飞的初始化冒充预解锁成功；[ICRA 2020 OpenVINS 论文](https://yangyulin.net/papers/2020_icra_ov.pdf)给出前端稀疏特征跟踪架构。上游 GitHub 在 2026 年仍有 issue 活动，但本实验仍锁定已核验的提交，避免版本漂移。

方案是对 `InertialInitializer.cpp` 增加只读计数日志：在上游原来的 `compute_disparity` 结果旁，按严格的时间边界统计每个特征/相机轨迹在旧半窗与新半窗的 0、1、至少 2 次观测分布、两半窗均至少 2 次的数量和最长观测数。代码不写回数据库，不影响判定路径。比换 VIO、加学习型匹配器或单独实现 KLT 更小，适配成本是一次隔离 C++ 构建和一次约数秒的离线回放；293 MB 本地动态库仍不打入证据 ZIP。日志若与上游 `num_features0/1` 不一致，判定插桩解释有误，不作为归因。

## 试验与验收

在新的固定提交副本应用 PR #24 的既有逐帧日志补丁和本阶段新增日志补丁，独立构建并记录库/runner/配置/原始输入/补丁哈希。复用 PR #25 唯一采集的 15,203 IMU 和 608 图像，使用同一 runner 与估计器配置仅回放一次；不读取 Gazebo 位姿进入估计。将新 `states.csv` 与 PR #25 已封存的插桩回放 `states.csv` SHA-256 逐字节比较。如果不同，明确标注日志时序可能扰动估计，不把结果称为纯观测。解析器严格要求每次 `FD_TRACK_COUNTS` 与同时间 `FD_INIT_FRAME`/`FD_INIT_DISP` 一一对应，双半窗 `2+` 数应等于原上游合格特征数；保留 malformed/缺失日志的失败证据。

只报告半窗轨迹长度分布及直接可推断的瓶颈，不据此声称根因已经是纹理、时间同步或训练。旧实验的越界、未预解锁初始化及硬件/多机门槛不变。所有原始日志、状态、补丁、构建版本和逐帧摘要封存为新的证据与草稿 PR。
