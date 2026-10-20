# P1：本次新源码 build 请求组装

2026-10-20。用户本轮只授权“基于已封存材料组装本次stage=build请求，列出仍无法闭合的精确缺项和下一步最小范围；不填allow-once，不编译或运行，也不重复采集已有内容”。本轮已生成 `results/native-fresh-build-p1-request-20261020/request.json`，**请求已组装，但P1未完全闭合、未获准入、未执行**。

## 实际交付

请求使用现有生产协议 `native-offset-fresh-source-request-v1`，stage=`build`，profile=`fixed-source-openvins-v1`，target=`openvins_offset_reset_v2`，upstream=`69488123ed9362dd44b6f28e7f4680abbff1442b`。这是具体请求草案，不是生产准入review；没有创建review或填写allow-once。文件中的dispatchable/qualification=false只是状态声明，不能代替生产gate；本轮未调用那个gate。

从已封存final-v3 `input-pin-references.json`复制3677条path/resolved/bytes/SHA记录，并从 `final-receipt-bindings.json`加入当前source manifest、v2 toolchain receipt、v3 header/package manifest的3条实际Linux回读pin，合计**3680条输入pin路径**。这不是3680份新文件或本轮采集，亦不冒原子/futurefresh/实际消费闭包。原集合含历史命名候选的超集，不能把每个条目都称为本次真正消费输入。

`input-pin-sources.json`逐项保留原derived文件、phase及blob出处。16个BUILD_KEYS均已选择，9个文件binding有已保存pin；另7个是目录binding，不伪造regular-file pin。128本地源码逐字段与封存manifest相同，required12齐；固定143源码的保存SHA/size与原manifest字段匹配，0差异。六命名组20/1828/1205/20/105/234均无缺pin成员；没有把六组非空当成完整实际消费证明。

当前选定toolchain仍是 `toolchain-native.cmake`、v2 receipt和final-v3 header/package；不改旧草稿、模板、生产代码、源manifest、结果或归档。HOME=`/home/yuchen7509`、PATH=`/usr/bin:/bin`、LANG=`C.UTF-8`只是沿方案选入的构建环境声明，不认证host/WSL/manager的全部环境。`link_resolutions={}`保留未闭合，不能从NEEDED名称推断新driver最终链接输入。

## 精确缺项与边界

| ID | 精确位置/字段 | 未闭合的内容与理由 |
|---|---|---|
| P1-M1 | `/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility/results/native-offset-run-plan-20261018/upstream-build-source-manifest.json` | 生产 `verify_upstream()` 额外要求此文件本身在input_pins中，且SHA等于固定 `19b343211b5ae6b25d9c565095e812f32a265c32997b27100e7eb6bbd3a0ec7f`。选定3677索引与最终readback sidecar中没有该路径pin。已知SHA/可解析的保存JSON不等于实际Linux path/resolved/bytes/观察出处；本轮没有拼造pin，也不把“143源码齐”代替manifest文件pin。此结论仅限选定封存材料，非全仓/全局不存在声明。 |
| P1-R1 | `request.json:link_resolutions` | 空映射；本次新link argv尚未生成，没有可信完整的请求级 `-l...`→实际路径选择。属于后续P4，不猜填符号名、隐含脚本或driver选择。 |
| P1-E1 | `request.json:build_environment` | 三变量已选择，P2所需host/WSL Python、psutil、sys.path/site/native扩展、实际控制环境等尚无本次完整执行语境证明。 |
| P1-F1 | `request.json:input_pins` | 完全来自跨时点保存观察，本轮未对实际路径重验。不能把SHA字段相同冒成futurefresh连续性。 |
| P1-A1 | review/准入 | 未创建review，decision=null、admission_granted=false；P8及明确build-only执行授权尚无。 |

机器可读清单为 `missing-evidence.json`。P2–P8的原剩余条件保持；本轮没有补齐loader glob成员/实际选择、包来源、隐含driver/specs观察机制、资源/无竞争、cgroup/pidfd/完整后代与hardcancel、预算可行性或ONE适用审查。构建后才会产生的35TU depfiles/trace/新库与adapter/build-release receipts仍是输出，不成为当前缺少“预先新binary”的循环要求。运行的ABI/实测标定noise/ELF/PythonSDK/source-clock-wire/独立准入仍属后续。

## 下一步最小范围（只提出，未执行）

先仅针对P1-M1：如果明确指出已有该精确路径的实际Linux观察回执，复用那一条保存metadata，不扩搜payload/旧archives或全树。若没有可复用回执，最小新观察候选只有上表**1个精确manifest文件**的Linux身份/完整稳定内容上下文回读，与固定SHA核对；这将是已知内容在缺失Linux上下文中的重观察，不能称为新独立payload。

当前用户明确禁止重复采集，因此**本轮不做这个回读，也不把下一步方案当授权**。将来需要独立明确范围，保留原file67108864B、aggregate201326592B、read27s（首metadata10s包含在内）、parent30+terminate5+kill5、outer45、metadata/stderr各2097152B、40linkhops，并进一步限为1目标；不扩任何界。路径不符/缺失/差异/redirect/partial/触限/清理不明即停，无retry/补批/换folder。不能为了这一条重新采128/143源码、headers/compiler/libs或探测原onceattempt。

仅取得该pin也只补P1-M1，不会补齐P1-R1/P2–P8或授予build/run。后续最小非执行工作是明确P2所选host/WSL执行环境边界和保存metadata引用；不自动采集环境或运行导入探测。详细范围见 `next-minimum-scope.json`。

## 本轮核查与限制

只在Windows用标准库准备helper读取明确的保存派生JSON和必要生产源码文本/AST常量，没有导入生产模块、调用 `verify_request`/`file_pin`/once CLI，也没有WSL/Linux路径stat/open/resolve、资源查询、compiler/configure/link/native目标/SDK/tests、安装或取包。只hash本轮新生成文件用于交付校验，未重hash旧payload/旧manifest/ZIP。无需为一次材料组装新造生产validator、重跑旧测试或再审整个已封存软件链。

helper是本次新材料生成recipe，输出独占创建；本轮只执行一次，不应自动重跑覆盖。新JSON解析及独立静态对照记录在 `verification.json`；不是生产 `verify_request` 成功、完整源码/原生审查或准入。初合并console读输出显示截断，不冒完整原始coverage；后续聚焦字段/源码契约读取取得本轮依据。原此前完整history覆盖沿本连续会话继承，全文仍由 `evidence/flydrones-history-through-linux-production-inputs-20261020.json` 保留，不重审历史冒进展。

完整活动任务目标、原预算/安全和全部UNKNOWN/CONSUMED不变；旧库32/34与G1–G7/ABI不代填。goal blocked/read-only、automation ACTIVE、personal原分支/draftPR65、PR正文不改；full_request_complete/full_input_closure_complete及全部资格/runtime_graph_frozen/physical_dispatch_ready/dispatch=false。P1本次材料组装交付结束，未授权继续采集或执行。
