# openvins_offset_reset_v2 一次运行准备计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本轮只完成准备交付，禁止执行下面的原生步骤；不再询问已明确的软件范围或资源选择。

**Goal:** 为独立 `openvins_offset_reset_v2` 目标提供可以逐项否决的一次构建/一次生产捕获方案，缺项时不启动。

**Architecture:** 先固定 Windows 当前集成源和上游 Git 提交的构建源，再用当前 Linux 工具/库/配置实物回执填满外部绑定项。准入审查只允许单一固定 offset、一个新进程、原生产 capture/sole wire/owned ULog 路径；当前 JSON 是非执行模板。

**Tech Stack:** Linux/GCC libstdc++、CMake>=3.20、C++17 adapter、OpenVINS69488123ed9362dd44b6f28e7f4680abbff1442b NO_ROS library、Eigen/OpenCV4/Boost/Ceres、现有 Python capture。

**Spec:** `docs/superpowers/specs/2026-10-18-native-offset-once-plan.md`

## Global Constraints

- 本轮不 configure/compile/import target/dlopen/run native/SDK/WSL/resource query，不重跑旧测试；所有命令模板均未执行。
- 仅 personal，不 origin/force/新 chat；所有旧封存证据和原审查等级不改。未申请/未准入不是新的资源拒绝或已消费原生尝试。
- 不以旧 executable 冒新 target。允许引用历史库 SHA 作追溯线索，不允许用其替代当前库实物及 build receipt。
- 不 PARAM_SET/ARM/offboard/EV enable/control。保留现有 `supported-ready-v1` 仿真激励及其原限制，不等于飞行任务。truth 仅独立 score/abort。
- 原精度/250Hz IMU/10Hz160x120 RGB-D/1ms physics/near0.2 far19.1/速度0.8/加速度1.2/yaw0.6/RTF>=.95 不变；本次25秒诊断不是120秒任务。
- pidfd denied/unsupported 必须停止，无 fallback/sysctl/提权/竞争进程清理。UNKNOWN/CONSUMED/AV/缺 payload/recorder gap 不补造或重放。

## Review Focus

1. C++17 配方是否仍链接预期 NO_ROS 库、同 OpenCV 主版本和兼容 C++ ABI；没有工具/库实物就拒准入，不能靠源码清单放行。
2. `find_package`/编译器系统头/链接器隐式输入/Ceres-TBB 懒加载是否遗漏；须有配置/depfile/ELF/实际 maps 回执，静态 AST/包名不是完整运行闭包。
3. 首个 ack 前的 native 初始化和 maps 观察窗口；当前 v2 不具备 PNG supervisor 的构造后 stdin barrier，不能复制旧协议冒已实现。
4. 单一固定 offset、标定来源和 reset 可达性；不得用测试7ms、调用者零计数、重启或故障注入宣称实测标定/真实上游 reset。
5. scope/worker/decode/cleanup 超时及部分证据：全部原 cap 保持，超时后的逃逸后代未知必须保留，不能把“文件缺失”改为“没有 effect”。

这些是未来一次准入审查必须逐项回答的条件；本轮未以重复测试或第二次旧 source review 处理。

## 1. 本轮已经完成的可核查准备

- [x] 保存18个显式入口的修改前 bytes/SHA 与 Git blob；静态追踪121个当前本地文件、381条本地 import 边及2处动态加载位置。`current-source-manifest.json` 明确这是 AST 可见闭包，不能保证动态模块/全部 Python 环境。
- [x] 取回固定提交的三个完整构建源码子树 `ov_core`/`ov_init`/`ov_msckf` 加 LICENSE/ReadMe，共143文件1434868B，逐项校验 Git blob SHA1 并另存 SHA256；不是当前 Linux checkout/library 证明。记录在 `upstream-build-source-manifest.json`。
- [x] 从固定 `ov_msckf/cmake/ROS1.cmake` 静态展开34个库编译单元，保留 NO_ROS 排除规则。没有运行 CMake，也没有重建上游库。清单为 `upstream-no-ros-library-sources.json`。
- [x] 修正独立 adapter CMake 标准14→17，因为实际本地 `exclusive_probe_output.h` 包含 `std::filesystem`。这只消除源级标准冲突，不证明编译/链接/ABI成功；旧15-pin审查仍是原结果，此改动待新方案准入审查。
- [x] 保存非执行 `run-plan.json`、依赖/回执要求和下面的预算/停止矩阵。没有构造可自动默认放行的 launcher 或新增小 validator。

