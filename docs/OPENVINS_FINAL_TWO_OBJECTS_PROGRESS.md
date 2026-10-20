# UpdaterSLAM 与 UpdaterZeroVelocity：两份内容已取得

本次仅按用户授权读取这两个精确对象路径，前4轮986份已取得文件及所有已确认超限路径排除；两个排除表与本次访问路径交集均0。`DynamicInitializer.cpp.o`、`Propagator.cpp.o`和旧库没有再次stat/open/read。无目录枚举、日志搜索、源码/头/工具/依赖文件/旧payload重采，无Linux/WSL命令、compiler/configure、原生/SDK执行、资源查询、安装、测试、Linux写入或生产修改。

一次Windows标准文件I/O子进程0.921s，两份均取得完整内容并通过本次共享视图读取前后元数据一致性检查：

| 对象 | 字节数 |
| --- | ---: |
| UpdaterSLAM.cpp.o | 45841632 |
| UpdaterZeroVelocity.cpp.o | 30651792 |

实际合计76493424B，保存2个SHA256 blob。单文件67108864B、累计201326592B、27s读取窗口、30s父等待+5s terminate/5s kill、45s outer等原上限均保持，未触及。本次exact2选择complete=true，仅指两份授权内容取得完整，不表示完整历史构建、全部34对象、库来源或原生准入完整。两份均纯字节解析为ELF64、小端、x86-64可重定位对象，未加载或执行。

累计34份配方对象中，**32份已有实际保存内容，剩2份均为此前已确认超限**：DynamicInitializer81028080B、Propagator81915872B。本轮完全跳过它们，不strip、分块拼回、替换、重编、扩cap或另开批次。合并表逐个引用phase/SHA/blob及此前保存的34份实际`.o.d`；这是不同时间的内容观察，不是原子或历史构建时快照。

规范派生回执使用本目录 **`*-v2.json`**。初版分析helper生成时，先替换schema名称导致两份新对象的phase标签成为不存在的 `results/openvins-two-objects-20261018`。保存字节引用核对时发现后，原v1/helper/JSON保持不变，新增v2仅纠正新对象phase为实际目录 `results/openvins-final-two-objects-20261018`，另存 `analysis-reference-erratum.json`。payload、实际访问路径、SHA、计数、旧引用及未知/资格不变；这属于Windows保存字节分析标签错误，非Linux/native失败，没有再次访问Linux。新核验逐项检查v2实际引用存在及v1→v2仅该标签差异。

**source→object→旧库仍未证明。** 名称、`.o.d`、链接配方、ELF/comment/debug字段不替代可信构建时源码/头/工具输入内容、编译器身份及主编译/最终链接同会话回执。32份跨时点对象也不能自行证明它们被旧库链接。旧291717384B库仍缺完整当前SHA/ELF/ABI，继续null/unknown，不用历史ef649cc代填；production64MiB file_pin不改。此前日志搜索不是全局日志不存在证明，本轮未重新搜索或执行任何日志命令。

Winshare元数据/链接/非原子限制与完整tool/header/library/package/loader/ABI/sourcebuildproof、实测标定/noise/输入、futurefresh原资源/cgroup/pidfd/适用唯一准入缺口保持。所有qualification/runtime_graph_frozen/physical_dispatch_ready/dispatchfalse；goalblocked只读、automationACTIVE、同chatbranch仅personal/draftPR65。旧封存raw/report/ZIP/map/review和生产/binding/admission模板不改。

后续仅Windows保存字节派生及新payload/JSON/helperAST/新ZIP CRC/member/hash核验；无旧tests/archive/private475/history扫描或第二source/native/delivery审查。全部原UNKNOWN/CONSUMED/预算stopsoncecleanup/precision/sensors速度RTF/truth仅scoreabort/pidfd failclosed及完整单机mission/常规planner/heldout/MaleCNS/公平upstream/HITL实飞目标保持。
