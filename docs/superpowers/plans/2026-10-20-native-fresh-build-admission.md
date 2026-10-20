# 一次新源码构建准入方案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for any later explicitly authorized preparation. Steps use checkbox (`- [ ]`) syntax for tracking. 本文仅交付方案；下列未来步骤未执行，不授予 compile/configure/link/run 或补采权限。

**Goal:** 基于已封存的 Linux 源码与 toolchain 绑定，形成一次 `stage=build` 的可审查准入方案，明确前置条件、构建输出和独立运行门槛。

**Architecture:** 复用现有 once coordinator → owned scope → configure/library/adapter → build receipt；不新增执行器或 validator。以已保存的 final-v3/final-v2 为跨时点基线，真正 dispatch 前仍须完成本次请求、适用审查和原资源/停止/清理门槛。实际构建消费证据只能在未来获准的那一次构建中产生，不能由静态清单推定。

**Tech Stack:** 现有 Python once/scope/receipt；CMake Unix Makefiles；GCC13；OpenVINS 固定源码；C++17/O2/NO_ROS/OpenCV4。

**Spec:** `docs/NATIVE_LINUX_PRODUCTION_INPUTS_PROGRESS.md`、`docs/NATIVE_OFFSET_FRESH_SOURCE_BUILD_PROGRESS.md`、`results/native-linux-production-inputs-20261019/NEXT_PHASE.md`；具体字段和顺序以 `tools/benchmark/native_offset_once.py`、`native_offset_once_scope.py`、`native_offset_fresh_receipt.py` 当前契约为准。基线 publication `dde58388d76ceb2798d324fb07768d1e56952959`。

## Global Constraints

- 当前授权仅准备方案；不访问 Linux、重采/重hash已有 payload、资源轮询、compiler/configure/link/目标运行、SDK、安装或网络取包；不调用生产 `verify_request` 或 once CLI，后者会读当前文件/创建 attempt。
- 固定上游 `69488123ed9362dd44b6f28e7f4680abbff1442b`，原143文件 manifest SHA `19b343211b5ae6b25d9c565095e812f32a265c32997b27100e7eb6bbd3a0ec7f`；不改原 manifest、生产源码、请求/准入模板、封存结果或旧回执。
- 仅 personal 原分支/draft PR65，不 origin；goal blocked/read-only，automation ACTIVE，全部资格、dispatch、runtime_graph_frozen、physical_dispatch_ready=false。
- 原 fixed attempt `results/native-offset-once-attempt-v1/build`，产物目录 `build/artifacts`；本轮未创建或探测。任何已有占用/terminal/CONSUMED/UNKNOWN 均停止，不覆盖、删改、换目录或重开。
- 禁 PARAM_SET、ARM、EV-enable、offboard/control 和 truth 注册；完整单机任务及后续 heldout/MaleCNS/公平 upstream/HITL 实飞目标和全部历史 UNKNOWN 保持。

## Review Focus

1. 静态六组都非空只满足结构的一部分，不能视作消费完整性或准入。
2. 旧 pins 是观察时事实；futurefresh 不由 hash 字段相等、publication 或旧软件审查认证。
3. 新 depfile/trace 首次暴露未声明输入时，保留 incomplete 并终止；不能事后补采使同一次变成功。
4. scope/PID/JSON 自述、child exit0 和 cgroup 消失不足以证明全部后代、pidfd 或 hard cancellation；未知不能填 true。
5. 35TU、反复核验、两次链接、回执及清理必须在原预算内；工作量未知不能通过扩大时间/内存/文件上限解决。

这是非执行方案，以上用逐项静态契约对照核查；本轮不新增或重跑软件测试，不把本方案称为第二源码/原生准入审查。

## 文件职责与封存引用

本轮只新增本文和 `results/native-fresh-build-admission-plan-20261020/{proposal.json,NEXT_PHASE.md,verification.json}`。proposal 使用独立非执行 schema，保存准入条件分类和引用，不是生产 request/review。另行保存完整旧 automation prompt 以延续历史，不修改任何旧 mapped 文件。

