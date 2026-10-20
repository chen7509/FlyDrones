# 剩余 OpenVINS 对象与新日志位置：本次有界补采

本次按用户的新授权补采上一轮剩余19份对象，并在此前未搜索的位置查找原始编译、链接日志。全程仅Windows标准文件I/O；此前两轮971份已取得路径为排除表，新采文件与该表交集0。没有重新读取旧对象、依赖文件、源码、头文件、工具、旧日志或旧库；没有Linux/WSL命令、编译/configure、原生/SDK运行、资源查询、安装、测试或Linux写入。旧报告/raw/ZIP/map/审查等级和生产源码不改。

## 新取得与停止位置

一次Windows子进程2.422s，选择12份剩余对象，10份取得完整内容并通过该次共享视图读取前后元数据一致性检查，保留10个SHA256 blob，累计实际读取201271200B。10份均纯字节解析为ELF64、小端、x86-64可重定位对象，未执行或加载；具体字段和调试字符串记录在 `object-static-observations.json`。

原单文件67108864B、累计201326592B、27s读取窗口、30s父等待+5s terminate/5s kill、45s outer等上限保持：

- `ov_init/src/dynamic/DynamicInitializer.cpp.o` 本次实际元数据大小 **81028080B**，超过64MiB，未读取内容，当前SHA仍未知；没有strip、分块拼回、替换、扩cap或重编。
- 已读10份后，下一份 `src/sim/Simulator.cpp.o` 实际元数据大小45073752B，会超过累计上限，在读取前拒绝并停止。其余7份未尝试；不挑选小文件补满、不继续第二批次。
- 本次采集 `complete=false`；父进程的complete=true仅表示有界采集子进程正常退出。

与上轮保存的15份合计，34份配方对象中已有 **25份内容回执，9份仍未知**（1份单文件超限、1份累计界拒读、7份停止后未尝试）。这是不同时间采集的实物集合，不是构建时或原子快照。`object-union-bindings.json`逐项标明新旧来源、SHA、blob及此前保存的34份实际`.o.d`引用，未重新读取对应Linux文件。

## 日志搜索范围及限制

先于大对象读取，本次枚举8个目录：OpenVINS根、ov_core/ov_init/ov_msckf模块根、ov_msckf/build及CMakeFiles、flydrones-upstream顶层、`/tmp`顶层。仅递归既定build/log/logs/build_logs/build-logs/CMakeFiles目录名，深度上限4；项目内要求build/compile/link/configure/CMake/make/ninja名称及日志/文本输出后缀，外部顶层还要求名称明确标识OpenVINS/ov_msckf。没有读取shell history、.git、无关项目内容或全盘搜索。

观察到的目录名称中**没有新的匹配日志候选，未取得新主库编译/链接日志**。5条已保存的CMakeLists/Cache/ConfigureLog候选被排除，未重读。7个目录的共享前后元数据相同；`/tmp`在枚举期间元数据改变，complete=false。该搜索有名称、目录和深度限制，也不是原子观察，因此不能推为其他位置/文件名不存在原始日志，不能声称全局搜索完整。完整限定与目录观察见 `log-search-observations.json`；原始目录名和失败/停止状态另存。

## 仍未证明的来源链

实际对象内容增加了，但source→object→旧库仍未知。配方/`.o.d`/链接命令中的名称、`.comment`或调试路径不含可信构建时输入内容快照或主库编译、最终链接会话绑定；不同采集轮次的对象集合不能自行变为同一次历史构建证明。前一轮取得的配置探测日志仍只支持其保存内容，不等于主库完整构建日志。本轮没有执行其中任何命令，也没有重跑测试。

旧库291717384B及其原64MiB拒读事实沿用此前实际观察，本轮没有再次stat/open/read它；完整当前SHA/ELF/ABI仍null/unknown，不填历史ef649cc。现有production file_pin门槛不变。Winshare元数据/符号链接不等Linux原生身份；原工具/头/库/包/loader/ABI/sourcebuildproof、实测标定/noise/输入、未来fresh原资源门槛/cgroup/pidfd/适用唯一准入仍缺。所有资格、dispatchable、runtime_graph_frozen、physical_dispatch_ready仍false，goalblocked只读、automationACTIVE、同chatbranch/个人draftPR65。

采集后仅读Windows保存字节做派生与新payload/JSON/helperAST/新ZIP完整性核验；无旧tests/archives/private475/history扫描或第二source/native/delivery审查。完整原UNKNOWN/CONSUMED/预算停止cleanup/precision/sensors速度RTF/truth仅scoreabort/pidfd failclosed及单机mission/常规planner/heldout/MaleCNS/公平upstream/HITL实飞目标保持。
