# XRCE 受管 Docker daemon 身份契约实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为未来未解锁 PX4/XRCE 同回合收集提供失败即拒绝的同 daemon 前后只读证据，旧 v8–v10 不追认。

**Architecture:** 独立模块执行三条固定 WSL Docker 查询并验证两份结构化记录。运行器在创建容器前和清理后调用；本阶段只演示当前只读探测，绝不把探测当实际捕获。

**Tech Stack:** Python 3.12、现有 Windows→WSL Docker CLI、pytest。

**Spec:** `docs/superpowers/specs/2026-10-12-xrce-owned-daemon-identity-design.md`

## Global Constraints

- 不终止或更改无关容器；不启动 PX4/Gazebo/OpenVINS/Agent/训练。
- 不降低 4 GiB 物理门槛，不追认 v8–v10，也不把 daemon 一致性冒充 PX4 发布身份。
- 所有固定命令使用参数列表和同一 WSL Docker 路径，查询失败即拒绝。

## Review Focus

- Docker 查询返回非零但输出为空；必须拒绝。
- daemon ID 或 context 在两次探测之间变化；必须拒绝。
- 精确受管名称仍存在；必须拒绝，不能操作无关容器。
- `ps` 结果有多行或异常名称；必须拒绝。
- 只有只读探测，没有运行/清理过程；必须继续报告捕获来源资格为 false。

## Task 1: 纯函数和真实只读探测

- [x] 在 `tests/test_xrce_owned_daemon_identity.py` 写正常、错误码、ID/context 漂移、受管残留与结构变异用例，先观察 RED。
- [x] 实现 `tools/connectome/xrce_typed_probe/daemon_identity.py`，使用唯一 WSL Docker 命令入口和可注入 runner；仅验证精确受管名称。
- [x] 运行 GREEN、相邻 XRCE 回归与 Ruff；只读查询当前两个环境并留原始记录。

## Task 2: 证据与集成边界

- [ ] 写阶段报告，区分当前身份观测与未来回合证据；封存测试和真实只读结果。
- [ ] 独立复核失败即拒绝与无关容器不受影响，提交并只推 personal、更新草稿 PR65。