| 已有材料 | 本方案复用的事实 | 不能推出的结论 |
|---|---|---|
| `current-linux-source-manifest.json` + `final-receipt-bindings.json` | 同一 `/mnt/c/.../track-eligibility` 工作树128源码，once所需12齐，411静态边/2动态点，有实际Linux回读 | 原子快照、完整Python/SDK/FFI或futurefresh |
| `toolchain-native.cmake` + `final-v2/toolchain-receipt.json` | native变体1677B/SHA `3b7f6512ffe514f021d12b78bfc749ac2d3e60b9a25aea38e34d0cd17273d9b3`，13工具引用已绑定；不选强制SYSTEM_NAME草稿 | 已经过CMake解析、真实driver/linker选择、全sysroot或ABI |
| `final-v3/{header-package-manifest,input-pin-references,binding-candidates}.json` | 3677路径refs，组20/1828/1205/20/105/234，逐项phase/pin/blob | 3677新独立文件、完整实际消费集合或可直接运行请求 |
| 固定143上游源码跨阶段回执 | 前141+授权恢复2齐；保留已有1457头/五compiler组件 | 当前重新采集、同一时点状态或旧库来源 |
| `final-v2/static-elf-closure.json` + `final-v3/linker-script-relations.json` | 129ELF/374NEEDED，每个已观察名称有候选；脚本绝对引用0缺项 | 实际loader选择/hwcaps/符号版本/lazy maps |

以上引用均相对 `results/native-linux-production-inputs-20261019/`（上游跨阶段回执除外）。有效pin/group/binding是final-v3，toolchain/ELF是final-v2；旧pending字段只属生成时历史。新proposal抄录保存的回读pin，不重新读取旧payload或ZIP验证其hash。

## 构建前必须补齐的条件

| ID | 条件与可核查完成标准 | 当前状态/下一次允许做什么 |
|---|---|---|
| P1 | 一份新的 `native-offset-fresh-source-request-v1`，`stage=build`、`build_profile=fixed-source-openvins-v1`、精确target/commit、16 BUILD_KEYS、完整 `input_pins`；本地128/source12和固定143对应。所有pins含path/resolved/bytes/SHA，保留phase出处；同一解析字节与SHA绑定。 | 有已观察候选，尚无本次完整实际请求。本轮不填旧45bindings或生成可dispatch请求。将来只能在另有明确范围时组装。 |
| P2 | 冻结构建环境：目标子命令只保留HOME、PATH=`/usr/bin:/bin`、LANG=`C.UTF-8`，HOME与所选执行账户及Linux根明确对应。分别列Windows协调器、WSL校验/scope、CMake/driver及manager控制环境；不能把目标三变量冒成全执行环境。 | HOME及host Python/WSL `/usr/bin/python3`→所选解释器连续性、sys.path/site/.pth/本机扩展、psutil等实际涉及输入仍须有边界及依据；manager环境XDG_RUNTIME_DIR不能混入目标环境。 |
| P3 | 对本次build确实会执行的工具/解释器/控制工具，绑定已存在的loader配置、ld.so.conf glob成员、cache/hwcaps搜索策略及上下文声明；明确包来源未知的处理及安全停止。这里只要求已存在的输入及观察机制，实际loader选择/maps是B5输出；已知新文件缺口只能另列精确范围，已有内容不再补采。 | 目前静态候选不能证明执行上下文。signed origin未知原样保留；审查须明确依据，不能写已认证或默许必要输入缺口。未获额外文件观察/枚举/driver probe授权。 |
| P4 | 将所有预期link输入写入pin及 `link_resolutions`：每个可能的 `-l...` 都须有明确候选路径/依据，显式script/response/sysroot/search不能任意跟随。实际argv仍由构建产生。 | `binding-candidates` 没有完整请求级link_resolutions；不从NEEDED反推driver最终选择，不猜填。未能冻结的引用是准入缺口；未来若实际不符就终止。 |
| P5 | 明确构建中允许产生哪些generated输入、如何对35TU depfiles/trace/link进行有界消费，以及driver内置specs/搜索/隐含FFI证据的实际覆盖；审查须判断本次build所需输入闭包是否有充分依据，必要机制缺失则先补具体机制，不得降低原门槛。 | 现有producer有depfile/trace/显式link检查，**没有自动完整driver内置specs、syscall读集或loader maps采集**。本轮不改代码/放宽门槛；完整消费闭包仍false。缺机制不能只挪到“构建后”就当已解决。 |
| P6 | 资源及执行安全可行性：Windows与WSL各>=4294967296B，blocked processes空、Docker查询成功且无运行容器、无MicroXRCEAgent/Kalibr竞争；两次fresh facts由原coordinator依序取得。owned cgroup、账户manager、pidfd适用性、停止与释放依据在ONE审查中有明确责任与拒绝条件。 | 尚未查询；旧资源快照不沿用。实际scope/cgroup身份和释放是未来执行过程输出，不要求预先伪造。现有cleanup以owned Popen及unit为界、后代保留unknown，不声称已实现/证明pidfd或全后代；要求未满足即不准入。 |
| P7 | 对35TU及全部核验/回执/控制/清理进行原预算可行性说明，不用未测性能保证通过；review创建时机须容纳重复输入检查与命令边界TTL。 | 1GiB/300s内完成未知；无编译估时或资源刷新。失败关闭不能替代合理预算论证，不能扩大原界、strip或拆块绕cap。 |
| P8 | 新ONE适用review：schema `native-offset-fresh-source-admission-v1`，真正审查者决定，精确request SHA、`stage=build`、covers精确为current-source/tool-library-closure/recipe/budget/stops/once-cleanup/prefeed；`created <= now < expires <= created+300`，全部条件满足后才可有allow-once。 | 旧C0/I3/M0是软件审查；本方案自查也不是新准入。`decision=null`，`admission_granted=false`。人类另有明确build-only执行授权仍必需。 |

