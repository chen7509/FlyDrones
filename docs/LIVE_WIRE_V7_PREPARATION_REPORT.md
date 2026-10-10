# Live wire v7 离线准备（2026-10-09）

**v7 研究输入与启动诊断声明已独立准备并通过离线校验；尚未启动 PX4/Gazebo，也没有新的 TIMESYNC 结果。** v6 在固定 2 秒首次进度门槛前没有收到第一个 PX4 TIMESYNC，其失败和原始输出保留。v7 不修改 25 秒、1 毫秒物理、250 Hz 原始 IMU、10 Hz 160×120 RGB-D、机体、运动、未解锁监督器及 2 秒/8 秒门槛。

`prepare-v7.py` 从已封存 v6 准备器仅更换研究目录、提交源码清单和研究 ID；`committed-source-v7.json` 绑定提交 `7d4bf91a78773911d139c6a698d9b24c8a3e58e8` 的 577 个跟踪 Python 文件。准备器校验旧安装输入包 SHA-256 `b9c25ae47336904033c9d557b04e66bf9b57dae70e6eb837ce4c85af8b0092de`，保留旧输入身份，只接受三个已提交 Python 文件的差异。新清单核对 610 个声明文件、82 个静态审计源、8 个资源文档和 46 条边；40 次本地只读原生资源查询一致。种子、启动命令、审计器摘要、时钟范围和缺失安全审计源五种变异均被拒绝。准备器输出明确 `physical_run=false`、`live_qualified=false`、`fusion_eligible=false`、`runtime_closure_qualified=false`，不能称完整 OS/驱动依赖闭包。

v7 `study-manifest.json` 的 SHA-256 为 `1d240fb161cfff97349562fb0d55a7ca7b9c8b9174ab7e3e545ba871b5cc79e2`。另一个只读诊断声明将此摘要、提交后的观察器/协调器源码、60 秒观察期限、5 秒握手期限和三个准确输出路径绑定，声明 SHA-256 为 `e32c4c898971e299d59005ee3d9b12c6364c0481f047d427a73de70a697a6e9a`；WSL 解析器独立接受。执行器预期的采集、dispatch、completion、审计及物理输出均不存在；activation request 和两个诊断输出也不存在。未创建容器实例、PX4、Gazebo、估计器或训练进程。

最新资源检查显示 Docker 服务可用但无运行容器，PX4/Gazebo/OpenVINS 进程为空；Windows 可用物理内存约 0.4–1.1 GiB。此时启动完整物理场景可能与宿主内存竞争，故尚未执行 v7。下一次必须先确认资源余量及无已有仿真，再以两个选中摘要调用独立执行入口一次，保留 dispatch、completion、ULog、PX4 原始日志、启动观察、监督器及全部失败。诊断观察的宿主单调时间只表示日志首次可见，不是 PX4 内部事件时间；即便 v7 获得 TIMESYNC，也仍需后续通信、安全与融合门槛。

离线准备及声明封存包 `evidence/live-wire-v7-preparation-dev-1701.zip` 共 71 个成员，逐成员 SHA-256 和 ZIP CRC 检查通过，整包 SHA-256 `23d6887c557e1f8cad429d5da221ac0ad0ef41aeba63be61a2caec79a670f6df`。包内报告是封存前版本，整包摘要仅在此后记中记录。
