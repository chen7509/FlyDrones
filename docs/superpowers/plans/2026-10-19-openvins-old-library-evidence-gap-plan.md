# OpenVINS 旧库来源关键缺口与最小有界方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if a later explicit request authorizes implementation. 本文是非执行方案；不授权采集、实现采集器、编译或原生运行，不派发第二次审查。

**Goal:** 基于已保存的32/34份对象和构建元数据，明确旧库来源证明缺口，并限定下一项可能有信息增益的只读输入。

**Architecture:** 复用已有规范派生记录的结论，不重新读取、散列或解析对象、旧库、源码、依赖或归档。把历史构建来源、当前文件身份和运行准入分开；新增回执最多缩小其实际覆盖的缺口。

**Tech Stack:** 已保存的Windows侧JSON/Markdown；未来候选仅Windows标准只读文件I/O，不执行回执中的命令。

**Spec:** 2026-10-19本聊天用户请求：不重复采集或核验、不扩大上限、不编译、不运行原生程序、不刷新资源、不重跑旧测试，无法证明的关联继续未知。

## 本轮边界与结论

基线为data `18c26c264b2a49746ea2efe7949078a6dc4cb0f6`、publication `3fccec2d731f985e7638eb3b3da918a50b17cf87`。本轮仅阅读既存分析记录并编写本方案；不是新实物采集、旧证据复核、fresh pin、来源认证或准入审查。32/34是已保存对象内容覆盖数，不是来源可信度或完成百分比。

规范使用 `results/openvins-final-two-objects-20261018/*-v2.json`；v1的两份新对象phase标签错误及修正见 `analysis-reference-erratum.json`，v1/helper/原bytes保留。早期JSON中“尚无对象/depfile”“剩19/9/4”等是当时状态，当前累计数以最终v2为准，不回填早期记录。

## 已有证据能说明什么

| 已保存记录 | 已有观察的边界 |
| --- | --- |
| 32份对象的phase/SHA/blob引用；新两份静态ELF64LE/x86-64 ET_REL观察 | 保存了多次采集时的内容；没有加载、执行或验证ABI，不是构建时或原子快照 |
| 34份实际`.o.d`与DependInfo的目标/源码路径匹配 | 名称关联；1564个lexical依赖路径中此前112个有保存内容引用，不证明编译时实际读取这些内容，也不解析符号链接 |
| 已存link.txt列34个对象名，集合与DependInfo一致 | 链接配方名称关联；没有最终链接执行成功回执或输入内容绑定 |
| 当前141份源码内容与固定上游清单匹配的既存记录 | 当前采样内容关联；不能推出历史编译输入。预期LICENSE/ReadMe.md未取得，不冒完整143份当前闭包 |
| CMakeCache/flags/配置探测日志、包数据库与工具候选 | 配方及当前/历史探测观察；不是主库34TU构建执行证明。旧flags记录O3/g3等，不用独立adapter的O2配方代替 |

上述均引用已有派生结论，本轮没有重算匹配、重新散列payload或验证归档。

## 仍缺的关键证据

