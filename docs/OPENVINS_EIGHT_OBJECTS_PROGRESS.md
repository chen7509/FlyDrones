# 8份未确认超限对象：本次只读补采结果

按用户新授权，仅选择上一轮尚未读取且未确认超限的8个对象路径。前3轮981份已取得文件及已确认超限路径均排除；新采路径与两类排除表的交集都是0。`DynamicInitializer.cpp.o`和旧库未再次stat/open/read。没有目录枚举、日志搜索或其他payload扩展，没有Linux/WSL命令、compiler/configure、原生/SDK执行、资源查询、安装、测试、Linux写入或生产改动。

## 取得5份，随后按原界停止

一次Windows标准文件I/O子进程用时1.812s，在8条授权路径中尝试7条，5份取得完整内容并通过本次共享视图读取前后元数据一致性检查，保存5个SHA256 blob，实际累计读取160403224B：

| 新取得对象 | 字节数 |
| --- | ---: |
| Simulator.cpp.o | 45073752 |
| State.cpp.o | 17344392 |
| StateHelper.cpp.o | 43751096 |
| UpdaterHelper.cpp.o | 26676344 |
| UpdaterMSCKF.cpp.o | 27557640 |

这5份纯字节解析均为ELF64、小端、x86-64可重定位对象，没有加载或执行。字段/字符串另存 `object-static-observations.json`，不推定ABI、编译器身份或源码内容来源。

`Propagator.cpp.o` 本次实际共享元数据大小 **81915872B**，超过原67108864B单文件上限，内容未读、SHA未知。随后下一份 `UpdaterSLAM.cpp.o` 实际元数据大小45841632B；若读取会令本次累计超过201326592B，因此读取前拒绝并停止。`UpdaterZeroVelocity.cpp.o` 未尝试。不挑选小文件补满、不追加批次、不扩cap、不分块拼回/strip/替换/重编。原27s读取窗口、30s父等待+5s terminate/5s kill及45s outer等界均保持；collection complete=false，父进程正常退出不等证据完整。

## 当前累计：30/34对象有内容，4份仍未知

`object-union-bindings.json`保留各对象的新旧phase/SHA/blob和此前实际34份`.o.d`引用，复用Windows已保存元数据，没有重采对应Linux文件。不同轮次的30份对象不是同一构建时快照或原子观察。剩余4份为：

- `DynamicInitializer.cpp.o`：沿用此前81028080B实物观察，已知超64MiB，本轮完全跳过。
- `Propagator.cpp.o`：本次81915872B，已知超64MiB，未读取内容。
- `UpdaterSLAM.cpp.o`：本次累计界拒读，未确认为单文件超限。
- `UpdaterZeroVelocity.cpp.o`：停止后未尝试，大小和内容未知。

**source→object→旧库仍未证明。** 对象名、`.o.d`路径、link配方、ELF/comment/debug字段不能替代可信构建时源码/头/工具内容快照、主库编译和最终链接会话。此前限定日志搜索不是全局不存在证明；本轮没有重新搜索或执行任何日志中的命令。旧291717384B库仍未取得完整当前SHA/ELF/ABI，不填历史ef649cc；生产64MiB file_pin门槛不改。

Windows共享的前后元数据稳定性不等Linux原生身份、权限或符号链接认证；完整tool/header/library/package/loader/ABI/sourcebuildproof、实测标定/noise/inputs及未来fresh原资源/cgroup/pidfd/唯一适用准入仍缺。全部qualification/runtime_graph_frozen/physical_dispatch_ready/dispatchfalse，goalblocked只读、automationACTIVE、同chatbranch仅personal/draftPR65。

采集后仅Windows保存字节派生及新payload/JSON/helperAST/新ZIP CRC/member/hash核验，无旧tests/archive/private475/history重扫或第二source/native/delivery审查。旧封存raw/report/ZIP/map/review及所有原UNKNOWN/CONSUMED/预算stopsoncecleanup/precision/sensors速度RTF/truth仅scoreabort/pidfd failclosed和完整单机任务/常规planner/heldout/MaleCNS/公平upstream/HITL实飞目标均保持。
