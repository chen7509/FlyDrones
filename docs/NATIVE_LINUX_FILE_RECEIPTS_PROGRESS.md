# 当前 Linux 文件回执：已采集，闭包仍不完整

本轮只通过 `\\wsl.localhost\Ubuntu` 读取实际文件，在 Windows 工作区保存新证据。没有调用 Linux/WSL 命令、`--version`、dpkg、readelf、ldd、编译器、CMake、SDK 或原生目标；没有查询资源、安装/写入 Linux、跑测试或修改生产源码。旧封存报告、ZIP、map、审查等级及已消费尝试不改。

## 已取得的实际材料

一次有界采集选择1054个路径，919个文件取得完整内容并通过该次 Windows 共享视图的读取前后元数据一致性检查，保存为907个去重 SHA256 blob。实际累计读取124940278B，采集子进程27.187s；内部27s总读取截止点触发后停止，未扩预算或换目录重试。`collection-completion.json` 的 complete 明确保留 false。其余状态为98个未解析 reparse、7个不可用、1个文件超限、28个非普通文件及1个截止中断路径。

- 工具：15个实际普通文件，包括 CMake、make、Python3.12、systemd-run/systemctl、time/timeout/env、versioned GCC/G++/cpp13 和 binutils；另有4个编译器组件文件。17个工具别名为未解析链接，不把 versioned candidate 冒充这些别名的真实目标。
- 包：当前 `/var/lib/dpkg/status`、115个选定包的230份实际 `.list`/`.md5sums`。455个已采文件与本地包 MD5 表匹配，比较中没有不匹配；这是本地数据库一致性，不是签名仓库或安装来源认证。
- 依赖：52份实际 CMake 配置，83个普通库候选文件；共100个实际 ELF 文件做了纯字节解析，保留 NEEDED/SONAME/RPATH/RUNPATH/解释器等可见字段。不执行或加载这些文件，不把候选集称为实际加载闭包或 ABI 验证。
- 头文件：从实际包清单选出18151个候选路径，只取得其中371个普通文件后到达截止。目录也在候选路径中，不能把18151称为全部文件数；这些主要是按排序先到的 Boost 路径，Eigen/Ceres/OpenCV、标准库和系统头尚未构成完整闭包。
- 当前 OpenVINS：实际 HEAD/master 文件指向 `69488123ed9362dd44b6f28e7f4680abbff1442b`；141个实际读取的源码文件与固定提交清单逐字节 SHA 相符，没有观测到不匹配。预期 `LICENSE`、`ReadMe.md` 路径未找到，因此不是完整143文件闭包。
- 现有构建目录：实际取得11份材料，包括 cache、Makefile、link.txt、flags.make、DependInfo.cmake、compiler_depend.make 及生成的编译器元数据。DependInfo 实际列34个编译单元，cache 保存 `ENABLE_ROS=OFF`，flags 保存 `ROS_AVAILABLE=0`、C++17 和原库 O3/-g3 等选项。它们是现存元数据内容，未执行或重现构建；也没有改成新 adapter 的 O2 配方。

实际本地包数据库记录 CMake3.28.3-1build7、GCC/G++13.3.0-6ubuntu2~24.04.1、Eigen3.4.0-4build0.1、OpenCV4.6.0+dfsg-13.1ubuntu1、Ceres2.2.0+dfsg-4.1ubuntu2、Boost1.83.0.1ubuntu2。版本来自当前数据库字节，不是运行工具得到的版本输出。

## 不能补造的缺口

1. **当前 OpenVINS 库为291717384B，超过保留的67108864B单文件上限。** 只取得其本次元数据，未完整读取，当前库 SHA/ELF/ABI 为 null/unknown。没有 strip、换库、重编或拿历史 ef649cc 等哈希填入当前绑定。现有生产 file_pin 的64MiB界也不能接受此文件；本轮没有修改该门槛。
2. `compile_commands.json` 在实际构建目录不可用；没有原始编译/链接执行日志、完整对象与 .o.d payload、当时的工具/头/配置输入快照或 source→object→library 回执。当前源码相符及 cache/flags/link 文件存在，不能证明旧库在构建时使用了这些字节。
3. Windows 共享返回 LX reparse 标签，但普通打开、`os.readlink` 和只读 FSCTL_GET_REPARSE_POINT 都无法取得其目标。失败原样保存；未改用 WSL 命令。Windows视图 dev=0、inode/权限/链接链不能冒 Linux 原生身份，所有 `linux_resolved_path` 均不预填。
4. Windows 共享目录名还将包名中的冒号投影为 U+F03A。原始目录名和 v1 分析原留；v2 仅为与实际 status 包名关联而规范化该转义，明确不授予原始 Linux 目录名字节或链接身份认证。文件绑定仍保留原共享投影与候选 Linux 名。
5. 头/系统启动文件/specs/sysroot、全部 CMake 实际读取文件、隐式链接输入、递归 loader 选择和懒加载库仍不完整。没有在本轮通过更多批次绕开截止点。包签名、仓库 origin、当前 Linux 原生 file_pin 和 ABI 均未证明。

`file-bindings-v2.json` 将919份实际内容绑定到 bytes/SHA/blob/共享前后元数据及包关联。`candidate-bindings-v2.json` 提供8个有实际普通文件支撑的工具/配置候选，但标记 not admitted；`existing-build-metadata-v2.json` 和 `missing-evidence-v2.json` 保存当前来源材料与逐项缺口。它们不伪装成可通过 once gate 的 `openvins-no-ros-current-build-v1`。旧45项运行模板未改，现有库 bound=false、当前SHA=null，所有资格/readiness/dispatchable 仍 false。

分析只读取本轮已保留的 Windows 文件，不再访问 Linux。首次临时打印包数据库漏写 UTF-8 导致 cp1252 解码异常，是 console-only 分析错误，非 Linux/原生失败；后续分析显式 UTF-8。v1 未识别共享文件名转义，v2有因地修正关联，两个版本及原始字节均保留，未回填 v1。没有旧测试、旧 archive/private475/history 扫描或第二 source/native/delivery 审查。

本轮新增的是当前实物观察与部分绑定；不是当前 OpenVINS 库来源证明、完整 Linux 依赖闭包、构建/运行准入或 PX4融合进展。goal 保持 blocked/read-only，automation ACTIVE，同 chat/branch/personal draftPR65。后续仍保留原资源/精度/sensors/速度/RTF/once/cleanup、UNKNOWN/CONSUMED及完整单机任务和后续目标；不因这次只读采集降低任何门槛。
