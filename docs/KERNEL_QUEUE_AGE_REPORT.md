# 生成型 RX 的队列年龄拒绝（2026-10-12）

旧接收器检查 `recvmsg` 耗时和解码时刻，但不能拒绝“刚解码、实际已积压”的包。本阶段增加可选的整数时钟区间与队列年龄拒绝路径，保持原 **2秒** 门槛；没有启动新 socket、PX4/Gazebo、模型或训练。它只增加软件拒绝条件，**没有获得连续时钟关系、真实源或控制资格**。

## 实现与依据

精确 `KernelRXTimestamping` 在原 prepare 成功后、bind之前创建 `KernelQueueAge`。读取 monotonic→realtime→monotonic，条件偏移 `O=R-M` 位于 `[R-M_after,R-M_before]`，逐次求交。无重叠、回退、跨度≥2秒、溢出、异常类型或容量耗尽锁存拒绝。NS时间戳可能有读时回填，因此不允许取得此语义。offset使用整数区间而非中点，不能借解码时间补造源时间。

生成型时间戳 `K` 在模型中的 monotonic 区间为 `[K-O_hi,K-O_lo]`。拒绝会话前数据、可能未来的数据或年龄上界≥2秒。相机/PX4状态的100ms与此处主机包队列年龄是不同门槛；包进入内核不等于状态产生。

接收器额外检查准确对应其 kernel对象、clock callable、start和单个receiver；clock callback之后再次验证 prepared FD／选项／unbound，不能事后给已绑定socket补时间依据。内核原始返回数据仍在时钟／日志回调前保存，EAGAIN也保留采样检查。旧默认和NS不会导入新模块；opt-in没有启用到现有 livewire profile。

日志前和返回前分别检查年龄。发送前 `check(packet)` 在此模式要求确切的最新发放对象；未指定、旧、复制或别的receiver对象拒绝，新的包不能给旧缓存续期。默认模式保留无参数检查。最后判断直接验证已观察时间的highwater、绝对deadline和restoration上下文，不再调用任意时钟回调。两个组件共享观察highwater；年龄model失败不通过重置或恢复读包来消除。

单writer互斥与纯状态锁分开，外部clock调用不占状态锁；竞争者能立即锁存失败，活跃采样在返回前再查失败。证据是独立副本；最多32768 anchors/8192 assessments，没有新增后台任务。元数据和日志前年龄放在已有事件中，保留8192事件预算；最终返回前／send前结果在返回对象与exported evidence中，**不能回填已经写出的journal或声称fsync事务**。

观察区间只能检验“采样点与常量偏移模型一致”，无法排除采样之间未观察到的跳变再恢复，也不能认证进程或证明硬件时钟。全部 clock_mapping/source/network/fusion/training 字段为false。调用成功不是认证／新鲜度授权，不能直接据此发布ODOMETRY、解锁或训练；实际控制还缺完整源／clock／健康／reset／相机证据链。

## 测试与复核

初始缺模块属于API bootstrap。数学实现之后、receiver接入之前保存 **10 failed/14 passed**，包含陈旧首包、递增积压、日志延迟、offset跳变、会话前时间、缺绑定/重入以及尚未存在字段；不是10个物理故障。随后packet-specific功能记录4失败，其中2是API形状，2为真实漏拒绝／漏锁存行为。

独立复核先发现3 Important：最终回调已锁存receiver失败仍返回packet；初始clock回调绑定socket后anchor仍接受；状态锁跨clock回调使竞争者无法及时拒绝。对应4个真实RED后修复。再发现最终assessment跨绝对8秒deadline，2个RED后修复；自查共享clockhighwater遗漏也有1个RED。所有输出保留，未以测试数量代替复核结论。

最终 **42项针对性** 与 **188 passed/3 skipped** Windows邻近回归通过。实际覆盖原receiver、RX/NS、原观察entry和segmented receiver；3 skip是缺真实pymavlink而整组跳过的 `test_openvins_timesync_wire.py`、`test_openvins_wire_maintenance.py`、`test_openvins_observed_restoration.py`，不能称Windows验证了这三组。changed Ruff/diff为0，4份源/测试前后SHA一致。没有重跑全库／全库lint。独立代码复核最终无遗留Critical/Important/Minor，另报告148项fake通过；复核结果保存在工具消息记录／review.json，不是其原始机器stdout。主188项运行原始输出已保存。

