# 现有 OpenVINS 构建目录：新增依赖、对象与日志实物

本次补采仅在原 `ov_msckf/build` 目录内，通过 Windows 标准文件 I/O 读取此前未保存的文件。上轮919份已取得路径作为排除表；新旧采集路径重叠为0。没有重新访问旧库、源码、头文件或工具，也没有执行 Linux/WSL 命令、CMake、编译器、原生目标、资源查询、安装或测试。旧封存报告、原始数据、ZIP、map、审查结论和生产代码不改。

## 实际补齐

一次 Windows 子进程用时4.063s，选择60条文件路径，完整取得52份稳定普通文件、52个SHA256 blob，实际读取186048617B。原限制保持单文件67108864B、总读取201326592B、27s读取窗口、30s父等待、5s terminate/5s kill和45s outer。下一对象为20403152B，会超过总上限，因此在读取前停止；不挑选更小对象继续、不追加批次，采集 complete=false。父进程的 complete=true只表示采集子进程正常退出，不表示证据完整。

- **34份实际 `.o.d`**：与上轮保存的 DependInfo.cmake 中34个编译单元逐项对应。全部目标名匹配预期对象路径，全部列出预期源码路径。解析得到1564个按词法规范化的依赖路径；其中112个可引用上轮已保存的实际文件观察，其余没有内容回执。本轮未沿这些路径补读头文件。词法规范化不是符号链接解析，依赖路径清单不含构建时输入内容哈希。
- **15份实际 `.o`**：全部纯字节解析为ELF64、小端、x86-64可重定位对象，未加载或执行。`.comment`均含 `GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`；相关调试字符串另存静态观察。它们只能说明保留对象中存在这些字段，不能认证编译器身份、源码内容或ABI。
- **3份日志/依赖元数据**：69245B的 `CMakeConfigureLog.yaml` 保存7个message事件和8个try_compile事件，包含历史配置探测的编译/链接输出，未出现 `ov_msckf_lib` 目标名。它不是34个主库编译单元及最终库链接的完整执行记录。本轮没有执行其中任何命令。119B的 `compiler_depend.ts` 是依赖管理时间戳说明；121B的 `Testing/Temporary/LastTest.log` 仅有Oct02的start/end，无测试用例结果，不能推为测试通过或本次运行。

上轮实际 `link.txt` 中的34个对象名称集合与实际 DependInfo.cmake相同；15份新增对象处在该名称集合中。这里只复用上轮Windows保存字节，不重新读取其Linux文件。`translation-unit-associations.json`、`dependency-path-index.json`、`object-static-observations.json`、`log-observations.json`和`link-name-correspondence.json`给出可复核关联及其证据引用。

## 仍然未知

19个对象未取得：下一对象因总大小界拒读，其余18个在停止后未尝试。7个选定日志/内部依赖路径不可用，错误原留：CMakeOutput.log、CMakeError.log、build.log、configure.log、compile.log、link.log和compiler_depend.internal。这不等于其他未搜索位置没有日志；本轮只枚举Testing子树并读取固定日志路径，没有全盘/历史目录搜索。

**source→object→旧库仍未证明。** `.o.d`记录依赖名称，`.o`中存在编译器/路径字符串，现存link.txt列出对象名称；三者没有构建时输入内容快照、完整34份对象、可信主库编译/链接执行及同一次构建会话的绑定。保存的配置探测日志增加了真实历史材料，但不能替代这些缺口。文件名、mtime、调试路径或版本字符串均不构成内容来源认证。

旧库291717384B超过原64MiB单文件上限的事实沿用上轮明确的实物观察；本轮没有再次stat/open/读取它。其当前完整SHA、ELF和ABI继续null/unknown，不用历史ef649cc填入，不strip、替换、重编或提高cap。现有production file_pin仍无法接受该大小，运行门槛未改。

Windows共享的dev/inode/权限、符号链接身份、非原子观察与原生Linux身份的差异保持；前后元数据一致只适用于本次共享视图。原工具/头/包/loader/ABI闭包和库来源、实测标定/noise/输入及未来原资源门槛/唯一适用准入仍缺。所有资格、dispatchable、runtime_graph_frozen和physical_dispatch_ready仍false，goal保持blocked/read-only。

后续分析仅读取保存到Windows的新证据和已引用旧文件；不再访问Linux。核验范围仅新payload/派生JSON一致性及新ZIP的CRC/member/hash，不是旧测试、旧封存重审、source/native/delivery审批或原生实验。原UNKNOWN/CONSUMED、预算/停止/cleanup、安全、truth仅score/abort和完整单机任务及后续目标不变。
