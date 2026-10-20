# 五份编译组件的只读内容回执

本轮仅采集用户明确指定的`/usr/libexec/gcc/x86_64-linux-gnu/13/`下cc1plus、cc1、collect2、lto1、lto-wrapper。五份全部取得完整内容、实际Linux身份及前后描述符/链接检查，均stable；不再将这五份说成“只有身份、未取得内容”。这不等于工具链或新请求全部完整。

| 文件 | 字节数 | SHA256 |
|---|---:|---|
| cc1plus | 32675168 | `840b332fb62ec6f694ac77d91fe69ef7f80b0d69512ed89374af0ee7a506255d` |
| cc1 | 30487984 | `5d1679131184e2de4435b426eb264bf13472fe026db8e5c6bc97445814e8e2f4` |
| collect2 | 336056 | `4d1f341ae5b763b513258ee2812422a45e063c30a2f1924a0cf63d3699f3a158` |
| lto1 | 29352624 | `7c9bdc474948b9127b5942f0f260ecc7067fb3afbb54fcbe2ddf598b9889edc8` |
| lto-wrapper | 831800 | `f6d39bcfb1c2798c704e275a4ed2c1fe6374ebfb6aa0c5f3f3b6c669e1ff2e13` |

每份解析终点均为表中同名绝对路径，实际regular file，无符号链接。保存的device/inode、模式、uid/gid、nlink、mtime/ctime及前后字段在file-bindings.json中。path/resolved/bytes/SHA四字段的新观察绑定另见new-file-pins.json，仅适用于此次采集时点。

一次只读WSL标准库观察器：父进程0.719s，Linux记录0.545s，exit0，读线程关闭，collection_complete=true/exact_five_complete=true。共93683632B、5份完整回执/5个SHA blob，无partial、无错误、未触限。元数据帧正文5522B；stderr132B为既有WSL localhost代理未镜像提示，无网络请求或修复重试。Linux身份字段不是历史调用或包来源认证。

原单file67108864B、total201326592B、27s读、30s父wait+5s terminate+5s kill、45s outer、metadata/stderr各2097152B和40linkhops保持不变。选择只有五条路径；file/aggregate/time/metadata触限均停止，不挑小文件补满、换顺序、追加批次或提高上限。

采集前只读取既存派生JSON建立排除集，1997条已知内容路径/解析拼写及1655对既存观察到的device/inode保守排除，连上一轮未闭合内容也排除。没有重读或重hash旧payload/archives；全局未发现硬链接及未来内容连续性仍未知。必要的父目录lstat用于解析五个授权路径，不做目录枚举。解析终点若超出精确五份则拒读；本次未发生。

没有采CMake模块、其他工具/头/库/日志或旧ov_msckf/build内容，没有编译、configure、link、执行这五份组件或任何原生目标、SDK、资源刷新、Linux文件写入。仅必要的隔离Python观察器执行；其自身及隐式运行依赖未获得认证或完整保全。之后只分析和封存Windows保存的新结果；helper AST/新归档完整性检查不是测试、ABI或原生运行。

仍未知：编译driver是否实际调用这些组件、其隐式specs/sysroot/头/配置输入、完整当前工具链/源码/包及递归和延迟loader闭包、包来源认证、ABI、实测calibration/noise及未来fresh资源/无竞争/cgroup/pidfd和适用准入。此前保存的工具/配置内容哈希未刷新；这五份新pin不替代其他缺失binding。生产请求/准入模板、旧证据和旧库来源G1–G7均未修改，所有qualification/readiness/dispatch继续false。

本次精确五份选择已结束，不自动再采任何文件、构建或运行。goal blocked只读，automation ACTIVE，仅personal原分支；全部旧UNKNOWN/CONSUMED和原预算/安全/完整单机闭环目标保持。

结果目录：`results/native-linux-compiler-five-20261019/`。
