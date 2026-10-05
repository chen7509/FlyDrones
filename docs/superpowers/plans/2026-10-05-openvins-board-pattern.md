# OpenVINS 板面粗块纹理试验实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Spec:** `docs/superpowers/specs/2026-10-05-openvins-board-pattern-design.md`

- [ ] 校验来源、运行进程和现有静态探针；冻结图案及只改板面 URI 的语义契约。
- [ ] 先写确定性、几何/传感器保持、输入篡改、覆盖拒绝、写失败保留及可选贴图复制测试，再实现生成器/采集器适配。
- [ ] 生成独立基线与变体，核对全部哈希、SDF与相机位姿；串行运行两个静态渲染探针，保存失败并统计 FAST-20 内区角点。
- [ ] 仅在静态筛选通过后，运行一次完整果蝇单机 PX4/Gazebo 采集，保存 RGB、相机信息、ULog、控制延迟及安全终局。
- [ ] 冻结 OpenVINS 配置做离线回放，核对预解锁半窗轨迹、初始化、视觉更新、ATE和故障；任何失败不删不覆盖。
- [ ] 运行针对性和必要回归、独立复核、封存全部证据、提交草稿 PR，并按结果选择下一依赖。
