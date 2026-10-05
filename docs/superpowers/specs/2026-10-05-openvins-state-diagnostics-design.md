# 固定回放的起飞前 VIO 状态诊断

目标：明确内部初始化、公共 initialized()、状态参考时间与零速更新的区别，导出原来被公共标志遮住的姿态、位置、速度及 IMU 状态协方差。只验证离线输出连续性和拒绝无效输入，不发布 MAVLink，不改变 PX4/果蝇策略/估计器。

上游调研（2026-10-05）：rpng/open_vins API 显示 GPL-3.0、未归档，最近推送2025-11-30，不能据此称目前持续活跃开发。采用已固定 `69488123ed9362dd44b6f28e7f4680abbff1442b`、库SHA `532ae57a6a952a0137cc1de291bc47ad556d419c7524fbb23b7a90c00addab5b`，理由是保留可比性。官方 [VioManager API](https://docs.openvins.com/classov__msckf_1_1VioManager.html) 和固定头文件允许诊断子类只读 protected 标志；StateHelper 提供 IMU 15×15 边缘协方差。算法依据仍为 [ICRA2020 OpenVINS](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf)。[PX4外部定位文档](https://docs.px4.io/main/en/ros/external_position_estimation.html)要求处理消息、坐标系、时延与估计器配置；本阶段不满足这些完整集成条件。

考虑：①只在离线runner派生只读诊断子类；②给上游加新插桩补丁并重编库；③引入ROS包装。选①，不新增软件依赖，不改上游库；②重编约293MB库成本高且增加变量，③ROS接入扩大范围且不能直接解决状态含义。接口为追加的JSONL侧文件；只读状态/协方差有额外复制与序列化成本，记录真实墙钟耗时，不能将其当实时机载性能。

固定使用 PR30 的428图像/10711IMU和完全相同配置、库、输入顺序。旧CSV同步写出并与SHA `2b5ce9c343e63f3178a74e8a02c889beba3bfbc02ddf9eaf4e1c526f94a6f550` 比较，差异则保留失败并调查。每帧诊断含 image_ns、internal_initialized、public_initialized、initializer_time_s、state_time_s、last_regular_update_s、zupt_flag_latched、has_moved_since_zupt、姿态/位置/速度、15×15 IMU covariance、feed_camera_wall_s。未初始化不伪造向量/协方差，写null。zupt标志是上游保留值，不自称本帧更新事件。坐标和状态顺序明确为OpenVINS原生，不伪装PX4 NED/FRD消息；不伪造quality/reset_counter/arrival_timestamp。

审计器要求与预定图像列表一一对应、整数纳秒严格递增、精确字段、布尔字段有效、有限数字、四元数范数误差≤0.01、15×15协方差对称/半正定（1e-8数值容差）、公共标志与内部标志和last_regular_update一致。已初始化后丢失内部状态或initializer时间变化因无reset元数据而拒绝。每帧内部未初始化、状态超前/滞后大于冻结50ms窗口、相邻图像间隔超过150ms不通过诊断筛选；边界1ns容差。50ms/150ms只是本10Hz回放的结构性筛选条件，不是飞行安全门槛。所有输出恒标 `eligible_for_px4_fusion=false`；数值筛选通过不表示精度、可观性或协方差校准已合格。精确检查预解锁15.68–19.70s的41帧是否全部连续/数值有效；缺帧、乱序、NaN、负/非对称协方差、坏姿态、陈旧/未来状态、初始化丢失均要故障测试。

附带修复前阶段明确遗留的悬空INCOMPLETE.json符号链接拒绝（不改任何有效输入）；使用定向回归测试。不再运行PX4/Gazebo，不生成新场景，不重调图案。独立复核、封存、草稿PR后下一步由诊断结果决定。用户持续授权覆盖设计与实现，无需再次逐项批准。

固定回放后的语义补充（不改变任何健康门槛）：上游同步初始化工作线程完成并被 join 后，`try_to_initialize` 本次仍返回 false，下一帧才消费成功锁存。因此允许一次明确的交接记录：内部标志 false、initializer/state 时间相等且不超前于图像、常规更新时间 -1、向量和协方差 null、其余标志 false；此记录仍不通过筛选。下一条若仍未初始化或 initializer 改变则拒绝。分别报告成功交接图像、内部标志首次切换图像、初始化参考时间和公共可用图像。该修正有先失败后通过测试，原始回放和旧 CSV 不改、不重跑。

独立复核后的收紧：窗口首尾距各自边界必须严格小于100ms，防止同时从输入清单/诊断删除末帧仍通过；常规更新时间不回退、负值只能为-1，移动锁存不得在无reset时回退。输出两路径先检查已有对象/符号链接/别名，再Linux O_EXCL|O_NOFOLLOW创建，并检测写出失败。原生产者源码封存，修订版重新编译但不重复本次估计器回放；I/O保护单独用不链接估计器的C++可执行程序验证。
