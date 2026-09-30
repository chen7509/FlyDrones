# 五机视觉流偶发墙钟停顿：边界定位（2026-09-26）

## 已观察到的事实

在相同策略、世界和无故障配置下，五机视觉流偶尔在墙钟时间停止约 0.25–0.29 s，随后继续以约 20 ms/帧运行。250 ms 自主层门控在一次失败基线中拦住了四机；另两次基线完成 5/5，但仍有接近阈值的停顿。因此当前结果说明门控会对真实的输入空窗作出反应，尚未说明五机系统具有稳定的任务完成率。

| 原始轮次 | 2 号机最大原始回调间隔（墙钟） | 同一间隔内源仿真时间 | 回调后转发延迟 | 任务 |
|---|---:|---:|---:|---:|
| `fleet-vio-gate-frozen-baseline` | 286.3 ms | 20 ms | 下一帧 0.70 ms | 1/5；四机门控，转发退出异常 |
| `fleet-vio-gate-frozen-baseline-v2` | 244.9 ms | 20 ms | 下一帧 2.19 ms | 5/5；转发正常退出 |
| `fleet-vio-gate-baseline-pause-probe-1` | 254.8 ms | 20 ms | 下一帧 1.04 ms | 5/5；无门控，转发正常退出 |
| `fleet-vio-gate-baseline-pause-probe-2` | 232.9 ms | 20 ms | 正常 | 4/5；3 号机任务超时，无视觉门控 |
| `fleet-vio-gate-process-probe-1` | 224.5 ms | 20 ms | 正常 | 5/5；无门控，仍有时钟停顿 |
| `fleet-vio-gate-thread-probe-1` | 232.0 ms | 20 ms | 正常 | 4/5；无门控，仍有时钟停顿 |

第三轮使用控制器提交 `0e9decf`（与第二轮的飞行控制和转发代码一致），策略 SHA-256 `3c723587bfdbd15a8dc5976edc13d284b713dc081005b2dac04692c7d1b4accb`，世界 SHA-256 `da3e81c10a7d848671c1045f9da267eca65fd312793231dd99a038f55824e8ad`，仿真平均速度为 0.8671 倍墙钟。逐机任务、落地、转发收尾和 PX4 文件恢复均通过。

第三轮的独立 WSL 调度探针每约 50 ms 采样一次。在 2 号机 254.8 ms 原始回调空窗内，探针仍记录了 5 次样本；整轮探针最大采样间隔为 95.3 ms。该空窗内 CPU 压力累计只增加约 3.8 ms，内存压力没有增加，可用内存至少约 6 GB。空窗前后 2 号机原始回调的仿真源时间戳只相差 20 ms，回调后下一条转发消息约 1.04 ms 发出，随后没有积压帧突发。这排除了“整个 WSL 实例同时暂停约 255 ms”和“转发器发送队列积压约 255 ms”这两种简单解释；停顿位于 Gazebo 里程计产生、Gazebo transport 到 Python 回调，或该回调的进程调度之间。现有证据**不能**再细分，也不能断言 Gazebo 物理仿真本身暂停。

门控以墙钟数据新鲜度判断。即使仿真时间几乎没前进，只要实际飞行中观测断流，就应该停止依赖旧位姿；因此不应单凭这些结果把 250 ms 阈值放宽。第三轮 254.8 ms 空窗没有触发门控，仅表示控制循环检查时可能已经收到新帧，不说明该空窗已被修复。

第四轮加了独立的 Gazebo `/clock` 订阅器。1、2 号机约 233 ms 原始里程计空窗内，时钟订阅器仍收到两条消息，但相邻回调的墙钟间隔约 105 和 99 ms，各自只推进 4 ms 仿真时间；0 号机启动期的 684 ms 里程计空窗也与约 668 ms 时钟回调间隔重合。与此同时，独立 WSL 探针整轮最大采样间隔仅 82.1 ms，前述约 233 ms 空窗内记录了 5 个样本，CPU 压力累计只增加约 1.2 ms。这进一步表明 Gazebo 仿真时钟/发布链路出现严重慢速，而非 WSL 整体暂停或转发器发布队列堆积。现有 `/clock` 探针仅记录大于 50 ms 的间隔和每 500 条采样，尚不能区分 Gazebo 物理步、模型里程计插件与 transport 发布内部各自的开销。

随后做了一轮**仅用于定位、不可与正式任务结果合并**的单变量消融：保持控制代码、策略、世界和相机 10 Hz 更新率不变，把深度画面从 160×120 临时降为 80×60。原相机文件在轮次后按 SHA-256 校验恢复。该轮只有 3/5 完成任务，所有机体最终落地、无视觉门控；1、3 号机原始里程计仍分别出现 294.9 和 295.6 ms 的墙钟空窗，独立时钟回调最大非启动间隔约 160 ms，平均仿真速度为 0.8854 倍墙钟。这一负结果不支持“仅降低深度图像像素数即可消除停顿”。单轮消融也不能排除相机渲染在其他配置下的贡献。

