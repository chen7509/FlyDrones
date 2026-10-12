# 内核数据报时间戳：软件实现与失败的排队时间试验

## 结论与目标边界

本阶段没有解决真实 PX4 遥测积压/源时间证明。新增可选的 Linux `SO_TIMESTAMPNS_NEW` 元数据读取，保持既有默认路径、单调时钟期限和来源/融合权限不变。一次真实 WSL 试验得到合法的附带数据，但时间戳落在延迟读取的 `recvmsg` 前后观察之间；不能称为原始到达时刻，不能据此批准控制、训练或公平基线。

| 分类 | 结果 |
|---|---|
| 已验证（软件） | ABI/hash/schema、未绑定 socket 的一次启用确认、身份/选项复核、原始字节与 ancillary 保留、截断/错误时间/失败锁等拒绝；137 个针对性及邻近测试通过，1 个既有 Windows symlink 权限跳过；改动 Ruff/diff 检查通过 |
| 已验证（小型原生能力） | 安装头文件只读 C 探针正常编译，真实 option=64/cmsg=64/16 字节时间结构/32 字节 ancillary 空间；owned UDP 发出 3 个不透明数据报，读回第 1 个的准确 payload 和元数据；两 FD 关闭且 fstat 返回 EBADF，子进程退出 1 |
| 仅实现 | 可选 NEW 元数据 profile、独立 CLOCK_REALTIME 记录、严格声明与源哈希前后检查；未接入 CaptureWireOwner/冻结物理配置/旧 MAVLink 门禁 |
| 未测试 | 原生 option-drift 第二例（第一例失败，未执行）；真实 PX4 收包、源时钟映射、EKF2 健康/重置/标定相机生产端、物理/硬件/训练；完整运行依赖闭包未知 |
| 失败 | opaque-loopback-v1 排队时间证明；失败/未消费数据报记录保留，不改门槛、不重跑 |

整体目标未完成。五机 0.873 RTF < 0.95、首次两秒 TIMESYNC 失败和历史物理失败保持原结论。

## 上游依据与选型

