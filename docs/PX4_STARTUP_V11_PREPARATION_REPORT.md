# PX4 启动阶段 v11 离线试验准备（2026-10-10）

本阶段为启动阶段门禁计划 Task 4 建立新的开发试验声明 `live-wire-startup-dev-1701-v11`，没有启动 PX4、Gazebo、OpenVINS、训练或网络 ODOMETRY。它保持旧 v10 失败及证据原样，不把 v10 改名为成功。v11 清单的 `live_activation_authorized=false`；准备结果的 `physical_run`、`live_qualified`、`fusion_eligible` 均为 `false`。

## 输入与选择

- 生产提交：`32b2c8f6a187de96179e159c7bfe962e78d5f1ff`。以 Git `hash-object --path` 对照提交 blob 确认工作树内容，记录实际检出字节的 SHA-256；这允许 Git 声明的行尾转换，但不接受源内容漂移。新清单覆盖 614 个受提交约束的 Python 源，其中三个是 PX4 启动阶段新模块。
- 旧 v10 的 613 个已声明文件逐项比对：609 个内容不变，4 个源码内容变化均由上述提交核验；已选的安装包没有变化。原资源选择未重基线。v10 已封存的准备包 SHA-256 为 `e5000481edc794ecc705bd577981f14269cb0e69b258b4d434bcb401dbe16885`，仅作可核验输入。v11 不回填 v10 的物理结果。
- v11 独立 seed `27601`，`capture-wire-startup-v2`，从 PX4 spawn 起算的启动阶段上限 60 秒；原 25 秒仿真、1 ms 物理、250 Hz IMU、10 Hz 160×120 RGB-D、其余 8 秒/2 秒健康门槛与机体/轨迹条件均保留。60 秒是此前代码定义的启动阶段硬上限，并不延长运行期的 2 秒失联容限。
- 新清单声明 619 个文件，静态审计图含 85 个源。实际安装的只读 SDK 资源查询 40 次，资源图 8 份文档/46 条边通过；不代表已加载的全部动态库、操作系统或运行期资源闭包。

## 验证与缺口

离线 `validate_live_wire_study_files`、`prepare_live_wire_execution` 及独立审计均通过。seed、启动命令、审计器哈希、时钟范围、缺失静态源五类篡改均被拒绝；没有生成 capture、dispatch、completion 或物理 audit。审计脚本首轮错误地读取不存在的 `wire_config_sha256` 字段而报 `KeyError`；修正为执行契约实际的 `wire.sha256` 后通过，首轮错误记录保留。封存 `evidence/live-wire-v11-startup-preparation-dev-1701.zip`：74 成员，SHA-256 `ea31808ff8b835a851a84c12f6fd65329fac05170fe8ceef411a8167565e9b26`，全部成员 SHA-256 和 ZIP CRC 已复核。准备文件与审计脚本在 `results/live-wire-study-dev-1701/study-v11/` 和同级目录中，封存包含复核副本。

**已验证：** 当前提交及原有选择的离线绑定、v2 配置/负载声明、资源查询、五类拒绝和无授权状态。**仅准备：** 新试验清单及执行绑定。**未测试：** 实际 PX4 启动、首次 TIMESYNC、500 个有效样本、VIO 及 EKF2 物理闭环。**仍失败：** v10 首次 TIMESYNC 未在原 2 秒门槛出现；五机相机容量 0.873 RTF 低于 0.95 门槛。

宿主本次空闲内存约 0.95 GiB，低于现行 4 GiB 启动探测门槛，故本轮不能启用物理试验。资源允许后，需在启动前重新核对 owned PX4/Gazebo/OpenVINS 进程、固定 socket 实际占用、清单文件/进程身份、完整依赖快照及宿主内存；再将独立声明明确授权为一次未解锁开发试验，并保留全部 ULog、日志、轨迹和失败。当前离线准备不能用于宣布果蝇策略、VIO→EKF2 或安全飞行通过。