| 缺口 | 需要什么才能缩小缺口 | 现有资料不能替代的原因 / 当前结论 |
| --- | --- | --- |
| G1 构建时输入内容 | 主构建每个TU实际使用的源码、完整头/生成文件/配置/宏和隐含输入的内容摘要及可追溯快照，绑定到具体编译调用 | 当前源码、路径、`.o.d`、debug字符串不证明当时内容；source→object仍未知 |
| G2 实际工具身份与调用 | 当时真实解析的compiler driver、cc1plus、assembler、linker、specs/sysroot/启动文件等身份与内容，完整argv、cwd、相关环境及退出状态 | `.comment`版本字符串、包版本或configure probe不能认证主构建工具；`/usr/bin/c++`别名仍未解析 |
| G3 主编译会话与对象输出 | 覆盖34TU的可信原始执行记录，逐条连接输入摘要、工具/命令、成功状态及输出对象完整摘要，包含缓存/复用来源，保留记录来源及完整性链 | 跨时点32份对象不能证明来自同一次主构建；mtime相邻不够。compile_commands即使另有，也只是调用配方，不独自证明执行成功 |
| G4 最终链接与库输出 | 同一可信会话中实际链接输入对象及全部库/脚本/response文件的内容绑定、真实linker调用、成功退出与完整输出库摘要 | link.txt只有名字；现存对象是否被旧库使用仍未知。普通文本日志即使exit=0，若缺输入/输出内容绑定和可信来源，仍只是部分观察 |
| G5 当前旧库身份及历史输出连续性 | 完整当前库内容身份，以及与G4历史输出一致且未替换的可证明关联 | 已知旧库元数据291717384B超67108864B；当前完整SHA/ELF为null、ABI未知。历史`ef649cc`或新收到的历史摘要不得代填current SHA |
| G6 两份对象内容覆盖 | DynamicInitializer与Propagator的完整内容身份及G3/G4关联 | 此前大小分别81028080B、81915872B，均超单文件上限；保持跳过。即使以后有两份历史摘要，也不等本地保存了34/34内容 |
| G7 身份与保管链 | Linux原生文件/符号链接解析身份、记录产生者/时间/保管链及可验证完整性或签名依据 | Winshare dev0/inode/权限/链接观察不是Linux原生身份；自述、PID、路径、签名字段本身不认证来源 |

G1–G7不是“再找一个hash”即可整体消除的缺口。完整34对象、匹配版本号、相似符号或重建得到相同/不同结果，都不能单独补造历史主构建与最终链接的事实。本文不安排重建。

运行准入另有未完成的当前工具/头/库/包/loader/ABI闭包、实测标定/noise/签名输入，以及未来fresh原资源/无竞争/cgroup/pidfd和唯一适用准入。即使部分历史来源得到补充，也不授予这些运行资格。

## 为什么下一步不再补对象或扩搜日志

两份剩余对象及旧库已知超限；当前约束下不能通过重读、strip、拆块拼回、压缩包装绕过逻辑文件上限、替换、重编或扩大cap取得。旧库还同时被production 64MiB file_pin拒绝，本文不改该门槛。

既存日志观察中，CMakeConfigureLog.yaml只有configure/probe事件，不是主库34TU/final link transcript；LastTest.log只有start/end，compiler_depend.ts只是依赖时间戳说明。此前限定位置/名称/depth4搜索未取得新匹配日志，且`/tmp`观察不稳定，不表示全局日志不存在。本轮不重搜，也不从旧日志执行命令。

## 下一步：最多一份原始历史回执，条件不满足即停止

**状态：仅准备，未执行；没有冻结的候选路径，不可dispatch。** 当前资料没有提供一份可直接读取的新原始主构建回执的位置。下一项输入应来自原构建产生者或已有记录保管者，提供它已经存在的精确位置及原始来源说明；不把请求别人重新生成的声明当历史事实，也不自动联系他人。

选择优先级：能把主34TU对象输出与最终旧库输出内容摘要联系起来的原始构建/链接回执或原始provenance索引。若仅有片段日志，可以保留为片段，但不能将其写成完整来源闭环。无需为了候选强行拼装多份旧材料。

### Task 1：在任何未来读取之前冻结单一候选

**Files:** 未来仅创建 `results/openvins-old-library-provenance-candidate-20261019/selection.json`（该目录当前未创建）；不修改任何旧证据或生产模板。

**Interfaces:** 输入为一份已经存在、未采过的精确文件路径和来源说明；输出为单一候选选择或明确“不存在可执行候选”。没有通配符、目录搜索、shell history、Git历史或网络拉取回退。

- [ ] 仅在后续明确授权读取该新候选后，按既存排除记录的路径字段排除已取得文件；不重开payload或重hash旧文件。路径别名/重复内容身份不能确定时拒绝本候选，不猜测其是新证据。
- [ ] 冻结一个精确regular-file候选；排除所有旧对象、源码、头、工具、依赖文件、旧库及已搜索/已取得日志。不存在精确新位置则停止，无自动替代候选或第二批。

### Task 2：一次有界只读取得该候选（并非本轮授权）

**Files:** 未来仅该新目录下保存selection、原始候选bytes、读取结果及失败记录；旧raw/report/ZIP/map/review不变。当前不新增采集器。