来源说明：整仓归档请求触及32MiB上限后停止，未提高上限重试。Git tree 显示 `ov_data` 单独394016623B，因此改为目标构建源子树逐文件读取。这是有原因的输入准备路径调整，不是换目录重试原生版本。首次超限响应体未保留，start/failure记录和此限制保留；不能声称那次完整下载已保全。上游 dataset/config 未当作新运行输入，旧数据也未提取或复跑。

## 2. 依赖闭包和回执，缺一即停

| 层 | 本轮已取得 | 尚需填充的实物/证明 |
|---|---|---|
| 当前 adapter 和生产接入 | 当前121文件快照；独立 CPP/header/exclusive header/CMake17 | 发布后/Linux部署前后同 bytes/SHA；不借旧382 membership或旧运行 pin |
| 上游构建源 | 固定提交143文件及34库编译单元 | 实际库构建使用这些源/配置的回执，及当前 Linux 源树比对 |
| 工具链 | 明确需要 CMake、GCC C++17/libstdc++、cc1plus/as/ld/ar/ranlib、Make、timeout/time、Python 和 scope manager | 每个 resolved path/bytes/SHA/版本/软件包、编译器 specs/sysroot、启动文件/标准头、CMake modules/imported targets、全部响应文件；本轮未执行任何 --version |
| 开发依赖 | Eigen3；adapter OpenCV4 core/imgproc；Boost filesystem/system/thread/date_time/chrono；Ceres | 精确版本、include tree/配置路径/SHA、CMake imported targets。库所用其它 OpenCV modules 由真实 NEEDED 扩展，不能只写 core/imgproc |
| 运行 ELF | 明确必须处理 loader/libc/libm/libgcc/libstdc++、OpenVINS、OpenCV、Boost、Ceres 及其递归依赖 | 实际 ELF headers/NEEDED/RPATH/RUNPATH/SONAME/version需求、symlink链/device/inode/SHA、包归属及递归解析；不能盲用 ldd 加载未知对象 |
| 间接/懒加载 | Ceres 可能关联 glog/gflags/SuiteSparse/BLAS/LAPACK/TBB；原已声明 libtbbmalloc2:amd64 2021.11.0-2ubuntu2 只作特定触发追溯 | 以实际 NEEDED/配置为准决定存在项，不能假定所有包都有/必须安装。first_acknowledged_imu 等实际 maps 必须在同一 inventory 中；未知映射拒绝，不加白名单 |
| Python/仿真链 | AST 已列外部名字/动态位置；生产 v2+receipt flags 可审查 | 当前 Python NumPy/PyYAML/pymavlink/pyulog、protobuf/Gazebo/SDF/Agent/PX4 插件及系统闭包实物。cflib/djitellopy 是静态分支可见名字，不要求安装或启用实体后端 |
| 运行输入 | 明确10文件 managed 标定闭包、三 native YAML、wire/execution/runtime/Agent/reference/gauge 文档关系 | 新测 calibration/noise与真实 signed integral-ns artifact及当前全部 SHA/路径/字节；新 exact execution/binding/scene。测试 artifact 和历史静态候选不是实测值 |

对 `ov_msckf_lib` 只接受明确 NO_ROS、固定上游源、相同 OpenCV4 和编译 ABI 回执。历史 ef649cc... 库只作为历史，不等于当前可用。若没有足够回执，不能自动重建上游库来“补齐”；上游重建另需同等完整方案/原预算准入，不能藏进本 adapter 的1GiB预算。

