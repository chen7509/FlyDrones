# Agent-inclusive v12 单机试验离线准备（2026-10-12）

**新声明可供以后核验，但没有执行 PX4/Gazebo 物理回合。** `live-wire-agent-dev-1701-v12-retry2` 为新开发试验，seed 27602，使用 `live-wire-study-v2`、固定 Agent v2.4.3、原 PX4/OpenVINS 配置与 60 秒独立 PX4 启动阶段上限。25 秒仿真、1 ms 物理、250 Hz 原始 IMU、10 Hz 160×120 RGB-D、8 秒初始就绪和原有 2 秒运行失联门槛不变。旧 v11 清单、v10 TIMESYNC 失败及全部历史结果未改写。新清单 `live_activation_authorized=false`，未产生 capture、dispatch、completion 或物理 audit。

v2 纯校验要求 Agent 配置文件、bundle、固定二进制和 13 个库路径同时出现在事前快照中，受管进程角色 `agent` 含 `ready/prestop` 两阶段；执行声明和命令必须携带同一个 Agent 配置。配置选定 UDP 18888，固定文件 SHA-256 来自前阶段独立构建。校验继续拒绝 v1 偷加 Agent、新声明缺 Agent、错误种子、错库哈希、缺受管角色、额外启动选项和既有输出覆盖。接入 Agent 不代表 PX4 XRCE 会话、DDS/CDR 解析、真实 PX4 发布身份或 EKF2 融合成功。

准备输入以已封存的 v11 ZIP（SHA-256 `ea31808ff8b835a851a84c12f6fd65329fac05170fe8ceef411a8167565e9b26`）逐字节核对；当时已选的 619 个路径只有 5 个仓库 Python 文件内容变化，均对应提交 `75ba637` 的冻结源码哈希，外部安装文件未被静默重基线。新快照有 640 条路径、87 项静态审计源码和 16 个 Agent 选定路径，原生只读 SDK 查询 40 次，资源图为 8 文档/46 边。`validate_live_wire_study_files` 与执行器的准备接口通过；7 类负例均拒绝。独立脚本再次逐项核对旧 ZIP、种子/负载、Agent 路径与哈希、失败保留、无输出及准备接口，结果为 `offline_agent_study_verified`。这些快照证明声明文件在检查时稳定，不证明完整动态加载闭包或未来运行时内存/调度。

两次离线准备错误被原样保留：`study-v12` 因旧扩展函数按真实目标去重，漏掉 8 个必须分别声明的 SONAME 链接，正确被 v2 校验拒绝；加入先失败后修复用例后，`study-v12-retry` 走到负例封存阶段，却因两个负例写同一文件名而拒绝。另一次先失败后修复用例固定了唯一文件名，最终在新 `study-v12-retry2` 成功。两者均 `physical_run=false`，不能抹掉或计为物理试验次数。

相邻试验声明/执行器/Agent 运行器回归 70 通过、1 跳过；审计与完整夹具 19 通过、5 跳过；两个准备器故障用例通过。跳过项目未算通过。改动文件 Ruff 和 `git diff --check` 通过。封存 ZIP 的成员哈希与 CRC 须另附复核记录。

| 范围 | 当前结论 |
| --- | --- |
| 已验证 | v2 离线文件与命令绑定、固定 Agent 路径/哈希、负例拒绝、失败保留和 v1 回归。 |
| 仅实现 | 将受管 Agent 纳入新单机物理试验的事前声明；代码 opt-in 路径尚无同回合 PX4↔Agent 证据。 |
| 未测试 | 同回合首次 TIMESYNC、XRCE 会话/实际 DDS、已标定非真值传感器到 EKF2、VIO 融合和无人机飞行。 |
| 仍失败 | v10 首次 TIMESYNC 超原 2 秒门槛；五机相机 0.873 RTF 低于 0.95；两次离线准备错误已保留。 |

最后一次资源检查：宿主空闲物理内存约 2.37 GiB，低于既有 4 GiB 启动门槛；无运行 Docker 容器、PX4/Gazebo/OpenVINS/Agent 及 UDP 18888 占用。因此本阶段不启动物理仿真。资源允许时仍需重新核对进程、内存、端口、全部绑定文件与一次性输出路径，再单次执行未解锁试验，保留 ULog、Agent/PX4/DDS 日志和所有失败。真值只作离线评分；不发布 ODOMETRY、不注入 EKF2、不解锁。
