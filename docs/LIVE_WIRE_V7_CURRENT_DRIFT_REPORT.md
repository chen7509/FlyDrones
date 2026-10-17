# v7 在线接线研究的当前启动前核验（2026-10-10）

**结论：已封存的 v7 声明现在不能执行；本次没有启动 PX4、Gazebo、OpenVINS、训练或网络 ODOMETRY。** 这是一项只读启动前检查，不是物理试验失败，也不能说明果蝇策略好坏。v6 首次 TIMESYNC 未在固定 2 秒门槛出现的历史失败仍独立保留。

对 `study-v7/study-manifest.json` 使用生产入口 `prepare_live_wire_execution()` 时，生产校验器立即以 `ValueError: mismatched study file capture` 拒绝。选择的研究清单 SHA-256 仍是 `1d240fb161cfff97349562fb0d55a7ca7b9c8b9174ab7e3e545ba871b5cc79e2`；选择的启动诊断声明、观察器和协调器 SHA-256 也分别与现有文件一致。因此拒绝来自清单绑定的实际输入漂移，不能更换摘要后沿用 v7。

独立逐文件只读审计检查了研究清单 7 个文件和运行绑定 610 个基线文件，发现 10 条记录不一致，涉及 9 个不同文件：

| 类别 | 当前差异 |
| --- | --- |
| 仓库 Python 文件 | `capture_disarmed_sensors.py`（在研究清单和基线中各出现一次）、`capture_contract.py`、`disarmed_sensor_provenance.py`、`ready_shadow_fanout.py` 的 SHA-256 已变化。提交 `50a8921` 修改这些文件以记录原始深度来源。 |
| WSL 已安装库 | `libpng16.so.16`、`libXpm.so.4.11.0`、`libfreetype.so.6.20.1`、`libpoppler.so.134.0.0`、`libxml2.so.2.9.14` 的 SHA-256 与封存基线不同。仅确认当前字节/文件身份变化，没有把变化原因归因于某一次系统更新。 |

`activation-request.json`、capture、dispatch、completion、audit 五个输出均不存在。Docker 无运行容器，Windows/WSL 进程检查未发现竞争中的 PX4、Gazebo、OpenVINS、测试或训练。Windows 可用物理内存检查为 849,348 KiB，低于既有 900,000 KiB 启动门槛；没有降低门槛或物理负载，也没有尝试启动。

证据为 `results/live-wire-v7-current-preflight-dev-1701/check.py`（调用生产只读校验器并保留其拒绝）、`drift_audit.py`、`drift-audit.json`，以及本报告。`drift-audit.json` 包含每条旧/新摘要、长度、变化字段和输出缺失状态；审计不重新计算历史 v7 运行结果。检查脚本是本次临时只读工具，不是新的物理采集器。封存 ZIP 的整体摘要见提交后的报告附记。

下一步应保留 v7 原声明和本次拒绝记录。在能够满足内存门槛且没有竞争运行时，以新的研究 ID 对当时实际选中的仓库代码、已安装库和执行资源重新做事前冻结、离线拒绝测试，再单次执行未解锁启动诊断。不能直接修改 v7 的 SHA 清单、复用旧选择摘要或把准备工作算作 TIMESYNC/EKF2/果蝇训练通过。当前已验证的是 fail-closed 漂移拒绝；真实接线、EKF2 融合、5/20 机和实飞仍未通过。

证据 ZIP `evidence/live-wire-v7-current-drift-dev-1701.zip` 含 5 个内容成员及 MANIFEST，逐成员 SHA-256 和 CRC 核验通过；整包 SHA-256 为 `3d28f61199699fa6058a4cb13d0f7214eaab0feb980b8129b4aba28f943fdb31`。包内报告是本摘要附记前版本。
