# 可恢复多任务课程训练设计

## 目标

在现有快速多机环境和循环 PPO/MAPPO 风格实现上，增加能够长期运行、断点续训、逐级晋级和回归旧技能的课程训练系统。系统先在计算机内训练和验证，不启动 PX4、Gazebo 或真实无人机。任何安全门槛、任务门槛或旧技能保持门槛失败时，候选模型不得晋级。

目标运行机器为 Windows、NVIDIA GeForce RTX 3070 Ti Laptop GPU（8 GB 显存）、约 16 GB 内存和 20 个逻辑处理器。默认配置必须能在该机器上安全运行，100 机长课程只能通过显式参数启用。

## 当前基础

现有实现已经提供：

- `ScenarioGenerator`：按种子生成第 0 至第 4 级场景。
- `MultiTaskEnv`：局部 actor 观察、训练专用 critic 真值和每机奖励。
- `SharedRecurrentPolicy` 与 `CentralizedCritic`。
- 单次 clipped PPO 更新、部署 actor 导出和保留种子评估。
- `MultiTaskAcceptance`、安全投影、持续学习门禁及 PX4/PyBullet 失败关闭边界。

当前训练入口每次从头初始化，只训练一个场景，并只导出 actor。它无法恢复 critic、优化器、随机数状态或课程位置，也不能依据跨技能回归结果选择模型。

## 设计原则

- 继续使用现有 PyTorch、NumPy、Gymnasium 和 YAML 依赖，不引入 RLlib 或新的训练框架。
- 训练过程可恢复且可重放。相同配置、起始检查点、种子和已完成批次产生相同的离散课程状态。
- 训练检查点与部署 actor 分离。训练检查点可以包含 critic 和优化器；部署产物只能包含 actor。
- 场景训练种子与保留评估种子严格分离。
- 一个批次必须完整提交后才推进状态。进程中断不能产生“已完成但没有有效检查点”的状态。
- 新技能训练后必须重新评估已经完成的技能；任何技能成功率下降超过 2 个百分点时回滚。
- 快速环境结果只能解锁下一快速课程阶段，不能直接解锁 PX4 或真机阶段。

## 架构

### 可恢复 PPO 训练器

新增 `flydrones.multitask_trainer`，负责单个训练批次。训练器持有：

- 共享 actor、集中 critic 和 Adam 优化器。
- 当前全局更新数和环境步数。
- Python、NumPy、PyTorch CPU 和 CUDA 随机数状态。
- actor/critic 架构版本、优化器超参数和训练配置摘要。

训练器接受一个完整的 `ScenarioManifest` 和本批次步数，采集新鲜 on-policy 轨迹并执行 PPO 更新。每架无人机的 GAE 和循环隐藏状态保持独立；节点失效、回合终止或截断结束对应轨迹。普通历史轨迹不进入 PPO 梯度批次。

训练检查点使用版本化字典并原子写入：

```text
schema_version
actor_state_dict
critic_state_dict
optimizer_state_dict
actor_metadata
critic_input_dimension
global_updates
environment_steps
random_states
config_digest
curriculum_state_digest
```

加载时逐项验证 schema、网络维度、配置摘要和所有必需字段。损坏、缺项或不兼容的检查点必须报错，不得部分加载。critic 输入维度随机群规模变化，因此课程训练器为每个规模维护独立 critic；actor 在规模之间继承，critic 在规模变化时重新初始化并在状态中记录。

### 课程定义与调度

扩展 `configs/multitask_training.yaml`，为快速课程增加三种资源配置：

- `smoke`：验证恢复和报告链路，1/5 机，小批次。
- `desktop`：本机默认正式训练，1/5/20 机，并限制并行环境和批量大小以适应 8 GB 显存。
- `full`：显式启用 20/50/100 机和完整保留集；允许长时间运行，但仍必须满足内存上限。

每个阶段明确列出训练种子、评估种子、机群规模、每批步数、最大批次数、最少改进量和耐心值。配置加载器拒绝：

