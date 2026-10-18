# openvins_offset_reset_v2 当前输入与一次运行方案

已形成可逐项审查的方案：[计划](superpowers/plans/2026-10-18-native-offset-once-plan.md)及`results/native-offset-run-plan-20261018/run-plan.json`。这是PLAN_ONLY/未申请/未消费，不是运行准入。本轮未 configure、编译、运行原生/SDK/WSL、刷新资源或重跑旧测试；全部资格/readiness仍false。

当前Windows集成输入已按18个显式入口保存修改前/Git bytes，并静态记录121个本地文件、381条import边和2处动态导入。该图是可见本地闭包，不冒完整Python/动态模块/FFI环境。独立目标唯一生产改动为CMake C++14→17，修正实际包含`exclusive_probe_output.h`的`std::filesystem`标准冲突；未改旧native/client/header，也未编译验证此修复。

固定上游OpenVINS69488123ed9362dd44b6f28e7f4680abbff1442b的三个构建子树与license/readme共143文件1434868B，逐项Git blob及SHA256核验，静态展开NO_ROS库34个编译单元。没有改上游算法或重建库，下载源树不等于当前Linux部署、当前库或ABI证明。整仓归档包含约394MB `ov_data`，下载触及原设32MiB上限后停止，没有提高上限重试；第一次超限响应体未保留，此限制和原start/failure记录保留。随后依据Git tree只读取目标构建源，不含dataset/runtime配置，不冒完整整仓保存。

方案给出：只构建新adapter的精确CMake argv模板；现有capture/sole owner/owned ULog完整flag模板；工具/系统头/CMake config/编译depfile/ELF递归依赖/懒加载maps回执；单offset单child/no-restart/no-fallback状态机；原compile1GiB/300inner330outer及physical4GiB/worker300/inner315/scopewait330/outer360等预算和停止条件。本方案对未来build/run均选择更保守双4GiB reserve，不改变原PNG双2GiB门槛或其它预算；本轮没有读取当前资源。

**软件可继续补齐的具体项：**v2构造后prefeed身份/maps barrier、绑定的once coordinator/build-receipt producer、另一符号与可达reset的独立实验设计。本轮交付明确合同，没有把这些入口称为已实现，不能把旧PNG的barrier/argc协议或旧consumed executor拿来使用。

**需要外部实物/时点/测量的项：**当前Linux工具/头/库/包/构建回执；原fresh资源/无竞争/cgroup/pidfd条件；真实signed calibration/noise和新输入；今后才可能取得的编译/ABI/加载/传播/receipt/RTF/cleanup证据。run-plan所有实物绑定均显式null、dispatchable=false，没有缺项默认通过。

一个native进程只能绑定一个固定offset，首次运行只能回答该符号；现有manager没有reset API，legacy restart/fault flags在v2被拒。没有可达reset事件就必须报分支未覆盖，kill/新nonce/调用者reset0不是真实reset。当前运行方案仍只允许未解锁、EV0的接收观察，不启用EV、不PARAM_SET/ARM/offboard/control，不证明positivefusion或单机飞行。

旧source reviews/封存报告/raw/ZIP/map/UNKNOWN/CONSUMED/缺payload/DL-M1/AV/120srecordergap保持原样。当前新配方和一次方案需未来完整current receipts及ONE适用准入审查；本轮不复用旧审查授予native权。仅personal/draftPR65，同chat/branch；goalblocked只读/automationACTIVE，完整后续单机/常规builtplanner/MaleCNS/公平upstream/HITL实飞目标保留。
