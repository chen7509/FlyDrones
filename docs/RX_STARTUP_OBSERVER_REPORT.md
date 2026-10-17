# RX 首包与后续包原始观测（2026-10-12）

独立观测 `opaque-rx-startup-observer-v1` 完整取得8个新包，**包括首包在内，8个包都有 NEW65 生成型软件时间戳，且均早于读取开始**。这是一个新条件下的局部接口观测，不能把此前首包无 ancillary 的失败改为通过，也不能据此认定延迟启用就是旧失败根因。生产接收器／失败锁未改动，本阶段没有取得 PX4、源时间、融合、训练或飞行资格。

## 为何进行与事前边界

上一试验将3个55字节包立即发出，首包没有元数据后停止，另外2个未读取。本次事前独立规格／计划选择8个53字节非 MAVLink 包、每次间隔至少50ms、发送返回观察后至少20ms再读取、单包轮询200ms、内部5s、外部20s+2s kill及25s owned supervisor。使用临时 loopback 端口和单次 nonce，不占 PX4 端口，不预热／丢首包，不重建／重跑已固定 ABI probe，没有修改内核参数或传感器负载。

固定 Linux v6.6 `dev.c` 提供 CONFIG_JUMP_LABEL 下 deferred netstamp_work 的源码依据，loopback 走自身清除与重新生成路径；这些只是候选解释。安装内核为6.6.87.2-microsoft-standard-WSL2，等价和运行时因果未证明。只读 `/proc/sys/net/core/netdev_tstamp_prequeue` 返回1；两个 tracefs 能力路径权限拒绝，未提权、安装或启用 tracing。全局先前时间戳使用者和静态开关状态未知，因此本研究是新 socket 的启动观察，不能称为冷内核启动试验。先前研究阶段的路径猜测、PowerShell展开错误与权限异常均记录，不能把权限拒绝解释为接口不存在。

## 实际输入与结果

代码／规格／计划在运行前提交 `2193e02`。调度器冻结16项输入，实际10份 Python 模块来自独立副本；Python `-I/-B`、新的未创建 cache prefix、最小环境、GNU timeout 与原 owned-group 监督器均记录。源码／副本／profile预后哈希一致。profile SHA256：`7de611ef565bee2cb0872322499fdfc2f3ef1f7eca620eae4c48da0a24132e23`。

| 单次实测项目 | 结果 |
|---|---|
| 原始包／逐阶段 journal | 8包／32条，顺序与 payload／peer 精确核对 |
| ancillary | 每包1条 SOL_SOCKET1/type65/48字节；ts0非零，ts1/ts2全零 |
| 新包实际最小发送间隔观察 | 50.745728ms |
| 发送返回观察→读前观察最小间隔 | 20.082146ms |
| 读前 realtime − 原始 ts0 | 20.503666–21.136234ms，8条分别保留 |
| 首次 attempt→末次 recv-return 观察 | 382.081680ms；不是果蝇／VIO推理耗时 |
| dispatcher 包含启动／监督／收尾 | 2.188692014s；不是采样吞吐或算法延迟 |
| owned FD | fd5、fd4均fileno=-1且fstat=EBADF |
| 原 owned process group | owner7546/pgrp7546/session7546/start_ticks2412479；退出0、WNOWAIT后reap、组空／无执行成员 |

磁盘 supervisor journal 与内存 events 一致，监督器没有发组信号／SIGKILL；只证明原 owned group 的检查，不证明 setsid 逃逸后代、全部 OS 资源或源码闭包。没有启动 PX4/Gazebo/OpenVINS、Docker容器、模型、EGO构建或训练。

观察器没有调用 `DatagramReceiver` 或生产 parser；其 `production_would_refuse_at=null` 只表示本次元数据／顺序筛选未找到拒绝位置，**不是生产路径成功证据**。另外一次只读虚拟时钟投影把保存的8条原始 ancillary 交给 unchanged `KernelRXTimestamping.parse()`，所得数值一致；parser没有绑定 socket、没有新包、没有恢复旧失败接收器。最初 `parser-parity-v1` 的两次读取只形成事后哈希，保留；`v2` 改为一次读取、用原结果固定SHA核验并解析同一字节，没有重跑网络。

