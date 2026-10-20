# 按顺序推进：构建前输入绑定

本轮完成了第一阶段的两项实际只读工作，但第一阶段仍未完整，因此没有进入编译或原生运行。生产源码、原请求/准入模板和旧证据均未修改；先前五份编译组件继续保留已取得内容的状态，没有重复采集。

## 本轮新增头文件内容

冻结选择1457条精确路径：从既存依赖索引取得1452条尚无内容的系统头路径，加上当前适配器`<filesystem>`对应的5个保存包清单路径。优先标准库/编译器内置头，再Eigen/Ceres/OpenCV、其他系统头、Boost；不采CMake模块、不枚举目录、不沿新读头文件继续扩搜。

一次父进程2.25s，Linux2.008s；1457份全部完整stable、1457个SHA blob，共18157079B，无partial/errors/触限。元数据帧正文1509074B+4373LF=JSONL1513447B；stderr132B为WSL既有localhost代理未镜像提示，无网络请求或修复重试。

| 头文件候选族 | 本次完整文件数 |
|---|---:|
| libstdc++13及平台头 | 223 |
| GCC13内置头 | 10 |
| Eigen | 255 |
| Ceres | 56 |
| OpenCV4 | 102 |
| Boost | 672 |
| 其他系统头 | 139 |

这是选定路径的当前内容观察，不是新构建实际消费证明，也不声称所有系统头已经完整。候选来源、原生身份、前后检查、path/resolved/bytes/SHA及保存blob引用均在`results/native-linux-build-headers-20261019/`。

## 经用户另行授权的当前内容复核

原“不重采已有内容”限制使旧工具/配置/源码哈希不能自动填成当前pin。先冻结169条提案并请求确认；随后收窄为166条，只去掉固定143源码清单之外的`.git/HEAD`、`.git/refs/heads/master`、`.git/packed-refs`，没有新增路径。v1和v2提案均保留。

用户明确答复“允许此清单一次只读复核”。实际仅执行166条子集：9个工具、16份依赖配置、141份固定源码。该授权不扩展为其他旧内容重采、编译、原生目标、资源刷新或Linux写入。

一次父进程0.547s，Linux0.327s；166份全部完整stable，共24310750B，无partial/errors/触限。元数据正文200315B+500LF=JSONL200815B；stderr同为132B既有提示。全部166份的当前SHA/字节数等于此前保存字段；没有重读或重hash旧保存payload来作比较。若有差异，采集器会保留真实end回执并停止，本次没有发生。

9个当前工具是cmake、x86_64-linux-gnu-g++-13、make、python3.12、env、time、timeout、systemd-run、systemctl。它们已有本次实际内容pin，不再沿用此前“当前内容SHA仍null”的状态。内容相等仍不认证包来源、历史工具调用、隐式输入或未来内容连续性。

141份当前上游源码也逐份匹配固定commit`69488123ed9362dd44b6f28e7f4680abbff1442b`的保存清单字段，零观察差异；完整要求仍为143份。`LICENSE`和`ReadMe.md`本次没有重试或访问，缺项状态保持。

复核结果、授权记录和构建候选绑定在`results/native-linux-required-input-refresh-20261019/`。input-candidates.json连接本次1457头文件、166复核输入以及此前5组件的1628个精确路径，逐项保留phase/pin。这是跨时点候选并集，不是原子快照、完整请求或已准入闭包；没有改写原生产模板。

## 第一阶段仍缺什么

| 构建前缺口 | 当前事实 |
|---|---|
| 固定143源码的完整当前内容 | 141/143已有当前回执；上述两份仍缺，不能直接删减清单要求 |
| 当前Linux生产源码/捕获入口绑定 | 软件实现已在本地分支交付，但没有据本轮输入冒充完整Linux部署源码闭包 |
| 显式toolchain_file及toolchain_receipt | 没有生成或推定为完整当前输入；工具内容齐备不自动提供该回执 |
| 完整header/package/config/implicit/link/loader输入闭包 | 1457头、16配置、9工具是真实内容，不证明所有CMake模块、递归配置/包来源或实际隐式消费已经闭合 |
| fresh一次构建准入 | 未授予；原资源/无竞争/cgroup/pidfd、预算、停止和清理要求不变，本轮没有资源查询 |

构建成功后的库/适配器身份、ABI、加载闭包及实测标定/noise和运行准入属于后续阶段；不能预填，也不能要求构建前已有新产物。本轮没有因为缺运行输出而宣称构建已失败。

## 上限和停止边界

两次选择分别对应顺序推进的新头文件范围和用户另行明确批准的166条复核范围；各自只有一次child，无追加/重排/补满/扩限。总读取42467829B，元数据帧正文合计1709389B。每次均保持67108864B/file、201326592B/total、27s读、30s父wait+5s terminate+5s kill、45s outer、metadata/stderr各2097152B和40linkhops；均未触限。

只有必要隔离Python标准库文件观察器执行；没有执行compiler、configure、link、pkg/version/shell、SDK或原生目标，没有Linux文件写入、目录搜索、资源/竞争扫描或控制。观察器自身及隐式运行依赖没有认证或完整保全证明。旧OpenVINS build/库/对象/日志完全排除，不追溯旧库来源，不重开任何UNKNOWN/CONSUMED尝试。

新头准备时一次本地诊断输出过多，被工具截断，发生于Linux访问之前；contract保留说明，不声称完整控制台原文已保全。两份新analysis-summary分别保留其生成时状态；头文件阶段的提案authorized=false是提案时状态，后来用户批准及实际166路径执行以复核阶段authorization-receipt和summary为准，不回填原提案。

后续只封存并发布本轮新结果，不自动继续Linux访问、部署写入、补模块、编译或运行。所有qualification/runtime_graph_frozen/physical_dispatch_ready/dispatch仍false，goal blocked只读、automation ACTIVE、仅personal原分支。全部原预算、安全、完整单机任务及后续目标保持。
