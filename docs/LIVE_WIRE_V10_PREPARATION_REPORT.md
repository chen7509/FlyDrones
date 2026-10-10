# v10 在线接线研究离线准备（2026-10-10）

**v10 的新研究输入、已安装依赖和 PX4 启动诊断声明通过离线冻结及生产只读校验；没有启动物理仿真、PX4、OpenVINS、网络 ODOMETRY 或训练。** 这是为 v7 输入漂移建立的独立开发研究 ID，不修改 v7 清单，也不消除 v6 首个 TIMESYNC 在固定 2 秒门槛前未出现的历史失败。

v7 当前漂移审计发现 4 个仓库 Python 文件及 5 个 WSL 库文件变化。v10 仅接受前者与已提交源码哈希吻合、后者与明确选择的当前文件 SHA-256、路径/链接、包归属和版本吻合的变化。五个库分别属于 `libpng16-16t64 1.6.43-5ubuntu0.7`、`libxpm4 1:3.5.17-1ubuntu0.24.04.2`、`libfreetype6 2.13.2+dfsg-1ubuntu0.2`、`libpoppler134 24.02.0-1ubuntu9.10`、`libxml2 2.9.14+dfsg-1.3ubuntu3.10`；`dpkg -V` 无输出。此检查不能证明发行包与任何固定上游源码的构建等价，也不自动批准其他文件变化。来源是封存的 v7 准备包 SHA-256 `23d6887c557e1f8cad429d5da221ac0ad0ef41aeba63be61a2caec79a670f6df`，新源码记录绑定提交 `9d9fcab`。

两次准备失败完整保留：`study-v8` 在继承 v7 库存时因已有 `runtime:prospective-loaded-source` 角色碰撞拒绝；`study-v9` 在扩展既有角色后，旧比较器把两个新增策略/时钟文件算作原有选择，因而拒绝。固定输入复现显示原有 610 个唯一文件加上两个新路径成为 612；v10 的针对性测试先因缺失逐路径比较函数失败，再验证旧 610 项必须逐条相同、缺失/改动/重复均拒绝。没有删改 v8/v9 失败目录。

v10 准备结果：原基线 610 个文件，新基线 613 个文件；接受 4 个已提交源码变化和 5 个明确包文件变化；82 个静态审计源码、8 个资源文档、46 条资源边与 40 次本地只读原生查询通过。种子、启动命令、审计器摘要、时钟范围和缺失安全审计源码五类变异均拒绝。研究清单 SHA-256 `2fb2a200a5a70a2f4ec4874f2e0ac3cb2275fbd2332607cfcbeac1177387be01`，独立启动诊断声明 SHA-256 `c554414ac0de5925ecbec1c0daeaf11f89866d3a4b04f2fd64161c7e9ce19718`；生产 `prepare_live_wire_execution()` 和诊断校验器用这两个准确选择值再次通过。activation、capture、dispatch、completion、audit 及启动观察输出均不存在。

现有仓库 `test_live_wire_study.py` 与 `test_live_wire_startup_diagnostic.py` 定向回归为 **53 passed、1 skipped**；v9 继承角色与 v10 原有选择的临时合成测试通过。未执行全库回归；准备器本身只在此固定输入上运行，不能由这些测试声称安装环境的完整运行时闭包。`files_verified` 与局部资源图通过，`runtime_closure_qualified`、`live_qualified`、`fusion_eligible` 仍为 false，`independent_review_complete` 仍为 false。没有真实 TIMESYNC、EKF2 接收、视觉融合或飞行性能结果。

准备后的三次宿主空闲物理内存为 **743,204 / 719,536 / 737,384 KiB**，均低于原 **900,000 KiB** 物理启动门槛；Docker 没有运行容器，未发现竞争的 PX4/Gazebo/OpenVINS。保持 25 秒、1 毫秒物理、250 Hz 原始 IMU、10 Hz 160×120 RGB-D、原机体/运动/未解锁安全监督以及 2 秒/8 秒看门狗不变。内存和输入核验都满足后，才能使用新选择的两个摘要单次运行 v10 并保留所有输出与失败。准备不能替代该次物理结果，更不能用于果蝇训练、5/20 机资格或实飞结论。

完整 v8/v9 失败记录、v10 输入/拒绝案例、包归属、选择摘要及只读校验输出已封存在 `evidence/live-wire-v10-preparation-dev-1701.zip`；整包摘要见下方附记。

封存包有 107 个内容成员加 MANIFEST，逐成员 SHA-256 与 ZIP CRC 通过，整体 SHA-256 为 `e5000481edc794ecc705bd577981f14269cb0e69b258b4d434bcb401dbe16885`。包内报告是本摘要附记前版本。