恢复原相机后又做了进程级探针轮次。该轮 5/5 完成，但 0 号机启动期有约 695 ms 原始里程计空窗；独立 `/clock` 回调对应约 680 ms 墙钟间隔、仅 4 ms 仿真推进。Gazebo `gz sim` 进程在这段间隔内累计消耗约 690 ms 用户态加内核态 CPU；后续多个约 150–170 ms 的时钟间隔也各自消耗约 110–150 ms CPU。进程主线程采样状态有时显示 sleeping，但进程总 CPU 仍增加，说明至少有其他线程在持续计算。证据指向 Gazebo 内部计算路径的尖峰负载；尚未定位到物理、渲染或某个模型插件的具体线程/调用栈。

线程级复测 4/5 完成、无视觉门控。0 号机启动期约 687 ms 原始里程计空窗对应独立时钟约 671 ms 墙钟间隔、仅 4 ms 仿真推进；此间 Gazebo 进程约消耗 690 ms CPU，其中同一线程约消耗 620 ms。后续长间隔也主要由该线程占用。该线程的系统名称只有 `ruby`，没有函数级采样栈，不能据此指定为物理、渲染或里程计插件。这个采样将负载定位到 Gazebo 进程中的一个热线程，但仍缺函数级归因。

## 函数级采样与时钟对齐

又保留了两轮原配置五机诊断。第一轮 `fleet-vio-gate-perf-probe-1` 使用 `perf` 采样，5/5 完成；它的默认采样时间戳与独立 `/clock` 探针使用的 Linux `CLOCK_MONOTONIC` 不同，且两者偏差随运行时间变化，所以只保留总体调用栈，**不用于逐个时钟空窗归因**。第二轮 `fleet-vio-gate-perf-mono-probe-1` 显式使用 `perf record -k mono -F 49 -e cpu-clock -g --call-graph dwarf,8192`，时间戳与探针对齐。第二轮 4/5 完成、5/5 落地、转发正常关闭，1 号机未逃出森林；其 `state_health_failures` 为 0，不能把这次任务失败归咎于视觉新鲜度门控。两轮的 PX4 ULog 证据均接受了 GNSS 关闭后的视觉融合。性能采样会改变线程调度和开销，因此这两轮只用于定位，不并入未采样的完成率基线。

对齐轮次的独立 `/clock` 探针记录了 27 个至少 100 ms 的墙钟间隔，每个间隔只推进 4 ms 仿真时间。启动期最长的两个间隔为 388 和 776 ms，调用栈混合了 Ogre、Mesa Gallium 和内核内存分配/缺页，不能把它们与稳定飞行期混为一谈。从首个时钟样本起 20 秒后，长间隔内的 137 个 CPU 样本中 78 个包含 Mesa Gallium、71 个包含 Ogre、68 个包含 Gazebo sensors 调用栈；同阶段非长间隔的 3984 个样本中分别为 751、636、621 个。渲染相关栈在长间隔内显著富集，而物理相关栈在这些间隔中仅有少数样本。分类可以重叠，样本频率有限，不能据此计算每个系统的独占耗时，也不能宣称渲染是唯一原因；但它将下一轮单变量实验指向渲染后端和传感器更新调度，而不是先放宽 250 ms 安全门控。

另用 `eglinfo -B` 查询同一 WSL 环境：X11/Wayland EGL 初始化失败，无显示（surfaceless）EGL 报告的 OpenGL renderer 是 Mesa `llvmpipe (LLVM 20.1.2, 256 bits)`；临时设置 `MESA_LOADER_DRIVER_OVERRIDE=d3d12` 后仍报告 `llvmpipe`。这说明此环境的无显示 EGL 路径目前是 CPU 渲染，符合 `perf` 中 Mesa Gallium 热栈的方向；查询工具与 Gazebo 并非同一进程，尚未直接证明 Gazebo 的上下文一定选择了该 renderer，也未证明更换后端即可满足五机尾部延迟。查询输出见 `renderer-eglinfo.txt`。

本机原始数据、对齐分析和调用栈摘要分别保存在 `results/vio-stress/fleet-vio-gate-perf-mono-probe-1/gazebo-perf.data`、`perf-window-analysis.txt`、`gazebo-perf-flat.txt`；采样器命令和分析脚本在同一目录。第一轮原始数据保存在 `results/vio-stress/fleet-vio-gate-perf-probe-1/`。两轮的紧凑清单、摘要、轨迹回放哈希和原始文件 SHA-256 由 `tools/snapshot_vio_gate_results.py` 写入 `docs/results/vio-safety-gate/raw-artifact-index.json`。大体积原始数据未提交到 Git；仅有版本化哈希不能独立重算函数级结论。

