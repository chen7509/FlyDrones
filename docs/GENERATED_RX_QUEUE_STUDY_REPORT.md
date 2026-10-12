# Generated RX 队列试验：缺失元数据拒绝

## 结论与分类

唯一新声明opaque-generated-rx-v1失败：3个55字节opaque包实际发送完成；首recvmsg准确返回首payload/peer、flags0，但ancillary_count0。接收器没有返回可用packet，锁存缺失metadata并停止；剩2包未消费，option-drift第二例未执行。不是果蝇训练或VIO精度失败。arrival/source/clock/fusion/training权限仍false。

已验证：软件严格声明/固定ABI/来源/故障/partial保留；真实首包无metadata时拒绝，没有读时补造；冻结输入/模块origin/owned FD与原owned组清理。仅实现：独立本地opaque诊断，不连接实际PX4/ROS/VIO/控制/训练。未测试：cold/steady差异、后两包元数据、原生option-drift、实际PX4/源时钟/真实传感器/物理/模型/HITL/实飞。失败保留：本次metadata缺失、bootstrap缺模块、初版fake缺ABI字段、setup-read/post-send-clock反例及所有历史失败。

## 事前设计与测试

规格/计划7c23ac0先提交。复用固定Linux NEW RX生成/报告接口及已封存ABI/probe，没有重编或重跑探针。依据为[官方timestamping API](https://docs.kernel.org/networking/timestamping.html)与固定v6.6 socket.c/sock.c/net_tstamp.h/errqueue.h。Kernel GPL2家族/UAPI syscall exception、Python3.12 PSF；官方文档当前可访问，固定版本支持状态/安装补丁等价不明。旧NS失败保持，硬件时钟另需设备/标定研究。成本是小型UDP/stdio，不装依赖、不改物理负载；协议资料不冒称VIO标定论文或飞行证据。

新独立入口仅复用旧read_static/duplicate-JSON/FD/close工具，旧NS入口不改。固定schema/runid、3包、40ms延迟、20ms诊断门槛、GNU timeout20s/kill-after2、exclusive127.0.0.1:14548/14588与精确capability哈希，未知/替换/漂移启动前拒绝。没有SO_REUSE或MAVLink/ODOMETRY、参数/解锁/仿真/模型/训练。

自查ABI再读在try外会丢result，1 failed/14 passed行为RED后修复。复核发现sendto返回后时钟异常会丢实际发送，1 failed/15 passed RED后修复：先记录attempt/count，再逐字段填after时间，失败None不补造。另补duplicate/unknown/missing inventory/capability、有效payload/queue/drift反例。green-v1的fake缺ABI导致正常案例失败，保留并修正fake，不称原生/产品失败。最终23入口针对性、199相关回归passed/1既有Windows symlink权限skip，changed Ruff/diff与源码预后hash通过；独立代码/实际证据复核无遗留。不称整库全测/全库lint。

## 唯一实际试验

Profile SHA256 e3c1f7587c65f092141324ce8d9b10801fe8a3af709a9a692da7d2162072621d。16份源/能力/测试/设计先复制并核hash，子进程执行冻结输入entry、Python-I/-B、全新cache-prefix、精简env；9模块origin均来自该副本，源/复制/profile前后相同，cache未创建。不声称完整Python/OS闭包或hostile-ABA防护。

Ubuntu首次/唯一执行：timeout leader7302/session7302/start_ticks1621964，Python worker7303。启用及选项/身份check未拒绝；这是代码与路径核对，不是逐syscall返回值trace。真实3×55byte send_returned=true；delay40.200692ms；首payload/peer/flags/空ancillary保留。recvmsg返回1，accepted packets0，不能把received列表空说成没收到数据；未消费2包的metadata未知。程序0.286415s、调度/监督等待2.881378s，都不是果蝇/VIO延迟或容量结果。

FD3/4均fileno=-1、EBADF9、无close错误。workerexit1/失败保留；既有GroupEvidence/finish_owned_worker以WNOWAIT保留leader，7条磁盘journal与内存逐条相同；原组只有zombie，reap后无成员/执行者，无group信号/noSIGKILL、graceful cleanup合格。只限原owned组，escaped descendants/无关进程全局释放仍false，未终止无关进程。audit.py只读验证字节、counts、origin、hash、FD/exit/组身份/journal，未重跑socket。

## 后续与阻碍

失败后阅读[固定v6.6 dev.c](https://github.com/torvalds/linux/blob/v6.6/net/core/dev.c)：首次net_enable_timestamp在CONFIG_JUMP_LABEL下可走netstamp_work延后静态key更新。只读安装/proc/config.gz观察CONFIG_JUMP_LABEL=y，SHA04a93986b749766e5f1e912e1a80eb9b84985f54c052695c64970230a8c2a9e3；[loopback.c](https://github.com/torvalds/linux/blob/v6.6/drivers/net/loopback.c)清除原skb时间后进入另行生成的接收栈。这支持冷启动/实际回环路径的新假设，未证明安装内核运行时因果，不能推断steady-state均失败。

下一依赖须独立声明只读/观察性生成启动诊断，完整保留cold/later新包和缺失，不复跑旧profile、不sleep预热后改称通过、不丢首包、不放宽runtime门禁。诊断不解开latched receiver、不授予控制/训练；真正源生成/到达/clock/health/private发布仍需闭环。本入口未接入旧live wire，不能用此次缺metadata解释旧两秒TIMESYNC失败。

Docker API恢复且无运行容器，宿主2294→1609MiB，仍低于EGO2500和完整模型/firmware/物理各4GiB，未启动这些工作。五机0.873RTF<0.95、首两秒TIMESYNC、full masked MaleCNS未训练/EGO teacher false保持；不要求安装原生Linux。完整学习/分工/公平比较/单机→5→20目标仍在，不宣称整体完成。
