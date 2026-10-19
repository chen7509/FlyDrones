# 新源码路线：Linux身份与新增输入观察

本轮只做一次有界只读WSL文件观察。新请求仍不完整，不能构建或运行。生产源码、原请求/准入模板及旧证据未修改。

## 实际结果

固定选择3524条精确路径；3518条取得Linux身份/链接观察，6条精确路径不可用。排除988条此前取得过内容的路径；保守加入包名投影拼写后，共1148条内容排除拼写。还排除这些路径在本次观察到的解析终点及设备/inode别名。没有全局硬链接发现保证。

749份新文件取得完整内容及前后描述符/链接检查，合计12063908B，734个去重SHA blob。另有215B未闭合传输，实际读取共12064123B。749份中4份为此前未取得的库候选，745份为保存的cmake-data包清单所列模块候选；这些模块不等于新构建实际消费的依赖。

一次父进程用时1.625s，正常退出0，读线程已关闭。Linux记录的停止原因是`2MiB metadata cap; no second selection`，collection_complete=false。没有超时终止或第二批。元数据帧正文2089117B，Windows保存的JSONL另含6024个LF分隔符，共2095141B，均未超过2097152B；stderr132B。正常退出只说明观察器/传输结束，不说明选择或依赖闭包完整。

## 新取得的当前身份

| 请求路径 | 实际观察到的解析终点 | 内容状态 |
|---|---|---|
| `/usr/bin/c++` | `/usr/bin/x86_64-linux-gnu-g++-13` | 旧内容排除，仅补身份 |
| `/usr/bin/gmake` | `/usr/bin/make` | 旧内容排除，仅补身份 |
| `/usr/bin/python3` | `/usr/bin/python3.12` | 旧内容排除，仅补身份 |
| `/usr/bin/ar` | `/usr/bin/x86_64-linux-gnu-ar` | 旧内容排除，仅补身份 |
| `/usr/bin/ld` | `/usr/bin/x86_64-linux-gnu-ld.bfd` | 旧内容排除，仅补身份 |

`c++`的完整观察链为`/usr/bin/c++ → /etc/alternatives/c++ → /usr/bin/g++ → g++-13 → x86_64-linux-gnu-g++-13`，相对链接按各自父目录解析。设备/inode、模式、uid/gid、nlink及时间字段保存在file-observations.json。这是采集时逐路径观察，不是原子构建时快照、历史编译器身份或内容认证。

从既存包清单精确选择的`/usr/libexec/gcc/x86_64-linux-gnu/13/{cc1plus,cc1,collect2,lto1,lto-wrapper}`均观察到实际regular file。其中cc1plus32675168B、cc130487984B、collect2336056B。这些文件没有因大小被拒；第二遍尚未读到它们即触及元数据上限，当前内容SHA仍null。此前`/usr/lib/gcc/...`下的三个同名路径不可用，不能据此说libexec组件不存在。

## 新保存的四份库候选内容

| 请求路径 | 解析终点 | 字节数 | SHA256 |
|---|---|---:|---|
| `/usr/lib/x86_64-linux-gnu/libjsoncpp.so.25` | `/usr/lib/x86_64-linux-gnu/libjsoncpp.so.1.9.5` | 219304 | `72527df2ef55a4af661f691e8be0eeece16a8e9bfc9a2a21971d41738e84b67b` |
| `/usr/lib/x86_64-linux-gnu/libglog.so.1` | `/usr/lib/x86_64-linux-gnu/libglog.so.0.6.0` | 155096 | `cc080fc134a77c4a2e415e2143566aa925d01a858592a9e660eb5430c56bddf1` |
| `/usr/lib/x86_64-linux-gnu/liblapack.so.3` | `/usr/lib/x86_64-linux-gnu/lapack/liblapack.so.3.12.0` | 7268368 | `851bb1fc5833ede9ed704b4417a251a899976d5e0915de40452615187a65278f` |
| `/usr/lib/x86_64-linux-gnu/libblas.so.3` | `/usr/lib/x86_64-linux-gnu/blas/libblas.so.3.12.0` | 677880 | `e748efcae5753fe4a652877fccdb5895ac6f7605668a2db878b19c914e78e3a8` |

new-file-pins.json保留749份新内容的path/resolved/bytes/SHA绑定，仅适用于此次观察。没有load、执行、ABI或实际loader/链接消费证明；四份新库不等于完整ELF依赖闭包。

## 明确保留的缺口

- 1000条路径仅补Linux身份，旧内容未重读/重hash，当前内容仍未知。候选工具及依赖配置目录因此不能直接填为完整的新请求绑定。
- 1768条路径只取得身份，未取得内容。选择把大量CMake模块排在新编译组件及头文件之前，元数据上限先耗尽。这是本次选择顺序的限制，不能用745份模块数量替代关键组件/头文件闭包。
- `Modules/Platform/BlueGeneQ-static.cmake`虽收到215B，但未发出end回执，payload-1752.partial不生成当前pin。另15个带.partial后缀的文件有完整end回执，是不同新路径的重复新内容保留件，不能和这1份未闭合传输混淆。
- 精确不可用路径仅6条：`/usr/lib/gcc/x86_64-linux-gnu/13/{cc1plus,cc1,collect2,specs}`及固定上游根下`LICENSE`、`ReadMe.md`。这不是其他位置/拼写不存在的证明。固定143源清单及当前Linux源码内容闭包仍未补齐。
- toolchain_file/receipt、header_package_manifest、current_linux_source_manifest、隐式工具/头/配置、递归及延迟loader、包来源认证、ABI、实测标定/noise与未来fresh资源/准入要求仍未闭合。目录身份不证明配置消费，历史depfile/包清单不证明本次实际输入。

原67108864B/file、201326592B/payload、27s读、30s父wait+5s terminate+5s kill、45s outer及2MiB元数据/stderr界不变。本轮只有一份冻结选择，不重排补批、扩限、挑小文件补满或重采。

Linux端只执行必要的隔离Python标准库观察器，使用lstat/readlink及只读文件描述符；观察器解释器本身未获得身份认证。没有shell/package/version/compiler/configure/link/原生目标、资源查询或Linux文件写入。stderr保存WSL的localhost代理未镜像提示；无网络请求或修复重试。此前本地打印U+F03A包名出现cp1252编码错误，发生于采集前，仅控制台输出失败，原说明不冒原生失败。

整个旧`ov_msckf/build`前缀被排除，旧库/32份对象/两个超限对象/日志未访问，旧来源G1–G7状态不变。新请求/ABI/运行资格、dispatch、runtime_graph_frozen和physical_dispatch_ready继续false；goal保持blocked只读，automation ACTIVE，仅personal原分支。

对应结果：`results/native-linux-fresh-input-bindings-20261019/`。本轮之后只处理已保存的新结果，不再自动访问Linux。
