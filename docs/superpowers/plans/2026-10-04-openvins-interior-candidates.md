# OpenVINS 边界内候选角点审计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 统计固定开发图像中检测器实际看到、实际补入的边界内候选角点，并据此选择下一项单变量干预。

**Spec:** `docs/superpowers/specs/2026-10-04-openvins-interior-candidates-design.md`

### Task 1: 来源和日志契约

- [ ] 核对 PR #28 的 ZIP/哈希、完整源图像、runner/配置及独立上游工作树，确认没有竞争进程。
- [ ] 定义候选/最终新增记录、帧配对和整数边界规则，先写正常、缺失、重复、错位和边界测试并观察 RED。

### Task 2: 隔离插桩与固定回放

- [ ] 实现严格解析器至 GREEN，并跑 Ruff。
- [ ] 隔离应用固定上游与前四个补丁，仅补记录候选/新增坐标；构建并核对 runner 的 `ldd`、源差异和库哈希。
- [ ] 仅回放一次相同离线输入，记录资源、原始 stdout/stderr、退出码、状态哈希和全部异常。
- [ ] 逐帧/逐 ID 审计候选及新增的内区/边界归属、下一帧存活和半窗计数，不把候选称为可用 VIO 轨迹。

### Task 3: 验证和交付

- [ ] 报告直接观察、推断限制与下一项单变量开发试验；封存原始证据及逐文件 SHA。
- [ ] 跑定向及必要回归测试，完成独立只读复核，提交基于 PR #28 的草稿 PR。