**Interfaces:** 仅消费Task 1冻结的一条路径；产出完整原始记录或partial/refused/unknown，不输出admission。

- [ ] 使用Windows标准只读file I/O；不调用Linux/WSL、compiler/configure、SDK、原生程序、资源查询或测试，不执行或自动跟随文件中的任何指令/引用。
- [ ] 原上限保持：67108864B/file、201326592B累计、27s读取窗口、30s parent wait +5s terminate +5s kill、45s outer；本选择最多1文件。已知超限读取前拒绝；到达任一上限即停止，不截取冒完整、不挑其他小文件补满、不递归跟随索引或解包绕过上限。
- [ ] 保存该新候选的实际读取结果；读取前后共享视图元数据变化、reparse/不可解析身份、失败或超时均不能声称完整稳定。Windows共享一致性仍不授Linux原生身份。

### Task 3：仅对新候选给出覆盖判定后停止

**Files:** 未来仅新目录下 `candidate-assessment.json` / `NEXT_PHASE.md`，不回填当前库SHA或旧union。

**Interfaces:** 消费新候选原bytes与已有派生记录中的引用字段；逐项输出G1–G7的“该记录声称 / 可信性依据 / 能支持的关联 / 仍未知”。没有旧payload复核或新测试。

- [ ] 区分声明和证明：记录的session、完整输入/工具摘要、34TU输出、最终链接argv/exit/output摘要、来源/签名验证依据缺什么就列什么；没有认证依据不把一份自述升级成可信回执。
- [ ] 候选摘要与既存派生字段相等最多记为“字段一致”，未重新比较原bytes；历史库摘要另列，`current_library_sha256`继续null。索引指向大库、其他文件或外部签名材料时只列待办，不自动读取。
- [ ] 候选无信息增益、身份不明或缺关键绑定时终止该选择；没有第二次搜索/补批/重试。若有部分信息增益，只报告对应缺口缩小，完整来源与native admission仍不得自动转true。

## 停止条件、审阅重点与非目标

审阅本文时只需关注：是否混淆当前/历史身份；是否把名称/字符串当内容证明；是否遗漏缓存或复用对象；是否把回执自述或签名字段当认证；是否通过索引/别名/包装/第二批绕过边界。以上均在各Task中以拒绝或保留未知处理；不为本文编写validator或运行软件测试。

不存在新候选时，下一步完成条件是明确记录缺输入并停止，不制造更多核验或metadata进展。在原上限和禁令不变的情况下，本方案不能完成旧库当前身份或原生准入。

全部qualification/runtime_graph_frozen/physical_dispatch_ready/dispatch保持false；goal保持blocked只读、automation保持ACTIVE、同chatbranch仅personal。禁PARAM_SET/ARM/EVenable/control/truth注册，保留原UNKNOWN/CONSUMED/缺payload/DL-M1/AV/recordergap、预算stops/once/cleanup、precision/sensors/速度/RTF、truth仅score/abort、pidfd failclosed及单机任务/常规built planner/heldout/完整MaleCNS/公平upstream/HITL实飞目标。

## 本文引用的既存记录（未重验）

- `docs/OPENVINS_FINAL_TWO_OBJECTS_PROGRESS.md`
- `docs/superpowers/plans/2026-10-18-openvins-final-two-objects.md`
- `results/openvins-final-two-objects-20261018/analysis-summary-v2.json`
- `results/openvins-final-two-objects-20261018/object-union-bindings-v2.json`
- `results/openvins-final-two-objects-20261018/object-static-observations-v2.json`
- `results/openvins-final-two-objects-20261018/file-bindings-v2.json`
- `results/openvins-final-two-objects-20261018/missing-evidence-v2.json`
- `results/openvins-final-two-objects-20261018/analysis-reference-erratum.json`
- `results/openvins-final-two-objects-20261018/postseal/NEXT_PHASE.md`
- `results/openvins-build-provenance-20261018/analysis-summary.json`
- `results/openvins-build-provenance-20261018/log-observations.json`
- `results/openvins-build-provenance-20261018/link-name-correspondence.json`
- `results/native-linux-file-receipts-20261018/existing-build-metadata-v2.json`
- `results/openvins-remaining-objects-20261018/log-search-observations.json`