P2/P3按实际build可达性区分输入，不因全capture静态图列有gz/numpy/SDK便一律作为编译前运行条件。两个动态点分别是 `native_reference_probe.load_module()` 的运行时native扩展、`audit_px4_logger_diagnostic.py` 的模块顶层加载；现有build-only入口未直接调用这两个点，不能由此认证整条传递import链或它们永不触发。未来审查须据实际选定build路径裁定可达性，不能导入模块作“只读”探测。只在run涉及的模块/FFI归独立run gate；实际build导入则回到P2/P3。

`verify_request()`目前核对receipt文件pin、六组结构/非空/成员pins，但不会对toolchain receipt的全部语义作真实性认证。它的成功只能作为必要结构/一致性检查，不能代替P1–P8审查。

## 构建后才能取得的证据（不是预先已有文件）

| ID | 未来取得时点与内容 | 完成标准与限制 |
|---|---|---|
| B1 | 获准后原scope实际身份/InvocationID/cgroup limits、请求再验、生成 `openvins-fixed-sources.cmake`；configure的stdout/stderr/退出、CMakeCache、compile_commands、JSON trace和try_compile记录（如实际生成） | 真实所选CMake/toolchain/配置；不预填成功，不禁用try_compile绕过ABI探测；trace并非完整syscall输入证明。 |
| B2 | 34库+1适配器的实际编译argv、新对象和含系统头的35份depfiles | exact sources/outputs、C++17/O2/ROS_AVAILABLE=0/ENABLE_ARUCO_TAGS=0、`-MD`，不以`-MMD`漏系统头。外部输入必须已声明且与pin一致，generated文件只能在原exclusive build目录。 |
| B3 | 新库link argv、对象覆盖、新 `libov_msckf_lib.so` pin/checkpoint；随后适配器link argv及其真实消费同一新库的证据 | 先库成功且<=64MiB才adapter，adapter后库pin不变；无旧库fallback。link.txt/compile_commands是配方记录，不自动证明全部driver隐含选择/库ABI。 |
| B4 | `native-offset-fresh-source-build-receipt-v1`、输入/输出前后pin、bounded inventory、inside/host完成、OOM/memory events、launcher退出和owned_group_released | 全部stage exit0、cleanup exit0、receipt.complete=true、inside/host成功且原组释放，方可说“本次构建记录完整”。escaped_closure/descendants仍未知不得升级；receipt四项native/runtime/ABI/history资格仍false。 |
| B5 | 实际driver/specs/search/加载语境的进一步消费证据 | 只能由未来已明确范围、预算和机制的观察取得；B1–B4现有producer不保证生成。若不能取得，full_input_closure_complete继续false，不能补写成已闭包或临时加probe突破一次scope。 |

完整构建后仍不能自动run。新库/适配器ABI与 `native-offset-new-library-abi-v1`、精确绑定本次library/binary/build_receipt、实际ELF递归/版本/loader/lazy maps（运行中产生的部分不能预造）、当前Python/SDK闭包、实测calibration/noise及signed offset/source-clock-wire、capture inputs和独立fresh运行准入均为后续门槛。PX4接收/融合/传播/reset/RTF/cleanup实测只能由未来获准运行回答；本次不接PX4或仿真。旧库G1–G7不由新库构建补填。

## 原一次预算、顺序与停止规则

