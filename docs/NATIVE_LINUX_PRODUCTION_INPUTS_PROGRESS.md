# Linux生产源码、toolchain与命名输入绑定

用户明确要求“继续按顺序补齐Linux生产源码绑定、toolchain回执和完整输入闭包，先不编译或运行”。本轮完成了生产源码和toolchain/回执的实际Linux文件绑定，以及当前命名输入集合与静态依赖关系的补齐；**完整实际消费/运行闭包仍未证明，未获得构建或运行准入**。

## 生产源码与toolchain

Linux实际可见的生产根为`/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility`，与本工作树对应，无需复制或改写生产代码。静态追踪当前入口得到128份本地源码、411条本地import边及2处动态加载位置；Linux逐份回读全部与准备的工作字节一致，包含现有once校验要求的12份源码/CMake。新`current-linux-source-manifest.json`使用生产契约的`native-offset-current-source-v1`结构，保存实际Linux path/resolved/bytes/SHA；没有导入或执行生产模块。它证明静态本地源码集合，不认证完整Python/SDK/FFI运行环境。

选定toolchain为`results/native-linux-production-inputs-20261019/toolchain-native.cmake`，已单独在Linux完整回读。它声明13份已观察工具的路径/pin、sysroot `/`、搜索前缀`/usr`，忽略`/usr/local`与`/opt`，关闭package registry和环境搜索入口，不设置try-compile shortcut。它尚未交给CMake解析/执行，不证明实际driver/sysroot搜索或ABI。

首版`toolchain.cmake`保留，其曾被实际观察，但未选作最终配方。最终native变体去掉强制`CMAKE_SYSTEM_NAME`，避免给本机路线引入cross-compile语义；未修改或覆盖首版。生成与观察分开：source manifest、v2 toolchain receipt、最终v3输入清单/引用索引/binding候选均完成Linux回读；以`final-receipt-bindings.json`连接实际观察。旧v1/v2生成时的pending字段保留，不能当成最新状态，不能倒写成预先观察。

## 命名输入和静态关系

| 命名组 | 绑定路径条目 |
|---|---:|
| tools | 20 |
| system_headers | 1828 |
| cmake_modules（含配置与显式toolchain文本） | 1205 |
| link_implicit（含启动文件、脚本、loader输入） | 20 |
| libraries | 105 |
| packages | 234 |

最终引用索引有3677条路径，逐条保留实际观察phase/pin/blob。这是跨时点集合，组间可有交集，不是3677份独立新文件、原子快照或已准入请求。原143份源码、此前1457头和五份编译组件未重采；旧生产模板和45bindings未填充。

实际补齐1046个先前未有当前内容pin的已知终点后，静态解析新增和必要保留ELF动态段、当前package-list字节，继续追踪新发现引用：递归CMake配置、共享库启动文件/`libc_nonshared.a`、loader配置，以及gfortran/isl/mpc/mpfr/systemd-shared/gflags/unwind等库。每份选择结束都没有触限，后续仅源于新引用，不是触限补批或换目录重试；后续选择持续扣减原总字节/metadata/read时间余额。

最终覆盖129份ELF、374条NEEDED边，已观察的每个NEEDED名称都有实际内容候选，未绑定名称为0；不证明loader实际选用了该候选。loader cache中仅提取精确路径字符串作引用索引，没有冒称完整解码cache条目/flags/hwcaps或实际选择。PAM→audit→cap-ng递归逐项保留，未执行任何库。

另外，libc/libm链接脚本有4条绝对别名尚未在实际pin键中。本轮为绑定这4个真实消费拼写回读4336800B已知内容，单列为别名上下文重观察，不冒4份新内容、新SHA或全局硬链接发现。四条脚本绝对引用现在均已绑定；原库、对象、build日志未访问。

## 实际范围与上限

按生产、依赖、新引用身份/内容和新回执分开的12次必要隔离WSL标准库观察，Linux均不写文件，无compiler/configure/link/native目标、SDK、tests、资源/竞争查询、网络、安装或控制。Windows只保存本轮新文件；没有创建或探测原native once attempt目录。

共1306份完整stable文件观察（含生成回执与已知别名内容，不等于全是新独立内容），payload123236864B，metadata正文1483814B+3971LF=1487785B JSONL，stderr总1584B。全部exit0/readers_closed=true，无partial/errors/触限。累计实际Linux观察6.521850s，父进程等待12.721s；这是各观察的实测累计，不是整个分析任务墙钟时间或硬实时保证。

每次保留file67108864B、read27s（首metadata最多10s仍在读界内）、parent30s+terminate5s+kill5s、outer45s、40linkhops和最多6000选择。总payload和metadata也小于本轮原201326592B/2097152B；后续按余额收窄，没有乘调用次数扩容。stderr各次132B均为既有localhost代理未镜像提示，无网络请求/修复重试。

保留文件/包清单和ELF动态段仅为此次授权的输入引用分析读取，不是重hash旧档案或全局payload审计。观察器Python及隐式依赖不冒完整环境、来源认证、FFI/custody、hardcancel或后代闭包证明。完整先前history读取coverage沿本连续对话前轮实际读取，不伪造新native审查。

## 仍不能写成完成的部分

1. 新35-TU构建的实际系统depfiles、CMake trace、compiler内置specs/搜索与真实配置选择尚不存在；命名候选都具备字节不等于实际输入无遗漏。
2. ELF和cache路径不证明loader的上下文/hwcaps选择、符号版本、ABI或lazy加载。`ld.so.conf`中的glob目录没有枚举，只观察索引中的精确配置文件。
3. 两处动态Python加载和外部模块仍需未来具体运行配置及环境/SDK/FFI绑定，当前静态图不冒完整运行闭包。
4. package status/list/md5内容不是签名来源认证，也不提供全环境原子或futurefresh连续性。
5. fresh资源、无竞争、cgroup/pidfd、预算/停止/cleanup和独立一次构建准入仍未授予或查询。新库/adapter构建回执、释放、ABI/实测标定noise与run准入是后续独立阶段，不能循环要求build前已有新产物。

因此最新`full_input_closure_complete=false`、`full_request_complete=false`和所有qualification/runtime_graph_frozen/physical_dispatch_ready/dispatch false。现在不能继续说“尚无Linux生产源码/toolchain回执”，也不能把静态集合说成完整已准入闭包。没有重做5cf6c6c软件链，旧库32/34、G1–G7和全部UNKNOWN/CONSUMED/原预算安全及完整单机/后续目标保持；goal blocked、automation ACTIVE、仅personal原分支/PR65。

详细新记录在`results/native-linux-production-inputs-20261019/`，最终有效命名输入和binding候选为`final-v3/`，toolchain receipt和静态ELF结果为`final-v2/`，实际生成文件回读在`final-receipt-bindings.json`。各旧生成版本原样保留，本轮到封存发布结束，不自动新采集、修改生产、编译、运行或刷新资源。
