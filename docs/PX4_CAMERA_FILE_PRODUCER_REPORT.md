# PX4 日志与相机文件生产接口（2026-10-14）

已实现并实际运行一个新的文件生产接口：从 SHA 绑定的 PX4 ULog、相机
内参/安装外参和帧时间表读取数据，输出逐帧来源与拒绝原因，条件满足时
计算 ENU 光学相机位姿。这不是新的仿真探针，也没有启动 PX4、Gazebo、
OpenVINS、DDS 发布器、完整 MaleCNS 或优化器。它补齐的是**已记录数据的
生产入口**；实时来源、实测标定及训练/飞行资格仍未完成。

## 接口和来源研究

- `src/flydrones/benchmark/px4_camera_source.py` 提供 `CameraRigBinding.load`、
  `Px4UlogCameraSource.from_ulog` 和 `produce`；
  `tools/benchmark/produce_px4_camera_file.py` 是实际文件消费者。
- rig 绑定 body/camera ID、CameraInfo 尺寸/frame/K、明确方向的
  body-FRD-from-camera-optical 旋转和平移以及实际证据文件字节。域只允许
  simulation-candidate/hardware-candidate，二者都不授予校准资格。
- pyulog 解析所选 topic 后，生产接口只选用唯一 instance 0 的 vehicle_local_position、vehicle_attitude、
  estimator_status 和 estimator_status_flags；其他实例不误当 instance 0。
  没有把不存在的 VehicleOdometry、host receipt、quality 或 covariance 补出来。