复用 Python 3.12 [recvmsg](https://docs.python.org/3.12/library/socket.html#socket.socket.recvmsg) 和 [Linux timestamping API](https://docs.kernel.org/networking/timestamping.html)。固定 Linux v6.6 [接收路径](https://github.com/torvalds/linux/blob/v6.6/net/socket.c)、[socket 选项](https://github.com/torvalds/linux/blob/v6.6/net/core/sock.c)、[UAPI](https://github.com/torvalds/linux/blob/v6.6/include/uapi/asm-generic/socket.h)说明 NEW 布局；接收路径存在无原有 skb 时间戳时生成当前时间的分支。Python 为 PSF 许可；内核 GPL-2.0 家族、UAPI 含 syscall exception。不声称安装内核补丁等价于纯 v6.6，不以 API 可用等同路径通过。没有新装依赖、硬件授时或论文校准证据；成本是小型头文件探针和额外元数据记录。Man7 请求失败，未作为依据。

安装 Python 3.12.3 未暴露所需 SO/SCM 常量，没有猜 ABI。安装 kernel 为 6.6.87.2-microsoft-standard-WSL2。能力探针源码、编译器/as/ld/cc1、头文件列表、真实 depfile、输出及前后哈希保留。ABI SHA256：b6e931bc6bfcd8615f27ecbbce67570a0e3f6a2262fc8c28424a8446b813d8eb；二进制：30fafb5a8a6236d0c87f72818e44d502049d979f8105d0ac2f1ab2331ecd9281。

只接受已观测 x86_64/little-endian NEW 结构，拒绝未知布局。先在未绑定 socket 启用并确认，再绑定发送。received_ns 保持 userspace monotonic 含义；内核系统实时时间独立记录，不转换为单调时钟或样本生成时间。所有 source/network/fusion/training 权限 false。最终额外显式标记 kernel_receive_instant_qualified=false：成功解码不能证明原始入队时刻。

## 唯一真实试验与保留失败

独立规格/计划在实现前记录。复核后冻结 study-v1/study-profile.json，SHA256 39658b82171a57a2ae1e51195cae201c71fef36b84003a2bfb06c8af0fdff833，副本与前后哈希一致。声明固定 127.0.0.1:14548/14588、3 个带随机 nonce 的不透明 ASCII 数据报、40ms 延迟、20ms 最低排队诊断门槛、GNU timeout 20s/kill-after 2s。不是 MAVLink，没有 PX4/ROS/Gazebo/传感器/训练或向他人发送消息。

首次 WSL 调度用了不存在的 Ubuntu-24.04 名称，分发前退出，launcher-prestudy-failure.json 保留。列出实际 Ubuntu 后纠正目标；此前 dispatcher/study 目录/socket 都未创建。实际 socket 试验仅一次。

capture-v1/result.json 为 failed：送出 3 个/读回 1 个/关闭前未消费 2 个。首数据报 59 字节；ancillary level=1/type=64/length=16、flags=0，原始 payload/peer/元数据保留。实际延迟 40.113192ms；时间戳比发送后观察晚 40.340515ms，却仅比 recvmsg 前观察晚 22.234µs、比返回后观察早 30.646µs，不能证明排队历史。接收路径合成当前时间是源码支持的候选解释，**未以运行时内核插桩证明因果**，不直接归咎于 WSL 或果蝇。

第一例因 kernel timestamp outside owned send/read observations 拒绝；第二例未执行，不能称原生 option-drift 通过。试验 0.110712s，调度等待约 1.056805s，都不是决策/VIO 性能。owned FD 3/4 关闭、fileno=-1、EBADF=9，timeout 子进程 exit=1；只证明这些描述符/子进程，不说全部无关进程组空。最终诊断字段和注释是试验后软件加固，仅测试、未重复 socket；冻结 producer 副本不回填。

## 测试、复核与剩余工作

bootstrap 缺模块是 API RED；接收集成 4 个行为反例、bool 端口/原时钟误借用、latched 时钟调用来源等有 RED/GREEN。复核两项 Important（passed 先于 post 哈希检查、意外错误丢第二例证据）、一项 Minor（close 失败观察丢失）、后续 constructor 拒绝丢初始事件 Important 已修复并确认无遗留。失败也做 post 检查，逐例保留事件/profile，清理和 post 合格后才写 passed。早期 fake 时间输入不符的 RED 保留，harness-red-v2 才确认进入第二接收器；不冒称原生结果。

只读 audit-study.py 核对实际 producer 哈希/副本、字节/解码/时序、未运行第二例、FD/退出和权限 false。audit-v1 生成后计划复选框更新，复核发现其 final_changes 列表过时；另存 audit-v2 加入计划文档变动，原 v1 保留，不重跑 producer。最终 137 passed/1 skipped 是局部回归，不称整库全测或全库 lint 通过。

下一步研究 [SO_TIMESTAMPING_RX_SOFTWARE](https://docs.kernel.org/networking/timestamping.html) 的生成/报告分离与固定源码，确认能否拒绝无生成时间的包、避免 SO_TIMESTAMP/NS 兼用的合成时间及延迟启用语义。此新候选尚未实现/编译/运行，必须独立规格/计划/冻结，不能直接重试本配置。仍需 TIMESYNC/源样本时刻、积压/重置/健康及私有发布路径契约；元数据不可放宽安全门禁。

宿主曾约 3148MiB，后约 1964MiB，未稳定达到 4GiB 物理/完整 MaleCNS 门槛。Docker Linux engine 管道不可用，未启动 EGO 构建。WSL 无关 Codex sandbox/forwarder/zombie 未被终止；进程名或 idle 不证明资源释放。证据 ZIP 的 SHA/成员/CRC 见封存记录；所有既有失败不覆盖。