这3组随后在WSL Python3.12.3／固定pymavlink2.4.49补验，**75项通过**，原始stdout/stderr、准确命令、6份源前后SHA保存在 `wsl-final-v1`；代码未变化。真实codec与fixture传输并不意味着真实socket、PX4、physical或新年龄profile实测，未执行任何网络／仿真进程。不能把两个平台的数量相加后称为完整套件或实飞通过。

## 保存的8包区间审计

只读消费原 `evidence/rx-startup-observer-dev-1701.zip`，SHA `0674634cc28b935db9c4c86169502aab6f715217552824b825087e43ba3d00cd`；单次读ZIP并核对3个消费成员的manifest／长度／SHA。生产源码 `3a99e94b…` 的求值顺序提供两组宽区间：`attempt_m→attempt_R→send_start_m` 和 `recv_start_m→recv_start_R→recv_return_m`。只用当时已发生的区间，未用后续包来调整之前结果；8条均保留。

8条在该条件模型下可计算，年龄上界 **21.233051–22.063214ms**；与原始20.5–21.1ms的realtime差不是同一指标，区间包含journal／处理不确定性。这不是新的实时sampler、历史before-bind证明或校准，不能把这8条升格为实时clock资格。原failed burst与其他ZIP没有改动；本阶段没有重放网络。

## 当前边界与后续

| 分类 | 结论 |
|---|---|
| 已验证 | 假连接与有界线程下的模型／绑定／生命周期拒绝、邻近回归、原8包字节绑定与条件区间计算 |
| 仅实现 | opt-in receiver年龄策略与packet-specific最终检查；未在livewire/capture激活 |
| 未测试/不合格 | 真正before-bind sampler、连续时钟关系、actual receiver收包、PX4源/sample/reset/健康、标定相机、EKF2闭环/硬件/飞行 |
| 保留失败 | 本轮全部RED及原RX/NS/TIMESYNC2秒、五机0.873RTF<0.95、物理历史失败 |

Linux读取的时钟实现名为CLOCK_MONOTONIC/CLOCK_REALTIME、报告resolution1ns；不等于1ns精度或固定offset证明。官方来源是Python3.12文档、固定CPython3.12.3（PSF）和Linuxv6.6timekeeping（GPL2族）；安装补丁等价／维护支持未新证明。适配代价为有界整数和几次clock读取，没有新依赖或仿真负载。

完整masked MaleCNS仍未训练，EGOteacher仍false，物理/fullMaleCNS各4GiB与EGO2500MiB门槛不降低。本轮宿主有短时约2647MiB快照、随后降至约2295MiB，最后实际Get-Counter为1731MiB；单次较高读数不能作为之后构建／物理启动资格。没有启动构建，也没有因平台条件把果蝇策略判失败。后续优先在新资源检查合格时执行已经冻结的EGO完整构建与原版/补丁数值核对，并把clock策略与真正源／sample/status/reset和相机生产端设计绑定。旧frozen输入继续用旧字节，不能偷偷替换新模块后仍称同一版本；新的opt-in必须另行声明依赖与packet-specific消费者。完整目标和单机→5→20仍未完成，不要求安装原生Linux。

证据 `evidence/kernel-queue-age-dev-1701.zip` 与同名SHA sidecar保存源码/规格/计划/原失败/最终运行/研究/区间审计/复核，成员SHA/CRC验证后发布；不覆盖既有工件。

[Python time API](https://docs.python.org/3.12/library/time.html)、[Linux clock_gettime](https://man7.org/linux/man-pages/man2/clock_gettime.2.html)、[固定CPython](https://github.com/python/cpython/blob/v3.12.3/Python/pytime.c)、[固定Linux timekeeping](https://github.com/torvalds/linux/blob/v6.6/kernel/time/timekeeping.c)支持时钟与采样选择；没有把无关估计器论文当作协议／硬件校准证据。
