# 固定 EGO 构建的首次真实失败与行尾修正（2026-10-13）

**首次冻结构建流程已经实际执行，但尚未进入 C++ 编译。** 2026-10-13 19:48（北京时间），原v2在2892MiB空闲内存下通过2500MiB前置门槛，固定镜像/补丁校验并应用补丁后，被 `git diff --check` 拒绝。Docker退出2/OOMfalse，外层脚本退出1，未生成新镜像；清理后原命名容器查询为空。不是果蝇训练、策略或物理飞行失败。

## 根因与证据

固定 EGO23a8d5a191711dd65633df689bd00f55d4dea8f9 的 upstream traj_server.cpp原有274CRLF、header有141CRLF，没有裸LF；旧补丁保留原行尾。patch本身有96CRLF（含上下文/删除行），但实际日志只有**54条新增行的尾空白诊断**；overlay增量44+10同样为54。初始将96混成拒绝数量的记录经独立复核修正，原工具消息/提交保持可追溯。

Git默认不把CR视为行尾。官方 [core.whitespace文档](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corewhitespace) 定义 `cr-at-eol`，可识别CRLF而继续拒绝实际尾随空白。采用独立v3执行版本，明确参数 `blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol`，不设置全局配置、不关闭空白检查、不重写上游或补丁字节。实际测试工具为Git2.55.0.windows.5，不声称它与镜像Git完全等价。

旧v2所有输入/结果保持：原patchSHA `bcf739842f3868fb082efce4a9a82609a7d5eb0833dea6c39e80ed9c57433fe9`，run.ps1 `a4dbbac97e4e13016f04a13d7d9caccec06a699c25ce0ff216a18f15ecce6db7`，build.sh `71c15c8412841414a8a41d94cb44ae6bef67fa62b586f2af8d94215136e285b2`，前后均相同，实际运行前副本保存。旧binaries-before只代表基镜像已有二进制；trap保存的colcon日志来自已有镜像历史，不是本次编译。失败发生在检查后生成diff/调用colcon之前，不能把历史日志或旧二进制称新构建结果。原脚本只保留命名容器清理记录，没有完整运行时inspect/所有后代证据；不扩大cleanup或closure资格。

## 新执行版本与验证

`tools/benchmark/ego_causal_build_v3.sh` 相对v2只有上述Git命令一行改变。v3run.ps1仅更换独立容器名和输出镜像标签，资源/构建参数不变：原2500MiB宿主门槛、1536MiB容器声明限额、1CPU/networknone/128pids/1200s、同一个upstream/baseimage/原patch。新的build.sh SHA `baa2742cb343e97c77408075ec29278099851b2a32b9569a36cee518e8ee4b37`；run.ps1 SHA `acd64e458d149de48f64a9ec77640174faf6a1361be3051dda8769702fed3dc3`；prospective SHA `cb5f8a4a16731a845a120dafc1fb2005a3d1a4c1eda78abfa802c155a857bb22`。许可证、上游维护不确定、SDK/接口/资源选择沿用既有GPL3 EGO和Humble源码审计；Git工具为GPL2，不引入新依赖。

验证：**6个真实Git用例和76项邻近回归通过**，changed Ruff/diff通过，WSL `bash -n`退出0、PowerShell语法0错误。正常CRLF接受，而LF/CRLF尾随空格、空白EOF和space-before-tab仍拒绝。初始3失败/1通过是缺新文件的bootstrap；之后真正behaviorRED为1失败/3通过，旧命令拒绝正常CRLF；其余拒绝用例保持通过。扩大回归首次遗漏旧target安装的rosbags导致11依赖失败/65通过，修正PYTHONPATH复用既有版本后76通过；全部输出保留，不称算法RED或安装新依赖。没有重跑全库或声称实际C++编译通过。

独立复核确认一行策略和两处名称变化、四项输入SHA、6Git用例、旧源码行尾和54计数，并修正文档统计。teacher/runtime/实际同输入数值等价/融合/物理资格仍false。

## 尚未执行的部分

v3首次父级预检在读取进程状态后遇到内存<2500MiB，**没有启动run.ps1或Docker，未消耗实际v3构建尝试**。精确counter值当时没有持久记录，只保留程序拒绝条件，不能用之后的1882MiB回填原采样值。快照/拒绝在独立admission-v1目录保留。

下次仅在fresh资源及无竞争/无owned运行通过后执行已冻结、尚未尝试的v3一次，使用新的admission目录，不覆盖v2失败或v3预检拒绝。必须核验真实编译/生成输出和来源；成功后再做原版/补丁相同输入、状态、地图与时钟的数值比较。当前完整MaleCNS未训练，真实PX4/标定相机/teacher尚未合格，五机0.873RTF<0.95、首2sTIMESYNC及其他历史失败仍保留；不扩展5/20机、不降低原负载/门槛、不要求原生Linux。

证据 `evidence/ego-build-whitespace-dev-1701.zip` 封存旧实际失败、原输入、新冻结执行、全部RED/依赖失败/最终测试、研究与复核，按成员SHA/CRC验证；旧目录不删除覆盖。修正阶段可复核不代表完整构建或整个目标完成。
