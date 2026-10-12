# PX4状态日志的CDR字节与字段绑定（2026-10-12）

新增 `audit_status_cdr_fields()` 离线伴随审计，将日志里的状态字段逐条与实际CDR字节独立解码结果核对。历史结构审计器和原C++采集器均未修改；旧 `completed` 仍只表示结构完整与观察到的写入进程退出0，不被重新解释为来源或健康合格。

## 实现与验证

复用固定 PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` 的 `EstimatorStatus.msg`（SHA256 `44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`）与已有可选 Rosbags 0.11.5。先调用原结构审计，再有界读取相同日志字节，要求SHA与原审计一致后才解析；文件在两次读取之间改变会拒绝。消息定义和解码器版本也不能漂移，没有可由调用者替换的解码回调。

命名profile `px4-d6f12ad-status-cdr-fields-v1` 只接受已观察的小端CDR1／零options，要求实际字节与重新序列化的规范字节完全相同。当前固定原生回调的载荷为140字节。每一条sample核对20个标量声明：两个PX4时间戳、四个位图、两个精度、七个创新比和五个reset计数；同时核对七个创新比的可用性。float32按编码比较，兼容采集器的9位有效数字表示；非有限创新比只能是null／false，不能伪装成健康零。输出保留逐条序号、raw/canonical哈希、日志／消息哈希和writer完成状态。

最初模块不存在的失败属于API bootstrap。格式解码阶段先记录1 failed／5 passed；随后真实字段不一致测试记录 **15 failed／8 passed**，包括伪造时间、fault、reset、精度和创新比，以及后续样本不一致。实现字段绑定后23项通过。独立复核发现一项Minor：`splitlines()`把合法JSON回车空白误当记录边界；保留实际RED后改为 `BytesIO` 的LF逐行读取，最终针对性 **24 passed**，复核无遗留Critical／Important／Minor。

最终受影响的状态结构／synthetic runner／封存回归为 **85 passed／1 skipped**；skip为既有Windows创建symlink权限不足。改动两文件Ruff与 `git diff --check` 通过，最终四份源／测试／消息定义运行前后SHA一致。记录确认导入本工作树及既有私有dependency目录，并逐份比较Rosbags Python源码与其已有0.11.5 wheel字节，保留wheel与模块哈希。没有安装或升级依赖。Windows和WSL的全局Python包缺失是能力检查结果，未被算作功能测试或静默跳过本阶段验证。

## 原始封存记录复核

源ZIP为 `evidence/px4-estimator-status-journal-dev-1701.zip`，固定SHA256 `6fbefedf287fb6915fd208211d2f0fbd18d825a08e0c0ff30cd6158387cc9a4d`。本阶段核对8个消费成员的原manifest哈希／长度，使用原subscriber.exit，保持原字节不变。

| 原记录 | 匹配样本 | writer_completed | 本阶段结果 |
|---|---:|---|---|
| normal | 3 | true | 字节和全部已记录字段一致 |
| fsync_eio | 3 | false | 先前样本字段一致，失败退出仍拒绝完成 |
| close_eio | 3 | false | 先前样本字段一致，失败退出仍拒绝完成 |
| partial_then_eio | 0个可资格化 | false | 原不完整JSON继续拒绝 |

这是既有3组ROS合成运行的9条记录，不是9个独立物理轨迹。格式修复前后的 `retained-v1`／`retained-v2` 分别保留；第二版只重新运行这个离线伴随审计以绑定最终源码，没有重新运行ROS采集器、Docker、PX4、Gazebo或训练。

## 资格边界与后续

**已验证：**固定消息下的独立字节／已记录字段一致性、拒绝反例、原失败保留与邻近软件回归。**仅实现：**供未来来源证据链使用的离线伴随API，尚未接入实时采集资格生产端。**未测试：**真实PX4状态发布、Agent／GID／PX4／ULog来源绑定、源生成时钟和真实到达／队列积压、VIO融合及硬件。**失败保留：**所有bootstrap／字段／格式／Ruff失败，以及历史TIMESYNC和五机容量失败。

全部 `live_source_authenticated`、`upstream_loss_qualified`、`clock_epoch_qualified`、`camera_calibration_qualified`、`fusion_qualified`、`training_eligible` 明确为false。完整消息中未记录到JSON的字段与fault事件载荷的解码不在此声明内。正确CDR与哈希无法证明消息来自真实PX4；路径检查与SHA也不是对恶意文件系统的完整保障。本阶段没有改变传感器负载、物理／RTF门槛或公开initialized门禁，没有发布ODOMETRY、解锁或训练。

下一依赖仍是固定firmware候选构建及未解锁真实状态接收，将这项字段证据与已有真实接收时间、PX4／Agent身份、重置和ULog绑定；需先通过现有资源门槛。旧MAVLink观察门禁的递增延迟积压问题、benchmark私有发布路径、相机/VIO及EGO teacher资格仍未完成，不能以本阶段替代。宿主约2.1GiB空闲内存仍低于冻结EGO构建2500MiB与物理／完整MaleCNS 4GiB门槛。

封存 `evidence/px4-status-cdr-fields-dev-1701.zip`，SHA256见同名 `.sha256` 文件。包内包含新源码、测试、规格／计划、最终验证／导入／dependency哈希、原消费日志／退出码、两次离线结果、全部已保存失败与复核；成员哈希和ZIP CRC逐项校验。

官方依据：[固定PX4状态定义](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/EstimatorStatus.msg)（BSD-3-Clause）、[Rosbags type-system API](https://ternaris.gitlab.io/rosbags/topics/typesys.html)（已用版本0.11.5，Apache-2.0）。选择现有库避免手工仿造消息布局；适配成本为有界离线解码和字段比较，不增加仿真负载。没有把协议／解析库资料或论文当作标定、源真实性或飞行证明。