| 项目 | 原界与解释 |
|---|---|
| scope资源 | MemoryMax=1073741824，MemorySwapMax=0，CPUQuota=100%，TasksMax=64；parallel1 |
| 目标配方 | configure → `ov_msckf_lib` → `openvins_offset_reset_v2`，Unix Makefiles、Release/-O2、C++17、NO_ROS、OpenCV4；无安装/上游ROS探测/O3g3/旧库fallback |
| 时间 | inside总300s含校验、三步骤、终端核验/receipt；timeout TERM、kill-after10s不另授工作时间；scope RuntimeMaxSec315、TimeoutStopSec10s；host launcher原工作等待至started+300，outer330总含控制/清理，末30s预留。不是三次各300s，也不能保证inside有完整300s可编译。 |
| 输入与文本 | file_pin每文件67108864B；response深度4、65536tokens；显式response/script单项1048576B/累计4194304B |
| 输出清单 | inventory最多512个遍历entry、累计regular file67108864B；单个输出还受64MiB/RLIMIT_FSIZE。日志/trace/对象/缓存等同目录文件计入，不能只算最终ELF；无strip/chunk/cap扩张。 |
| 后代/取消 | 同步file IO/解析只有前后deadline，非hard cancel；父child成功不等全后代保证。无身份不杀未知unit，无pidfd保证不冒填，通过独立审查原failclosed门槛处理。 |

未来真正获准执行的唯一顺序：原exclusive stage claim（**先于first facts**）→first gate→两次SHA绑定请求检查/相同选择→second gate→写CONSUMED_DISPATCH_BOUNDARY→原scope→核对claim/facts/selection→inside owned cgroup及请求检查→创建artifacts/生成固定sources→依次三命令（每条前重验TTL、pin及remaining budget）→终端检查/receipt→host释放证据。

任一fresh gate拒绝、pin漂移、review过期、输入缺失/未声明、未知路径flag、文件/总量超限、deadline/OOM、命令非零、清理或归属不明，停止后续阶段，保留真实primary/secondary错误和partial/incomplete。first/second gate的REFUSED_UNCONSUMED不意味着可以重开已exclusive创建的同一stage；CONSUMED/terminal/UNKNOWN绝不重开。无补批、fallback、换序、换目录或无界日志扫描。原once目录本轮不探测；未来发现已经存在就拒绝。

## 后续任务与本轮验收

### Task 1: 准入材料准备（未来，非本轮自动执行）

**Files:** 消费上表sealed引用和现有once/scope/receipt；如另获授权，只创建独立本次request与缺口处置材料，不改旧模板。

**Interfaces:** 输入为sealed pins/出处及明确范围；输出为P1–P7逐项真实事实/未知/拒绝理由、精确请求SHA，尚不是allow-once。

- [ ] 逐项闭合P1–P7；如需fresh内容重验、额外观察或软件变更，先固定精确范围并另获授权。本方案不自动重采已有内容。
- [ ] 审阅原预算及收集机制；无法满足则停止，交付具体缺项，不靠反复资源轮询或通用validator补位。

### Task 2: ONE适用准入与build-only一次执行（未来）

**Files:** 新SHA绑定review；输出仅原 `results/native-offset-once-attempt-v1/build/`。

**Interfaces:** 输入P1–P8及直接人类执行授权；输出B1–B4真实成功/失败/unknown记录，B5只按实有证据判定。

- [ ] 在全部前置条件满足时取得独立ONE适用review和明确build-only授权；不要求预先有B1–B5/new binary。
- [ ] 仅经原once入口执行一次，遵守上文顺序和全部停止条件；不提供本轮可直接运行的CLI或占位allow-once。
- [ ] 有界核查B1–B4/释放；失败或未知停止，不修回执为成功、不自动run、不重开。

### Task 3: 本轮方案验收（已做，范围有限）

- [x] 基于保存派生JSON/文档及必要当前源码契约区分P/B/run；没有Linux/资源/编译/运行/旧payload重采。
- [x] proposal采用非生产schema，stage仅build、decision null、所有资格及dispatch false；引用复制自保存回读记录，未hash旧blob/ZIP。
- [x] 本地新JSON解析、数值/字段/引用及本文静态对照，Git仅新文件whitespace检查；结果写新verification，不是生产验证/测试/新准入审查。

结论：**方案已准备，P1–P8尚未全部满足，未准入也未执行；完整实际消费闭包仍false。** 下一次有意义的动作是按明确授权关闭构建前缺项并形成可审查请求，而不是重复已封存采集或把构建后证据设成循环前提。