计时解释：attempt记录先写 journal；send-start时钟在 flush及guard后观察。send/recv return 时钟在 syscall-success journal后读取，包含 journal 耗时，是观察上界而非 syscall 瞬时。读取前后 realtime 和 monotonic 不是已经校准的域转换；没有补造回调时间、映射 PX4 boot time 或证明源数据生成时间。

## 软件验证与复核

初始模块缺失是API bootstrap RED，不声称行为反例。后续真实反例保留：setup失败遗漏 false 字段（1RED）；晚 recv return 被接受（1RED）；日志延迟扭曲实际发包间隔、过内部期限仍发送，以及 setup evidence 丢失（3RED）；最后 journal 超时仍宣称 observed（1RED）。修复后43项针对性通过，其中 cleanup、journal close、声明与能力 SHA、缺失元数据、异常值／时钟／identity／I/O／超时全覆盖。新增双 FD close/close error覆盖直接GREEN，未称新的RED。

最终邻近软件回归 **167 passed**，包括43新例与现有 RX/NS、旧 frozen study、owned-group 测试；changed Ruff/diff成功，5份源码／测试预后SHA一致。没有重跑整库／全库lint。独立代码复核的1Important计时问题和1Minor setup记录问题已修复，最终无遗留 Critical/Important/Minor。实际观察使用该最终 producer，后续仅只读审计，没有重跑 socket。

## 已验证、仅实现与未完成

| 分类 | 边界 |
|---|---|
| 已验证 | 该次8包原始字节／前读时间戳、固定输入与源预后、局部 FD／原组清理、假连接测试与独立复核 |
| 仅实现 | 不控制的诊断 entry和stateless ancillary观察；不改变生产失败锁 |
| 未测试／未资格化 | 冷内核、真实 PX4 源／源年龄／时钟同步、mono-realtime区间、递增积压拒绝、设备／远端／掉包场景、真实生产 receiver、EKF2／相机／融合／LAND ACK／硬件飞行 |
| 保留失败 | 原 NS／generatedRX 首包失败、TIMESYNC首2s失败、五机0.873RTF<0.95、历史物理与全部本轮失败 |

所有 arrival/clock/source/fusion/training 字段保持false。Docker已可用但物理与完整 MaleCNS仍需Windows/WSL各4GiB、EGO构建2500MiB；本轮宿主约1.65–2.06GiB，没有降低门槛，也未终止无关 ADS／sandbox／defunct 进程。完整 masked 参数仍未训练，EGO teacher=false；既有单机仿真域 VIO 结果不等于 PX4 安全飞行或多机资格。

下一依赖应转回可控制证据链：先建立保持2s门槛的 realtime/monotonic 区间与队列年龄拒绝契约，再把它绑定现有接收器和 PX4 源样本／状态／reset／校准相机生产端。未知映射不能授予新鲜度，也不能把包到达当状态生成。不要再次盲跑这8包或无限扩张内核诊断；资源允许后才能执行已冻结源码构建与未解锁物理验证。完整学习、分工、公平上游基线与单机→5→20证据仍为总目标，不要求安装原生 Linux。

原始观测、固定输入、研究源、测试/失败、版本、报告和复核分别封存于 `evidence/rx-startup-observer-dev-1701.zip`，SHA256见同名sidecar；每成员SHA／长度及ZIP CRC验证。先前ZIP不修改。

官方依据：[Linux v6.6 timestamping API](https://www.kernel.org/doc/html/v6.6/networking/timestamping.html)、[固定 dev.c](https://github.com/torvalds/linux/blob/v6.6/net/core/dev.c)、[固定 loopback.c](https://github.com/torvalds/linux/blob/v6.6/drivers/net/loopback.c)。Linux GPL2族/UAPI例外与PythonPSF沿用；固定版本维护支持／安装等价未新证明。没有新增依赖／编译／估计器；协议源码与无关算法论文都不能证明传感器标定或飞行安全。
