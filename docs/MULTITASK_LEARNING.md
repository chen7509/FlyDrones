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

## 固定安全边界

MaleCNS 视觉反射、安全投影器和 PX4 内环永远冻结。部署检查点只包含共享 actor，不包含读取全局仿真真值的集中式 critic。无人机之间只交换经验摘要、模型版本和哈希，不传递可直接执行的权重。

真机候选默认处于影子模式：候选计算动作但不控制飞机。只有离线回归、签名验证和安全门槛全部通过后，才允许单机金丝雀；首次碰撞、安全失败或推理超时会自动回滚。

仿真结果不是无人值守真实飞行的许可或安全认证。进入真实飞行前仍需依次完成 PX4 SITL、硬件在环、笼内或系留试飞，并遵守机型、场地和监管要求。
