# 相机 / PX4 IMU 数据集生产入口（2026-10-14）

新增真实文件消费者 `export_camera_px4_imu_dataset.py` 与
`camera_imu_dataset.py`：读取并绑定实际 PPM/RGB manifest、PX4 ULog 和 rig
候选文件，产出无损 RGB PNG、相机 CSV、完整 IMU 来源行及条件候选 IMU
CSV。这个阶段准备了可继续研究标定的输入文件，不是更多健康校验小修。
未启动 Gazebo/PX4/DDS/ROS/Kalibr/OpenVINS、神经网络或优化器，也未改原
传感器负载、物理精度、速度、安全或内存门槛。

## 研究及采用理由

固定 PX4 提交 d6f12ad1c4f70ad3230afd7d86e971421e02fef4 的
[SensorCombined.msg](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/SensorCombined.msg)
明确提供 gyro 时间、accel 相对时间、两者积分周期、clipping 和校准 counter。
该数据是 FRD 中已缩放/可用时已补偿的区间均值，不是瞬时 ADC 原值。保留
全部原字段；INT32_MAX 相对时间不能生成 accel 时间，不把不同 sensor sample
时刻合并为一条同时间记录。固定原 message/命令/哈希与 PX4 BSD-3-Clause
LICENSE 保存于本阶段 research。

参考 [OpenVINS 数据集说明](https://docs.openvins.com/gs-datasets.html)及
[Kalibr bag-format](https://github.com/ethz-asl/kalibr/wiki/bag-format)研究相机文件/
IMU 时间序列消费接口；输出采用 cam0/data/PNG、cam0/data.csv、imu0/data.csv
的候选布局。没有称它已经被某个上游程序接受，也没有生成 ROS bag、移植
上游代码或安装标定工具。RGB8/平均 IMU 的模型适配仍待消费端验证。
复用既有 WSL pyulog1.2.4、Python/NumPy 和标准库 CSV/zlib/PNG 编码，避免
新的 ROS/标定构建与模型内存。已保存既有解析器版本及已安装 pyulog BSD
许可观察；它们是环境观察，不是新构建结果或近期维护保证。

## 接口、安全和资格

ULog 最多16MiB，选定 sensor_combined instance0 最多100000行/256数值列，
选定列每组最多64MiB；manifest1MiB，最多512帧、每个P6文件64KiB。
保持原160x120 RGB，不裁剪、缩放、灰度化。逐帧读取、验证SHA、保留原PPM，
生成PNG及SHA/CRC。输入/结果目录必须受控静态；沿用 portable stat/open 检查，
不承诺敌对并发路径替换防护。解析器内部和多份列快照的总峰值未认证，
64MiB不是整个进程峰值内存声明。

每个IMU原行保留实际时间、区间、clipping/counter、source index、ULog/rig/
intrinsic/mount/manifest身份及所有拒绝原因。非有限数字用明确字符串标记，
原ULog二进制仍保留，不在JSON中写非标准NaN。sample零/溢出/不递增、无效
相对时间、非有限向量、clipping、无效积分周期拒绝候选；积分期需正整数
微秒、不超过1s且不越过boot起点。已观察时间故障或校准counter变化（含回绕）
锁存，不自行重基准。没有姿态、协方差或host receipt被补造。

候选IMU CSV只在**全部原IMU行**结构有效、无manifest drop、真实字节读取器
结果存在且epoch声明精确绑定时产生。不能跳过失败行取得“通过”。普通构造
列即使提供null epoch或SHA标签也只能用于未绑定原行组合，不能产生候选CSV。
私有loader结果禁止属性赋值且列初始只读，但其内部dict/NumPy不是对任意
进程内反射/改写的安全封印；不假称来源认证。入口一次列快照供journal/CSV
两轮使用。rig来自文件加载，epoch仍是caller声明，空间/时间标定仍未合格。

所有camera/IMU行与完成摘要的live、clock、calibration、training、flight资格
都是false，receipt=null，consumer_executed=false。目录独占，失败保留request/
部分输入/完成error；flush/fsync文件不称断电或目录持久化。原live collector、
bridge、几何producer和冻结profile未改；已有EGOv3OOM尝试不重跑。

## 实际生产与验证

使用原development27201文件：ULog SHA
55428c6d37e75d7fa2d53ab67a6527b4350fa020dca4a761a44fa7aec68d1028，
RGB manifest SHA6d71edb71136d4c0b696f900c46b5913dad586bb71b2b0f8e340a649fb631bdf。
rig/epoch复用前一阶段明确未合格的仿真候选与caller声明，未重复其位姿生产。
same-capture CameraInfo存在且与选定历史副本字节相同，仍非动态标定。

原实现v1实际parent61764 exit0；随后独立复核找到公开helper可用未绑定构造
数据产生候选CSV。原CLI自身已经实读并验证ULog，但helper门槛必须修复。
v1源代码快照、精确SHA/argv、全部原输入/输出均保留。2实际RED复现后，
新增byte-reader结果/effective digest门槛和同一入口快照，并声明新v2执行。
v2 parent7760 exit0；没有覆盖v1，没有重启任何传感器/仿真进程。

v2产出 **251张PNG、251条相机行、6123条完整IMU行、6123条候选IMU CSV**。
全部relative timestamp=0，结构拒绝0；这只证明此次记录满足CSV同时间字段
条件，不证明相机/IMU同步、设备归属、连续时钟、VIO初始化或真实标定。
完整像素核验：251张PNG的CRC/解压RGB逐字节等于原PPM，源SHA与输入副本
一致；所有CSV时间和值逐条等于IMU原行；v1/v2核验都保留。

原gyro sample范围0.5..24.988s，**6个相机帧时间在其范围外**（2ms、100、200、
300、400ms及25s）。全部保留，不丢帧/移时/插值强制覆盖。这不是已同步可用
数据集；真实动态标定/消费端需要处理此缺口，不能据6123结构合格而宣称通过。
完整ULog/manifest/CameraInfo及每个源图像的后核验哈希保留，九个旧archive未改。

## 测试、复核、封存

初始5RED是缺模块接口；首实现4failed/18passed含向量字段f-string拼写缺陷，
Ruff多余括号失败保留，修复后25passed6.25s/Ruff0。CLI缺文件baseline是
保留新CLI字节后重建的1RED，结束后byte-exact恢复，不伪装旧线上缺陷。
独立review的未绑定CSV门槛2RED后，最终 **27passed4.82s**、Ruff0；范围包括
新生产/PNG/CSV/raw行/失败保留和前一相机文件接口的必要邻近测试，不称全库。
正向byte-reader单测用了明确的parser替身fixture，不能冒充真实ULog；真实解析
由上述两次WSL文件运行证明。没有NN/optimizer/物理或上游标定工具运行。

独立复核关闭Important；“immutable”措辞按真实private dict/array边界限定。
最终报告/完整archive的独立结论和出版记录外置。封存计划是prepublication，
后ledger与其哈希区分。旧所有失败/轨迹/日志/ZIP不删除覆盖。

## 原目标的未完成项

已验证的是实际记录数据的生产、格式/原字节一致性和拒绝门槛的软件行为。
未完成：owned实时PX4/camera/IMU源认证、网络到达与生成时间关系、连续clock、
动态空间/时间标定及独立上游消费验证。候选CSV不授予capture/training/flight资格。
之前251帧位姿全部拒绝的heading/reset失败不被本阶段的原IMU结构结果消除。
全MaleCNS/teacher/物理/LAND/公平基线/5→20→100/HITL/实飞仍沿原门槛推进。