- 训练种子与评估种子重叠。
- 重复阶段 ID 或非连续阶段序号。
- 超过 100 机、空种子集、非正步数或非正批次数。
- `smoke` 或 `desktop` 隐式包含 100 机。
- 阶段引用当前 `ScenarioGenerator` 不支持的等级。

阶段同时明确 `active_skills`，不能依赖种子随机抽中所需技能。`ScenarioGenerator.generate()` 增加可选的技能覆盖参数；覆盖值仍经过 `ScenarioManifest` 的完整校验，并进入场景摘要。单技能阶段为出口、跟随、搜索、编队和门框分别建立独立阶段 ID；双技能阶段使用配置中明确列出的技能对。

调度顺序为：

1. 第 0 级现有能力回归。
2. 第 1 级单技能课程。
3. 第 2 级成对任务。
4. 第 3 级 20/50 机复合任务。
5. 第 4 级 20/50/100 机全量压力场景。

每批从阶段训练种子中确定性轮换，不因恢复次数改变种子顺序。

### 课程状态机

新增 `CurriculumState`，使用原子 JSON 文件保存：

```text
schema_version
run_id
config_digest
profile
stage_index
batch_index
global_updates
environment_steps
latest_checkpoint
best_actor
best_score
completed_stages
failed_attempts
last_committed_batch
```

状态只有以下转换：

- `READY -> TRAINING`：开始当前批次，不提前修改持久状态。
- `TRAINING -> EVALUATING`：训练检查点原子写入成功。
- `EVALUATING -> COMMITTED`：批次报告和状态原子写入成功。
- `COMMITTED -> READY`：进入下一批或下一阶段。
- 任意运行态到 `FAILED`：保留上一个已提交检查点和失败报告。

恢复时只读取最后一个 `COMMITTED` 状态。孤立临时文件、只有训练检查点但没有提交状态的批次、摘要不匹配的文件均忽略并记录。`--restart` 创建新的 run ID；默认行为是发现已有状态就恢复，配置摘要不一致时拒绝运行。

### 评估、最佳模型与阶段晋级

每个训练批次后用当前阶段的保留种子运行只读评估。评估报告必须记录：

- 模型、配置和场景摘要。
- 每技能成功率、奖励分量和完成证据。
- 碰撞、越界、低电量违规、安全接管和中央逐机指令计数。
- 当前阶段分数以及未通过的硬门槛。

快速环境新增累计遥测，直接测量跟随距离误差和丢失步数、联合覆盖和重复覆盖、编队槽位误差、门平面穿越和接触、任务完成证据及安全失败。评估器只能从这些累计量计算指标，不能用成功标志映射成固定 RMSE，也不能用常数代替未测量结果。没有观测值的指标以“缺少证据”失败。

电量换班和节点故障重分配继续由确定性的 `MissionAgent` 与任务账本负责，不把租约控制权交给 actor。新增只读 `MissionValidationRunner`，在固定种子下注入低电量、节点退出、消息延迟和分区，测量任务释放、重新开放和重新分配时间。课程阶段可以同时要求 actor 环境评估和任务账本验证；二者必须全部通过才能晋级。任务验证数据不进入 PPO 梯度。

阶段分数只用于在满足全部硬安全门槛的候选之间选择最佳模型。发生碰撞、越界、低电量违规、非有限指标、模型加载错误或中央逐机指令时，候选没有资格成为最佳模型。

候选通过当前阶段门槛后，对所有已完成阶段使用固定回归种子重新评估。新模型相对每个阶段保存的基线成功率下降不得超过 0.02。通过后，原子导出新的 `best-actor.pt` 并推进阶段；失败时保留当前稳定最佳 actor，记录退化技能和种子，并继续当前阶段，直至达到最大批次数或早停。

