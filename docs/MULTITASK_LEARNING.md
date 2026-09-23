# 多任务持续学习

这套流程训练同一个循环策略完成出口导航、移动目标跟随、区域搜索、多机覆盖、动态编队、门框赛道，以及由现有分布式任务层负责的电量换班和故障接管。

## 安装

```powershell
python -m pip install -e ".[learning,dev]"
```

## CPU 烟雾训练

```powershell
python tools/train_multitask.py --level 0 --seed 42 --steps 64 `
  --checkpoint results/multitask-smoke/checkpoint.pt `
  --report results/multitask-smoke/train.json

python tools/evaluate_multitask.py `
  --checkpoint results/multitask-smoke/checkpoint.pt `
  --seeds 100,101,102 --episodes 3 `
  --report results/multitask-smoke/evaluation.json
```

烟雾训练只验证数据链、PPO 更新、检查点和报告，不会达到正式准入门槛。长训练使用同一入口，并显式传入 `--fleet-size 20`、`50` 或 `100` 以及更大的 `--steps`。课程及阈值位于 `configs/multitask_training.yaml`。

## 可恢复课程训练

课程入口会按固定种子依次训练、评估和验证任务接管，并在每一批结束时先写检查点与报告，最后原子更新 `state.json`：

```powershell
python tools/run_multitask_curriculum.py `
  --config configs/multitask_training.yaml `
  --profile smoke `
  --output results/multitask-curriculum-smoke `
  --device cpu --max-batches 1
```

对同一个输出目录再次运行会从 `latest-trainer.pt` 继续，且不会重复已经提交的批次。`--restart` 会在原目录下创建新的运行子目录，保留之前的状态、报告和检查点。并发写入由 `.curriculum.lock` 拒绝；配置摘要改变、检查点缺失或摘要不符时也会停止且不推进状态。

未提供完整 MaleCNS 文件时，训练和证据生成仍可运行，但反射层按失效安全方式保持，候选模型不会晋级。要启用真实桥接，请同时传入 `--malecns-connectome` 和 `--malecns-config`，并可用 `--malecns-readout` 指定读出文件。只有评估全程报告 `malecns-v1.0-live`、零回退、任务阈值、安全零事件、任务接管和旧技能回归全部通过时，`best-actor.pt` 才会更新。

输出目录中的 `best-actor.pt` 是部署候选；`latest-trainer.pt` 还包含 critic、优化器、随机数状态和训练计数，只用于恢复训练。`reports/` 保存逐批评估与回归证据，`manifests/` 保存实际执行场景，`failures/` 保存不推进状态的失败记录。

## 固定安全边界

MaleCNS 视觉反射、安全投影器和 PX4 内环永远冻结。部署检查点只包含共享 actor，不包含读取全局仿真真值的集中式 critic。无人机之间只交换经验摘要、模型版本和哈希，不传递可直接执行的权重。

真机候选默认处于影子模式：候选计算动作但不控制飞机。只有离线回归、签名验证和安全门槛全部通过后，才允许单机金丝雀；首次碰撞、安全失败或推理超时会自动回滚。

仿真结果不是无人值守真实飞行的许可或安全认证。进入真实飞行前仍需依次完成 PX4 SITL、硬件在环、笼内或系留试飞，并遵守机型、场地和监管要求。

## 独立物理后端

`MultiTaskSITLAdapter` 将单机本地策略输出转换为限幅速度设定值，并拒绝跨车辆命令。评估器支持 `--backend fast|px4|pybullet` 的依赖探测。`fast` 可直接运行；`px4` 和 `pybullet` 只验证本机前置条件，然后要求使用相应的外部逐机仿真运行器。评估器会拒绝把快速运动学结果标记成独立物理结果。

PyBullet 交叉验证使用开源 [gym-pybullet-drones](https://github.com/utiasDSL/gym-pybullet-drones)。PX4 试验继续使用仓库已有的 Gazebo 世界、独立进程和 MAVLink 链路。