- 已读取固定 PX4 提交 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` 的四个
  message 定义和 BSD-3-Clause LICENSE，原字节/哈希/命令在 research。
  [VehicleLocalPosition](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleLocalPosition.msg)
  和 [VehicleAttitude](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleAttitude.msg)
  的 NED/FRD、wxyz、sample/publication 和 reset 字段用于明确接口方向。
  日志自报 ver_sw 同为该提交、ver_hw=PX4_SITL；自报值不证明固件二进制
  或当前运行源已认证。没有重建固件或审计本次 live source。
- 实际解析使用既有 WSL Python 3.12.3、pyulog 1.2.4、NumPy 2.5.3、
  SciPy 1.16.3；记录了已安装 pyulog 的 BSD 许可文本。没有全局安装依赖。
  采用已有文件解析/数学库可避免 ROS/PX4 编译和模型内存；没有对上游近期
  维护状态作新结论。
- [OpenVINS 标定说明](https://docs.openvins.com/gs-calibration.html)用于区分
  空间安装候选、图像/IMU 时间关系与实测标定。静态仿真候选不替代动态或
  硬件标定。拒绝 Gazebo 真值替代估计器、SHA 标签替代校准和 publication
  替代网络 receipt 的方案。

## 生产行为和安全边界

文件读取前验证预先存在的链接/越界路径和 SHA，读取后验证普通文件变化。
输入及输出目录须由调用者控制并保持静态；portable check/stat/open **不防御
敌对并发路径/祖先 symlink 或 junction 替换**，不宣称路径来源认证。
独立复核发现这个保证边界后，修订了原过强规格，未用事后检查冒称消除竞态。

每个 JSON 文档最多 64KiB、ULog 最多 16MiB、每选定 topic 最多 100000 行/
256 个数值标量列，选定列累计复制最多 64MiB，帧表最多 4096 个严格递增
int64 范围时间戳。列复制门槛不等于 pyulog 内部峰值内存证明。
实际输入 ULog 7553120 bytes，四 topic 列合计 1170361 bytes。

沿用状态/status publication 100ms、状态 sample 100ms、state skew 50ms 和
source-flags publication 2s 门槛。六个 reset counter 任一已观察变化（含回绕）
会拒绝该帧及后续帧，不隐式恢复。仅选择已发布的数据，不插值/外推。
必须额外提供绑定 rig、ULog 和 canonical frame-sequence SHA 的显式共同
PX4 boot epoch 声明，才允许条件几何计算；这个声明仍只是 caller assertion。
缺声明则每帧 `camera_px4_epoch_unbound` 且 geometry=null。

数值合格时以 NED→ENU、body-FRD-from-optical 和安装平移组合相机位姿，
源 quaternion 与用于计算的旋转副本分开。每行记录四 topic index、原 publication/
可用 sample 时间、ULog/rig/两角色证据 hash、原健康/时间/reset 原因；receipt
始终 null。结果不属于 Observation/CaptureInputEvidence，不接入原 recorder 或
live bridge。所有行和完成摘要的 live-source、clock、calibration、training、flight
资格始终 false。

CLI 只写新目录：保存准确 argv、输入快照、rows.jsonl 和 completion；失败也
保留部分输入和 error，已有目录拒绝覆盖。文件 flush/fsync 不声称目录或断电
持久化。旧 adapter、bridge、构建 profile 和所有历史失败未改。

## 真实开发日志集成

`results/px4-camera-file-producer-dev-1701/real-file-attempt-v1` 是新接口的一次
实际 WSL 文件运行，parent PID 48268、exit 0；UTC 完成 09:58:27。
没有重复历史场景/低层探针或调封存测试。准确 argv、输入 SHA、父进程开始/
结束、原文件前后 SHA、原始控制台 bytes 均保留。

使用原 development seed 27201 的 ULog：
`55428c6d37e75d7fa2d53ab67a6527b4350fa020dca4a761a44fa7aec68d1028`，
原 RGB manifest SHA `6d71edb71136d4c0b696f900c46b5913dad586bb71b2b0f8e340a649fb631bdf`。
帧时间来自该 manifest，但本接口不消费像素，也不认证相机设备或源生成时间。
解析观察：VLP 3038、attitude 5511、status 2432、flags 34 行，均 instance 0。

实际输出 **251 行，0 行几何**。heading_invalid 243 帧，reset_epoch_unresolved
239 帧；还有启动缺样、dead_reckoning、位置/速度无效。多原因可同时存在，
不能相加当成失败帧数。所有拒绝行均保留，不放宽门槛寻求可用姿态。
`file-production-complete` 只表示文件处理完成，不表示源、相机或任务合格。

本次命令实际选用了另一历史仿真目录的 CameraInfo 副本 SHA
`7887f77ebc2ac020bc603fd27ca2c3cf73b584414e33458d572859acaa5d658e`。
独立复核证明**同 capture 的 CameraInfo 实际存在且字节相同**；先前口头/计划
假设“同批文件缺失”错误。原 association-gaps.json 已记录 present=true。
新增 camera-association-correction.json 和 same-capture 原字节保存这次后观察
勘误；准确命令/输入不回填、不重跑。字节相同仍未证明动态时空/设备关联。
安装矩阵/平移来自旧静态仿真候选，不是本次实测标定。epoch 声明也未测量。

子进程完成 exit 0 及完成记录写入后，父脚本打印 WSL UTF16 warning 时发生
cp1252 UnicodeEncodeError，当时外层工具返回 exit 1。此退出码/traceback 只在
当时工具响应中观察，未持久化独立原始工具记录；real-file-summary.json 是
事后叙述，不能代替该原始记录。保存的 raw console 只有子进程的 UTF16 warning，
与外层 traceback 不混称。child exit 0 有直接完成记录支持；不冒称外层全通过，
不为补证据重跑。

## RED/GREEN、复核和封存

- 首次 11 RED 为缺模块接口失败；不称旧实现行为回归。
- 独立复核三项 Important（未显式 epoch 声明、逐行来源缺字段、未正确选
  instance 0）各以真实 3 RED 复现后修复，原失败保留。
- CLI 的 2 RED 是缺 CLI 生命周期接口；新增数值列复制边界 1 RED 是实际
  string 列被接受后修复。构造 parser 替身的单测不冒充真实 pyulog；真实解析
  由上述 WSL CLI 单独证明。
- 23/26/28 GREEN 与第三次 Ruff import 排序失败均保留。排序修复后及列边界
  修改后的最终必要测试 **29 passed in 4.13s**，Ruff 0。包含生产接口、CLI
  和原 EKF2 shadow 12 个相邻测试，不称全库/全模型测试。
- 正向构造输入验证非交换旋转、安装 lever arm 和实际数值输出；失败覆盖
  错误字节/ID/反射/越界、future/stale/reset、无声明与 CLI 失败保留。
- 独立代码复核关闭前三项 Important；路径威胁边界显式限定，同 capture
  存在事实勘误已处理。报告和 archive 的最终独立结论另见封存/出版记录。第一版 182-member ZIP
  保留为 pre-correction；其“只解析”及外层原始证据描述由后续 canonical
  report 和独立 correction sidecar 修正。第二版 ZIP 封存 canonical report，
  原实验/输入不重跑或覆盖。

## 未完成及下一依赖

已验证：实际文件读取/字节绑定、相机安装组合的软件数值路径、251 条真实
日志来源行生产及逐帧拒绝、独占结果/失败保留。仅实现：可供进一步受控消费
的文件接口。未验证：owned runtime PX4 来源、网络到达/源生成关系、连续
camera/IMU/PX4 时钟、动态空间/时间标定、真 reset 恢复、live 相机接入。

原目标的 EGO teacher/full MaleCNS 训练、物理安全闭环、公平原版/补丁对照、
LAND ACK/落地、5/20/100 机门槛、HITL/实飞均未因本阶段获得资格。重任务
原内存门槛不变，已消耗 EGO v3 OOM attempt 不重跑。下一项低内存工作应
推进相机/IMU 与 owned PX4 runtime 的生产来源关联；新的动态标定数据需
遵循独立开发输入与真实资源门槛，不能用本阶段的候选矩阵冒充已完成。