构建时必须保留 `CMakeCache.txt`、所有实际读取的 CMake config/module、`compile_commands.json`、完整 compiler/linker argv/response files、`.d`系统头列表、对象/ELF/工具前后 pin、raw stdout/stderr、实际 scope identity/计数和退出/cleanup。仅 success exit0 或新 binary hash 不构成 source→build→loaded library 的回执。未来 native 初始化前后/first IMU/camera/terminal 的 owned maps 是实际运行证据，不可能本轮补造。

## 3. 一次构建配方：只构建新 adapter，不构建库

`run-plan.json` 的 bindings 当前均未授予运行权；绝对路径和 digest 必须由实物填充并冻结。以下仅为 argv 结构，不是可复制运行的已准入 shell：

```text
cmake -S ${DEPLOYED_REPO}/tools/benchmark/native_offset_reset_v2 -B ${ABSENT_BUILD_DIR}
  -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_CXX_COMPILER=${PINNED_GXX} -DCMAKE_MAKE_PROGRAM=${PINNED_MAKE}
  -DCMAKE_CXX_FLAGS_RELEASE=-O2 -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
  -DCMAKE_TOOLCHAIN_FILE=${PINNED_TOOLCHAIN_FILE}
  -DOPENVINS_SOURCE_DIR=${PINNED_UPSTREAM_TREE}
  -DOPENVINS_LIBRARY_DIR=${PINNED_LIBRARY_DIR} -DOV_MSCKF=${PINNED_LIBRARY_FILE}
  -DEigen3_DIR=${PINNED_EIGEN_CONFIG_DIR} -DOpenCV_DIR=${PINNED_OPENCV4_CONFIG_DIR}
  -DBoost_DIR=${PINNED_BOOST_CONFIG_DIR} -DCeres_DIR=${PINNED_CERES_CONFIG_DIR}
  -DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF -DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF
cmake --build ${ABSENT_BUILD_DIR} --target openvins_offset_reset_v2 --parallel 1
```

两条放在同一300s build envelope内，不给 configure/build 各300s。首次 configure也可能探测编译器，必须在准入后、先持久化 build-attempt consumed 状态才执行。禁止 `make all`、run_simulation、upstream rebuild、网络依赖安装、OpenCV3 fallback、临时改flags、旧binary fallback。GNU libstdc++/filesystem与NO_ROS/Ceres/Eigen ABI仍要实际构建证明；C++17不是ABI证明。

toolchain文件必须绑定 compiler/make/sysroot/允许搜索前缀；所有 find_package 的实际选择写入回执，不允许未声明的 user package registry 或 `/usr/local` 抢占。缺头/库或超时即 build失败，保留目录，不重新configure或换目录重试。编译完成后审查其依赖/回执，不自动接着运行。

## 4. 唯一生产运行：一个固定 offset、一个 native 进程

在独立 run gate通过后，使用现有 `capture_disarmed_sensors.py` 普通生产路径。必须通过现有 `declared_command(args, python, capture_script, launch_environment)` 生成最终 exact argv并冻结，不能伪造执行契约或把任意callback称为认证。JSON中全部未绑定变量必须先有实际文件/哈希；当前模板不能当作 `capture-execution-*` 文档使用。

固定 flags：`--online-estimate-feed --native-estimate-profile offset-reset-v2 --disarmed-odometry --consume-disarmed-odometry-evidence --record-owned-ulog --logger-diagnostic-profile disarmed-receipt-v2 --source-fanout-profile ready-shadow-heartbeat-estimator-v1 --motion-profile supported-ready-v1 --physics-trace-profile substep-ready-v1`。

路径 flags：`--output/--shadow-binary/--shadow-config/--managed-source-config/--managed-source-sha256/--execution-contract/--runtime-binding/--wire-config/--reference-module/--reference-sha256/--agent-runtime-config/--trajectory-gauge-policy`，全部来自新实物绑定。Logger当前实际要求Agent config，不能省略它来绕过依赖；不因本计划重新编DDS/固件。实际 native argv由生产factory构造：

