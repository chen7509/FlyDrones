# 固定 EGO-Swarm 教师的合成输入烟测（2026-10-09）

**结果：固定 Docker 镜像内的真实 `ego_planner_node`、`traj_server` 和项目 ROS 桥接器，接收一帧明确标记的合成静止观测后返回了 `PositionCommand` 参考。** 上游日志有 `traj 1 success` 和 `plan_success=1`；桥接返回的 `position_ref`、`velocity_ref`、`yaw_rate`、两个时间字段通过当前 `EgoController.validate_reference()`。这是端到端协议与规划启动烟测，不是 PX4/Gazebo 飞行、真实 VIO、训练样本或公平对照成绩。

输入 `synthetic-static-depth-10m-v1` 固定 `sim_ns=1,000,000,000`，静止位置 `(0,0,1.5)`、目标 `(8,0,1.5)`、全图 10 米深度、160×120 `32FC1`。没有动力学、遮挡随机性、传感器故障或真实相机/IMU。容器从 `fly-ego-benchmark:humble` 固定镜像启动，单次上限 512 MiB、2 CPU、128 进程，没有发布 Docker 主机端口或启动 PX4/Gazebo。上游的第一个返回参考是位置约 `(0.00001647,0,1.5)`、速度约 `(0.00001396,0,0)`、航向率 `-1.5707963`；这是轨迹起始设定值，不能据此判断任务是否到达目标。返回的 `upstream_stamp_ns` 是原始上游时间，桥接另以当前观测的仿真时间 `sim_ns` 标记参考，二者均保留。

失败序列没有删改：v1 的一次性启动命令把 `source /ego_ws/install/setup.bash` 放进后台 AND-list 子 shell，导致桥接找不到 `quadrotor_msgs`；独立容器检查证实该包在正确加载环境后存在。v2/v3 的合成夹具把 ROS 严格浮点字段写成 JSON 整数，桥接拒绝并关闭连接；v3 完整日志显示 `The 'x' field must be of type 'float'`。只将夹具坐标改为浮点、保持上游镜像和桥接生产代码不变后，v4 第一帧得到参考。离线校验脚本首跑又因同目录 `inspect.py` 遮蔽 Python 标准库 `inspect` 失败；其原始失败日志保留，脚本改名后校验通过。这些均为研究夹具/启动命令问题，不计作上游规划器在物理场景中的失败。

`results/ego-upstream-source-audit-dev-1701/` 保留四次容器输出、合成客户端、首次离线校验失败、最终 `synthetic-validation.json` 与脚本；[EGO_UPSTREAM_INTERFACE_SMOKE_REPORT.md](EGO_UPSTREAM_INTERFACE_SMOKE_REPORT.md) 记录实际 ROS 图和固定上游源码。最终烟测 `CLIENT_EXIT=0` 且临时容器退出，`docker ps` 无遗留容器。宿主空闲内存仍低于 1 GiB，因此没有并行启动冻结的 v7 未解锁物理诊断、完整连接组推理或新的 PX4/Gazebo 教师采集。

**资格边界：** `upstream_reference_received=true`、`adapter_reference_validation_passed=true`，但 `physical_or_fair_comparison_qualified=false`。真实教师语料仍需部署可见的非真值状态/相机输入、可核验上游轨迹、冻结单机开发场景和全部失败证据；现有合成参考不得混入训练或未见测试集。
