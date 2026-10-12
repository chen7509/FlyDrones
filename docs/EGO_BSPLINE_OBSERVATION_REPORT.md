# EGO 完整轨迹观察与数值对照准备（2026-10-12）

当前桥接主要记录定时输出的 PositionCommand，不能据几个采样点证明原版与诊断补丁的完整规划轨迹相同。本轮增加独立只读 Bspline 观察入口及严格的候选系数比较器，原 EGO 桥接和只读补丁字节保持不变。**没有构建或运行新的 EGO 规划器，没有开始物理仿真、训练或飞行；teacher/runtime/fusion 资格仍为 false。**

固定上游 EGO23a8d5a191711dd65633df689bd00f55d4dea8f9 的 [Bspline.msg](https://github.com/ZJU-FAST-Lab/ego-planner-swarm/blob/23a8d5a191711dd65633df689bd00f55d4dea8f9/src/planner/traj_utils/msg/Bspline.msg) 包含 degree、轨迹编号、开始时刻、knots、位置和 yaw 控制点。封存 traj_server.cpp 用位置系数构造曲线，再求速度/加速度导数；yaw_pts 解读代码被注释，不能把系数相同说成实际 yaw 命令时序通过。源码来自既有 Git-tree绑定 ZIP `cb460e46c77cdff13a42a201bff2743384256ece9a687d580ed095e815e0aa14`；171字节定义 SHA `6a81d3687daf49f3152f514ed5639e55374be32dd438a4f1c90900503f8e3f85`。GPL3，既有维护观测 last-push2025-03-08 不代表当前维护活跃；本轮没有伪造新维护日期。[Humble rclpy源码](https://github.com/ros2/rclpy/blob/humble/rclpy/rclpy/node.py) 支持 raw 订阅，复用 Apache2 ROS 接口及已固定 rosbags0.11.5。官方文档遭访问保护、一次 traj_server 网页超时保留为研究限制，源码结论来自固定本地快照，未凭论文名称仿造对手。

## 实现

`tools/benchmark/ego_bspline_observation.py` 是单线程、独立订阅 CLI：明确绝对 topic/run/session、raw=True，只观察，不创建 publisher。输出独占打开；可接受消息先保存 raw 后解码，冗余字段在离线审计中重新从字节核对。512KiB单包、4096控制点/消息、16MiB raw总量；容量拒绝只记录长度和有界前缀SHA，不能复制无界数据。保留所有可记录失败，不静默删掉重复 ID、坏 knot 或缺失行。

解码严格限定当前 cubic degree3/正且无损 INT_MAX 轨迹ID/有限 Nx3/严格递增 N+4 knot/非空域/精确开始时间/有限yaw字段。规范 round-trip，最多三字节零对齐后缀，原始与规范SHA分开。不支持的曲线/大端等配置拒绝，而非静默转换。比较固定绝对1e-9、相对0，覆盖全部系数、knots、yaw、时间、ID与计数；不同项完整保留，不裁起始段、不后选 gauge、不从少量采样点插值宣称相同。

回调 monotonic 是本机观察时间，不是网络到达或源采样。30秒为观察窗口，不是抢占式解码/I/O超时；早期 ROS context结束拒绝，完成记录保留起止/原因。local run/session和相同 replay-context摘要都是本地声明，不认证发布者、实际输入消费或DDS无丢失。实际 rclpy订阅、外部进程监督与来源证明尚未运行；CLI在生成节点前要求固定独立解码依赖，旧镜像本次只运行其内置类型codec，不声称已装入新观察器及依赖。

关闭契约：原 journal 的 closed 只说明观察记录结束。实际 stream.close 后，先写并成功关闭 pending completion，再无覆盖hardlink发布canonical completion名；pending不是证明。审计/比较另要求语义摘要绑定的 exact-true success/stream_closed。关闭失败保留原closed字节和false证明或只有pending，不回填历史日志。CLI保留主异常并记录cleanup错误。canonical文件、实际进程exit及外部监督还须在未来实际运行中一并核对；这些本机程序声明不是恶意篡改防护、fsync或来源认证。

## 验证与保留失败

最终 **33项新用例，171项 EGO邻近回归通过**，changed Ruff/diff通过，5份源/旧桥接/补丁/旧ZIP前后SHA相同；没有重跑全库或全库lint。覆盖真实独立CDR、内点/knots/yaw/start不同、bool混淆、raw/字段/上下文/序号篡改、重复轨迹、空流、时钟、写/flush/关闭和完成文件发布失败，以及假的 readonly ROS生命周期。

初始缺模块为 bootstrap（工具记录）；首次13项失败是默认Python未发现既有target安装的rosbags，属于依赖环境，不是协议RED。使用原 `results/ego-cdr-field-audit-dev-1701/deps` 后，12通过/1测试行索引错误，原输出保留。后续4失败/20通过中，2个是真实 bool/未知字段漏拒绝，2个是 NumPy只读数组测试夹具错误；逐类修正后通过，没有把夹具错误称行为缺陷。

独立复核先发现 journal close失败仍可比较，再发现成功证明本身close失败后仍可用；两者独立工具反例已复现，新增明确故障用例和发布规则修复。独立原始反例stdout未作为本机文件保存，报告不伪称有先RED机器日志；修复后的 GREEN 原始输出已保存。容量措辞与提前context结束边界亦修正。最终复核结果另保留在阶段证据中。

## 一次真实 Humble codec 探针

独立预声明 `bspline-humble-codec-v1`：固定镜像 `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`，启动前宿主1143MiB，满足此离线轻量codec专用1024MiB门槛；cap256MiB/1CPU/64PIDs/networknone、内20s/外40s。这没有修改 EGO完整构建2500MiB或物理/fullMaleCNS4GiB门槛。

只 import实际 rclpy serialization和已编译 traj_utils Bspline，不调用 rclpy.init、Node或planner。直线、内控制点弯曲、三零padding三组，每组规范 payload **220字节**，独立rosbags与实际rclpy字节SHA全部一致；已核installed171字节msg定义。脚本/输入/父解码模块/旧ZIP四项启动前后hash相同，父模块后来仅日志/关闭路径修改；探针未重跑，旧925f9068…生产版本边界单独保留，不称最新整个CLI经过容器验证。

Docker start附着耗时约2.563秒，exit0/OOMKilled=false，原始inspect/stdout/stderr/selfmaps保留；唯一 owned容器 `8f85702cfa41aa8bf0989e4b4e0bc363a6c8005d8bc772ff258814d875903f2b` 移除返回0，之后无运行容器。maps文本不是全部动态库哈希闭包；没有证明生成类型源码/二进制完整预后稳定、DDS来源或真实规划器算法。不得把codec一致称原版/补丁规划等价或教师资格。

| 分类 | 结论 |
| --- | --- |
| 已验证 | 171软件/独立codec用例、三组实际Humble canonical字节一致、有界关闭/比较拒绝 |
| 仅实现 | 独立只读Bspline订阅入口、候选完整系数比较及声明context/完成证明 |
| 未测试 | 实际DDS Bspline订阅、原版/补丁同输入规划输出、真实消费状态/地图/时钟、source/type/runtime闭包及teacher |
| 失败/保留 | 依赖/夹具/两行为漏拒绝及独立关闭反例；既有RX/TIMESYNC/物理/五机RTF失败不改 |

后续优先新资源检查合格时执行冻结的 EGO单次完整构建，再对同一开发输入保存原版与补丁完整Bspline及PositionCommand，核对实际状态/地图/时钟消费，不能只信本文候选标志。真实PX4状态固件、EKF2/标定相机来源、完整MaleCNS训练/分工及单机→5→20仍未完成；本轮预声明codec源输入为合成开发消息，不进入训练或封存随机测试。所有历史和本轮证据保留，不要求安装原生Linux。证据归档为 `evidence/ego-bspline-observation-dev-1701.zip`，成员hash/CRC验证后发布。