达到最大批次数但仍未通过时，运行状态为 `FAILED`，进程返回非零，且不会自动进入下一阶段。耐心值只允许在候选已满足硬门槛、但分数没有继续改善时提前结束；它不能绕过安全或任务门槛。

### 命令行入口和产物

新增：

```powershell
python tools/run_multitask_curriculum.py `
  --config configs/multitask_training.yaml `
  --profile smoke `
  --output results/multitask-curriculum-smoke
```

可选参数：

- `--device auto|cpu|cuda`，`auto` 优先使用可用 CUDA。
- `--resume` 为默认语义；`--restart` 必须显式指定。
- `--max-batches N` 只限制本次进程运行量，不改变课程定义，用于可控的短运行。
- `--stop-after-stage N` 在阶段提交后正常退出。

输出目录结构：

```text
state.json
latest-trainer.pt
best-actor.pt
manifests/
reports/batch-<stage>-<batch>.json
reports/regression-<stage>-<batch>.json
failures/<stage>-<batch>-<seed>.json
```

所有 JSON 和检查点先写同目录临时文件，再执行原子替换。仓库只提交 smoke 状态摘要，不提交大型检查点、轨迹或完整课程日志。

### 资源控制

- 一次只运行一个课程进程；输出目录中使用带进程信息的锁文件防止双写。
- `desktop` 默认最多 20 机；50/100 机属于 `full`。
- 环境采样仍主要在 CPU，GPU 用于网络前向和 PPO 更新。首版不增加多进程环境，避免 16 GB 内存下复制大量场景状态。
- 每批结束后释放轨迹张量并记录 CPU、GPU 峰值内存和批次耗时。
- CUDA 内存不足时本批失败并保留上一个提交点，不自动减小规模后伪装成功。

## 安全边界

- 课程训练器不能启动 MAVLink、PX4、Gazebo 或硬件接口。
- 部署 actor 不包含 critic、优化器或仿真全局真值。
- 安全投影、MaleCNS 反射、地理围栏、返航阈值和 PX4 内环继续冻结。
- 评估缺少真实证据的指标保持失败，不使用常数推断为通过。
- 训练失败、磁盘写入失败或恢复校验失败不会覆盖最后稳定 actor。

## 测试策略

- 配置测试覆盖重复阶段、重叠种子、非法规模和资源配置越界。
- 检查点往返测试比较 actor、critic、优化器、计数器和随机数状态。
- 恢复测试在固定批次边界中断，确认恢复运行与不中断运行产生相同 actor 摘要和课程位置。
- 损坏检查点、摘要不一致和残留临时文件测试必须失败关闭。
- 调度测试确认种子顺序稳定、规模变化重置 critic 但继承 actor。
- 晋级测试确认安全失败不能靠高奖励晋级，旧技能下降超过 2% 会回滚。
- 锁测试确认同一输出目录不能被两个训练进程同时写入。
- CLI smoke 测试使用极小批次完整跑通训练、评估、提交、恢复和最佳 actor 导出。
- 最后运行完整仓库测试，并记录原有 MaleCNS 分组警告。

## 非目标

- 本阶段不声称训练出达到商业表演标准的模型。
- 不在本阶段启动 1,000 回合完整评估或持续数日的 100 机训练；实现完成后由显式 `full` 运行执行。
- 不迁移到 RLlib、Stable-Baselines3 RecurrentPPO 或分布式 GPU 集群。
- 不实现 PX4/PyBullet 外部执行器、硬件在环或真机在线更新。
- 不让训练器修改确定性任务账本、安全规则或飞控参数。

## 完成标准

- `smoke` 课程能从空目录完整运行并生成有效状态、训练检查点、最佳 actor 和报告。
- 在已提交批次后再次运行会恢复而不是重做；配置改变时拒绝误恢复。
- 固定种子的中断与连续 smoke 运行产生相同最终 actor 摘要。
- 安全失败、跨技能退化或损坏检查点均阻止晋级并保留稳定模型。
- 现有多任务测试和完整仓库测试继续通过。
