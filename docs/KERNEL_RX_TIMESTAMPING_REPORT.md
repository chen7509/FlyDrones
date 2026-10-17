# RX 软件生成时间戳：实现与能力验证

## 当前结论

新增独立 KernelRXTimestamping 配置，用 SO_TIMESTAMPING_NEW 的 RX_SOFTWARE|SOFTWARE 生成/报告语义；拒绝与四个旧 SO_TIMESTAMP/NS 选项混用。它已通过纯软件解析、选项/故障门禁与安装头文件能力验证，**没有进行真实收包或排队试验，没有证明真实 PX4 到达/生成时间**。上一阶段 opaque-loopback-v1 失败继续保留，不重跑、不改判。

该工作是可信 PX4 来源与积压拒绝契约的依赖。完整果蝇学习/分工、开源规划器源真实性/公平对照、物理安全闭环和单机→5→20目标仍未完成，不以协议软件取代它们。

## 设计与上游选择

规格/计划在8cab9ad先提交。使用 [Linux 官方 timestamping API](https://docs.kernel.org/networking/timestamping.html)、固定v6.6 [net_tstamp.h](https://github.com/torvalds/linux/blob/v6.6/include/uapi/linux/net_tstamp.h)、[errqueue.h](https://github.com/torvalds/linux/blob/v6.6/include/uapi/linux/errqueue.h)、[socket.c](https://github.com/torvalds/linux/blob/v6.6/net/socket.c)和[sock.c](https://github.com/torvalds/linux/blob/v6.6/net/core/sock.c)。生成与报告标志独立；文档明确提示旧SO_TIMESTAMP/NS兼用时可出现读取阶段生成的替代软件时间。新profile排除这些旧选项，不把源码解释冒称安装内核的运行时因果证明。

选择现有Python3.12 recvmsg与Linux UAPI，避免新守护进程或手工仿造包时间；Kernel为GPL2家族、UAPI有Linux-syscall-note，Python为PSF。官方文档当前可访问，但固定v6.6支持状态/维护节奏和WSL补丁等价未建立。适配成本为小型头文件探针、48字节解码和额外选项检查，没有依赖安装或物理负载改变。旧NS方案因真实队列试验失败拒绝用于到达证明；硬件方案需要NIC与时钟研究，暂不采用。协议资料不是VIO/相机标定论文或飞行证据。

复用基类的有界ABI/hash、单次未绑定启用、FD/对象身份、实时时钟高水位、失败锁和原始元数据描述，仅抽取ABI表、option hooks和时间值验证；NS默认逻辑与旧探针保持。接收器仅允许两个内部**exact type**，不能用caller subclass替换decoder。原userspace monotonic received_ns不变，内核CLOCK_REALTIME独立记录、不映射时钟。

新profile启用前/后和每次check检查旧29/63/35/64均literal int0，不清除调用方旧设置；NEW65必须exact flags24。只接受一个level1/type65/48字节记录；ts[0]有效、ts[1]/ts[2]全零，零/缺失/旧cmsg/截断/重复/错误类型/非软件值/未来/倒退拒绝。异常锁存、真实返回后的原始payload和48字节cmsg仍保留。全部receive-instant/source/clock/fusion/training资格false；未启用到CaptureWireOwner、物理配置、MAVLink控制或私有发布路径。

## 唯一头文件编译及后置包装失败

实际Ubuntu内GCC只读编译新kernel_rx_timestamping_abi.c一次，单job、每命令10秒界限；compiler/as/ld/cc1、预先头文件依赖、MD实际depfile、源码/二进制/输出保存。compile及probe执行均exit0。真实结果：NEW65、cmsg65、RX8/report16、旧选项29/63/35/64、scm_timestamping64共48字节、元素16字节/偏移0/16/32、CMSG_SPACE64、MSG flags64/32/8。

复用的研究driver仍检查旧timestampns schema，编译和probe正常后抛ABI output invalid；这个包装失败与原driver全部保留。另一个finish-capability.py没有重编译或重跑probe，仅核对已有输出和更长时间区间的原预先input hash/身份，运行ldd并另存completion。这里的post在包装失败后采集，不回填为原driver正常完成；能力记录无socket/估计器/物理。

ABI SHA256：6e466d6b0b5d43a5086e1bb509c9932d715c7aba6ebc32ba665d90aa81f72366。
Probe SHA256：2833ebd4ba6a51df6d5db76f59dee3b44247f2c621e2403eb237775feff5aa01。
前置与延后核对全部输入一致，runtime_closure_qualified=false；WSL6.6.87.2不冒称纯上游v6.6。

## 分类与测试

**已验证：**新软件门禁/解析、原始证据保留、旧NS/receiver邻近回归、真实头文件编译/探针输出身份。**仅实现：**可选生成RX profile与exact receiver入口。**未测试：**真实getsockopt/recvmsg行为、队列时间保留、PX4来源、时钟映射、物理/训练/硬件。**失败：**bootstrap缺模块、尚未实现hook时18 failed/6 passed的行为RED、头文件driver错误schema的后置拒绝；历史NS试验和其它历史失败不覆盖。

最初测试缺模块为API RED；具备ABI表的最小继承入口仍执行NS option lookup，18例实际失败，不冒称这些是已飞行或假接受。完成option hooks/三时间结构后变GREEN。独立复核没有Critical/Important；指出RX独有故障覆盖不足的Minor后，新增missing/duplicate/old cmsg/长度/flags、False/0.0旧选项、原生get/set异常与启用中冲突等持久测试。复核又指出零时间测试载荷会掩盖独立拒绝分支，已改成有效triple只变被测字段。新增覆盖是GREEN确认，不冒称修复过不存在的行为错误。最终39个RX针对性、176个相关回归passed/1既有Windows symlink权限skip，changed Ruff/diff及源码前后身份检查通过；独立复核无遗留Critical/Important/Minor。不声称整库全测或全库lint。

## 下一依赖与资源

Task3真实收包研究尚未执行。下一步独立冻结新的ABI/code/源副本、固定owned端点/3opaque包/40ms延迟/20ms诊断阈值/timeout20s/kill-after2/关闭和失效保留，再复核、单次试验；无sleep预热、任意重试、旧profile改名过关。成功解析或编译不授权ODOMETRY/EKF2/解锁/训练，真实源生成/到达、时钟/重置/健康、私有发布仍需独立契约。

当前宿主约2140MiB、Docker Linux engine不可连接，未启动EGO/物理/训练。EGO2500MiB、firmware/物理/完整MaleCNS的Windows/WSL各4GiB门槛不变；五机0.873RTF<0.95与首两秒TIMESYNC失败保留，不要求安装原生Linux。总路线图从curriculum-training既有文档只读复核，其早期真值替身与100机运动学不能冒称真实VIO/100机物理。