```text
[new_binary, estimator_config, exclusive_states.jsonl, exclusive_fast.jsonl,
 fresh64hexnonce, decimal_signed_offset_ns, owned_child_ack_fd]
```

最后一个fd只由原 NativeClient 的 owned pipe/pass_fds 提供；不可手写旧fd或在终端直接运行native。一个nonce/manager只能使用一个固定offset；第一次运行的值必须取自新artifact，精确整数ns、非零、绝对值不超过1e9，且原200ms lag/250ms pending/4ms IMU历史因果界实际可满足。无法证明非零时不能改写artifact“制造”它。另一符号必须另有独立科研问题/来源/新准入；不自动第二run。

允许本次回答：该单符号真实消费、physical20ms unique fast targets、每call cache invalidate、camera/filter不变、PID/session/offset/reset0及禁用EV的logged receipt/aid观察和owned cleanup。必须有实际初始化后成功传播样本，只有ack/未初始化/空输出不算成功。

不能回答：另一符号、实测标定准确度、质量、任意posejump/上游真实reset、positive EV fusion或飞行。当前manager没有reset API/外部fault命令，legacy restart/source-loss fault flags在v2被拒；原生exit/kill不是reset。首次运行若没发生可达reset，报告reset分支未覆盖，不能要求它“必须通过reset测试”而暗中新增注入。

## 5. 预算、停止条件及一次性状态

| 阶段 | 不超过的原界 / 本方案选择 | 必须停止的条件 |
|---|---|---|
| 未来build准入 | 原PNG compile reserve双2GiB保留；本方案更保守，对build和run均要求双host>=4GiB，无竞争/owned冲突；本轮不测 | 任一值缺失/陈旧/不足、未知竞争或旧release；写firstfacts后拒绝，无反复poll/杀竞争 |
| 元数据工具 | 原每query10s/2MiB每stream/TERM5+KILL5，metadata30+5/45outer等原界仍绑定 | 输出超界、不完整reader、非zero/未知owned身份；不得因工具慢而加预算 |
| adapter configure+build | MemoryMax1GiB/swap0/CPU100%/Tasks64，单并行/O2，300s inner/330s outer；不加upstream build | 任一源/工具/库漂移、选择不唯一、编译失败、OOM/timeout、未知映射/cleanup；保留失败，不重试 |
| 未来run准入 | 完整current build receipt+inputs+freshpins；唯一新run admission，双host4GiB；不复用已消耗v3/v4/PNG/EGO版本 | 任一绑定null、权限/预算/执行契约/审查不成立；不运行旧exe代替 |
| 生产capture | 原25sim秒/worker300s/scope4GiB swap0 CPU100% Tasks256/315s inner+TERM kill-after10/330s scope wait/360s outer，不扩大 | 原sensor/source/clock/pose/safety/RTF拒绝、worker/父进程deadline、OOM、pidfd不支持。25/.95≈26.32s仅physics时间估算，不是整体wall实测 |
| native channel | 2s总write+ack；ack8192B；camera57600B；fast行16KiB；native普通finish wait3s+kill/wait3s | malformed/seq/sample/PID/nonce/offset/reset漂移、IMU gap>4ms、camera causal越界、非finite、cache/state改变、child loss、partial/EOF/timeout |
| receiver/terminal | 原freshdisarmed/EV0/receipt<100ms、full/short/no-return分别保留；ULog64MiB/4096send/300s总deadline，原metadata/segment界不变 | armed/EV非0或过期、源loss、clock/ownedsocket/数据漂移、无关联ULog/接收/aid证据；never PARAM_SET/ARM |

所有terminal work在同一原总预算内，不能把cleanup和解析另计。同步filesystem/parser不能hard-cancel；必须保留该限制，由原外层scope/watchdog停止并记不完整。首次真实耗时若不足以在原界完成，则拒绝/不完整，不能声称cleanup成功或延长预算。只对已证实owned句柄/unit+InvocationID/ControlGroup做原bounded cleanup，未证实后代保留UNKNOWN。

