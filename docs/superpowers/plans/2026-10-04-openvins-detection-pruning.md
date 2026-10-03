# OpenVINS Detection Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在固定单机开发回放中准确指出单目特征检测阶段淘汰一次性 ID 的上游条件。

**Architecture:** 隔离 OpenVINS 源码只加逐 ID 淘汰原因与逐调用汇总日志；独立 Python 审计器将内部无时间戳日志与 PR #27 的逐帧日志按调用顺序严格关联，并与原始输入/状态哈希交叉核对。

**Tech Stack:** 固定 OpenVINS C++/OpenCV、WSL Ubuntu/g++、Python 3、pytest、Ruff。

**Spec:** `docs/superpowers/specs/2026-10-04-openvins-detection-pruning-design.md`

### Task 1: 预检与解析契约

- [ ] 核对上轮封存索引、源码/输入/状态 SHA、进程与独立上游工作树；定义五种互斥剔除原因和正常/提前返回日志格式。
- [ ] 写严格配对审计的正常、边界、缺失/重复 ID、未知原因、数量不守恒和帧错位测试，并观察预期 RED。

### Task 2: 插桩和固定输入回放

- [ ] 实现最小解析器使测试 GREEN，运行 Ruff。
- [ ] 在独立固定上游源码应用既有三个补丁与新只读检测日志补丁；构建、核对 `ldd`、保存哈希及差异。
- [ ] 对同一输入仅执行一次离线回放，保存完整 stdout/stderr、状态、资源与退出码；严格核对输出与上轮状态 SHA。
- [ ] 逐帧关联内部检测日志、旧 ID 与后续 KLT 帧，输出每种原因及每个短寿命 ID 的证据；保留所有异常。

### Task 3: 验证和交付

- [ ] 报告直接观察到的代码剔除条件及无法推断的物理原因，封存原始证据和逐文件哈希。
- [ ] 运行针对性与必要回归测试、独立只读复核，修正实质问题后提交基于 PR #27 的草稿 PR。

## Review Focus

- 五个互斥删除分支的计数与输入旧 ID 守恒。
- 不需要新特征时的提前返回也必须有汇总行。
- 一个内部检测调用仅对应一个单目帧，丢行、重行和时间顺序异常都拒绝。
- 被剔除 ID 必须来自上次保留的 ID，而不允许把新补点 ID 误记为旧轨迹丢失。
- 本轮状态字节哈希与 PR #27 不同则报告失败，不宣称日志不扰动。
