# XRCE 受管 Docker daemon 身份契约

## 目标与边界

下一次真实来源研究需要把 ROS 2 收集器所在 Docker daemon 的启动前、运行后记录绑定到同一实例。历史 v8–v10 的 Windows `docker` 检查和 WSL `docker run` 没有当时的 daemon ID，不能追认。本阶段只提供未来运行可调用的只读门禁和故障拒绝，不启动 PX4、Gazebo、Agent 或容器，也不授予来源、融合、训练或飞行资格。

## 输入与判定

通过同一 `wsl -d Ubuntu -- docker ...` 路径分别运行 `info --format {{.ID}}`、`context show` 和 `ps -a --filter name=^/<escaped-owned-name>$ --format {{.Names}}`，保留每条命令、退出码、标准输出/错误和采样时钟。容器名中的点号按正则字面量转义；失败异常携带已完成查询及失败命令，供未来执行器保存原始拒绝。启动前和清理后，daemon ID 必须是同一非空值；两次上下文也必须相同；每次精确受管名称查询必须成功且为空。只检查本试验受管名称，不要求或操作无关容器。任何命令失败、空/多行身份、上下文变化、受管名称出现或记录结构变异均拒绝。只有同时具备已受管的运行与清理结果时，这个门禁才是完整的运行生命周期证据；本模块单独的两次只读探测不能证明中间运行或真实 PX4 来源。

## 取舍与依据

沿用已经使用的 Docker CLI，不装新服务或更改 daemon。Docker Desktop 当前 Windows 与 WSL 查询显示同一 ID `6629cb9a-7501-4f8c-8512-b36360787f36`，但这只是本次只读观测，不补造旧回合证据。固定上游 Agent、PX4 和 ROS 2 消息版本沿用 `docs/XRCE_TYPED_ODOMETRY_DIAGNOSTIC_REPORT.md` 的来源表；此门禁只处理容器归属，不能以 Docker ID 代替 XRCE client、PX4 PID、ULog、相机标定或 EKF2 健康证明。