状态顺序：`PLAN_ONLY → CURRENT_RECEIPTS_BOUND → ONE_ADMISSION_REVIEW → BUILD_GATE → BUILD_CONSUMED → BUILD_RECEIPT → RUN_GATE → RUN_CONSUMED → TERMINAL_EVIDENCE`。绑定条件按阶段检查：build只要求源/工具/现有库及build准入输入；new binary/depfile/link回执是build输出，不能反过来当作开始build的前提。run必须等这些输出完整，再绑定真实运行输入和run gate；native maps/ack/ULog/cleanup是run输出，不是提前填造的输入。ONE方案审查必须写明这些输出的否决条件，不预先批准未知输出。任一失败终止该路径，没有自动fallback/restart。gate拒绝发生在构建/运行前时按原适用规则保留REFUSED_UNCONSUMED；一旦对应configure/target启动就不能恢复为unconsumed。每个原生阶段的首次观察及attempt record必须先exclusive持久化，不先创建可重开的旧study再补记。

## 6. 哪些还可由软件补齐，哪些需要外部事实

| 缺口 | 类别 | 具体后续交付 / 拒绝默认 |
|---|---|---|
| v2 prefeed identity barrier | 软件可补，但本轮未实现 | 若新准入要求构造后、首feed前的maps/二进制身份，需把明确readiness/barrier接入v2及生产client，保留实际PID/原deadline/cleanup并单独验证；不能借PNG旧argc/marker协议冒已支持 |
| 具体once coordinator/compile receipt producer | 软件可补，但本轮只给合同 | 绑定本JSON到实际firstfacts/consumed/pidfd/scope/receipt生产器；无任意argv通道、无旧consumed executor入口。实现后需其专属验证和同一新准入审查，不是现在授予执行权 |
| 正负两符号/真实reset的额外覆盖 | 研究/软件设计加实测 | 明确另一新样本来源和可达上游生命周期触发，区分诊断注入与真实reset；当前一次scope不覆盖它们，不能靠元数据填满 |
| 当前Linux tool/header/library/package及upstream build receipt | 外部实物条件 | 可读并可绑定的真实文件/路径/包版本/构建回执；本轮不能从Windows源码或历史hash推定。缺失时该层闭包就是未完成 |
| fresh资源/无竞争/cgroup/pidfd权限 | 外部时点条件 | 原准入窗口实际观察；本轮明确未查询，旧Windows1.44GB快照不当作当前值，也不当成已改善 |
| measured calibration/noise和新输入 | 外部测量条件 | 原预算内真实camera/IMU捕获、标定与样本时钟证据；静态sim参数/analytic fixture/旧数据重放不能代替 |
| 编译/ABI/加载/传播/reset/receipt/RTF/cleanup | 实际执行条件 | 只有今后准入后的当前目标运行能回答；本轮0次compiler/native/oldtests/resourcequery |

## 7. 审查与交接

- [x] 本轮executor自查：模板、源graph、143文件blob、34编译单元、CMake17理由、未绑定null、预算/拒绝条件及边界逐项可追溯。只做静态检查，不称pytest/compile/native验证。
- [ ] 在任何未来原生动作前，绑定当前实物、关闭需实现的软件入口，再对新目标完整source/tool/library/recipe/budget/once/cleanup做ONE适用准入审查。旧C0/I2/M2和C0/I1/M0 source reviews不授予该权。
- [ ] 执行前以实际新receipts填充未绑定项并冻结发布；所有blockers仍拒绝默认。没有本轮资源或native尝试。

本方案已可审查，但尚不可执行；没有把当前缺口归咎于必须换机器，也没有把所有后续工作都叫“待外部准入”。完整source/run evidence和新软件入口分别列明，后续单机mission/常规built planner、heldout/完整MaleCNS/公平upstream/HITL实飞目标保留。