## 下一项可判别测试

下一轮先记录 Gazebo 进程实际使用的 OpenGL/EGL renderer 与传感器更新耗时，再在相同五机世界、传感器分辨率和更新率下仅改变可用的渲染后端，做成对复测；如无法更换后端，应分别记录渲染与物理步时长以确认热点。验收同时看 `/clock` 与原始视觉流的尾部间隔、PX4 融合和任务完成率，保留所有失败；不能把阈值调大当作修复。现有六次未进行 `perf` 采样、正式配置的无故障五机基线分别为 1/5、5/5、5/5、4/5、5/5、4/5；差异不允许用单次成功宣称稳定。原项目已经开始阶段 0，后续真实相机加 IMU 的 VIO 替换应按总路线图阶段门槛推进。当前转发的是 Gazebo 位姿真值，不是已完成的相机与 IMU VIO。

第三轮大型原始文件保存在本机 `results/vio-stress/fleet-vio-gate-baseline-pause-probe-1/`。`vio-relay.jsonl` SHA-256 为 `c42dcd688bab7c9e5a6c683a03710dd58fab00fa547546d2acbc0d63609fa33e`；`runtime-probe.csv` SHA-256 为 `e7cf1e7b89982b602de0fe59c58face58da5e62d3cb643a3e98dfdcad308a8b8`。诊断探针源码保存在同一原始结果根目录，未纳入控制代码。

第四轮原始文件保存在本机 `results/vio-stress/fleet-vio-gate-baseline-pause-probe-2/`。`vio-relay.jsonl`、`runtime-probe.csv`、`clock-probe.csv` 的 SHA-256 依次为 `62459e4760121331cd822d294c41f51ccc7a3cca16402559499b1f60ad1332e5`、`d3dccc918cb18188afaec45a34e5fc599043a9453b44bd4d684ae8a303331c49`、`606dda0b4b6c35d373d83b0231294659f960ee269a2c381d3ba23e56e3d240af`。

两轮的清单、摘要和故障配置已复制到 `docs/results/vio-safety-gate/`，原始文件哈希见其 `raw-artifact-index.json`。交互轨迹回放也保存在各自原始目录；探针 CSV 和 ULog 仍仅在本机，不能仅凭版本化摘要重算全部时钟结论。

消融轮次完整原始文件见本机 `results/vio-stress/fleet-vio-gate-depth-quarter-pixels-probe/`；被临时修改的相机 SDF 副本 SHA-256 为 `4a6218067eb9f32c8a14ea2be8b0798edf00243c8ad7c4917d7ff3b36f6ad83c`，恢复后的正式相机文件 SHA-256 为 `f8d49346ec66e02ed3f8caca2d4429ac339380ae6af00f97affa0e1ab3455bcd`。该轮 `vio-relay.jsonl`、`runtime-probe.csv`、`clock-probe.csv` 的 SHA-256 依次为 `60363b0f5a34a69bfaecd3e72aede9a096616573275d44a385ecb69eae10fdc6`、`78d336556f58e6347d6c95eb54069a100b05d7ef8bd1698f6d9579309210f775`、`b5237f7e1fa2f901ce3fc57820ea491663257bdf631d120474f3127e6c5bd05b`。

进程探针轮次原始文件见本机 `results/vio-stress/fleet-vio-gate-process-probe-1/`。`vio-relay.jsonl`、`clock-probe.csv`、`process-probe.csv` 的 SHA-256 依次为 `1a57279dd0fbb9557da2ecc092dbf930be1a261bf0d95468890bd511a959cf65`、`5aa329ab96bb48a6a9d204059a78a407ae6f5b823febc66f7ba6549ef3ec0ba1`、`322ff2a0b663a26b410dbaa015865d2be43d3a50350d7fd7adfb7e7afe7e2d0c`。

线程探针轮次原始文件见本机 `results/vio-stress/fleet-vio-gate-thread-probe-1/`。`vio-relay.jsonl`、`clock-probe.csv`、`thread-probe.csv` 的 SHA-256 依次为 `0d6ac885f1f56859dcd95e927114cf7238aa375f7e61758e9191b9e8c5c7c5e0`、`67a5f47dae80c6122929a89311446cd2279478c274e3715e0d7e86689bffa25f`、`f8da3c1223ebfd22e064bda91556613fdabfc99e9a8f4dd35c3b8b014f4bc03a`。
