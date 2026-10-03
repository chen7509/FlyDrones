# OpenVINS Track Lifetime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在固定 PR #25 开发输入上定位 OpenVINS 预解锁轨迹短寿命发生于哪个前端阶段。

**Architecture:** 在隔离的固定上游 OpenVINS 单目 KLT 路径加入只写日志的帧、匹配和逐 ID 记录；本仓库独立解析器验证并汇总。保留 PR #26 计数和状态哈希作回归锚点。

**Tech Stack:** C++/OpenCV/OpenVINS、Python 3、pytest、Ruff、WSL Ubuntu/g++。

**Spec:** `docs/superpowers/specs/2026-10-04-openvins-track-lifetime-design.md`

### Task 1: 固定来源、输入与日志契约

- [x] 核对无竞争进程、PR #25/#26 封存索引、runner/config/输入 SHA，建立独立上游工作树和结果目录。
- [x] 按固定 `feed_monocular`/`perform_matching` 控制流定义首帧、匹配和逐 ID 日志格式，记录正常与提前返回的配对规则。
- [x] 写解析器接口的正常、缺失、畸形、重复、逆序、计数边界测试；运行并确认预期 RED。

### Task 2: 只读插桩、解析器和一次回放

- [x] 写最小解析器使测试 GREEN；运行针对性测试和 Ruff。
- [x] 固定上游副本应用前两轮补丁和新 `TrackKLT.cpp` 只读补丁；构建、`ldd` 核实 runner 实际加载的库，保存哈希和日志。
- [x] 对完全相同输入仅执行一次离线回放，保存 stdout/stderr、状态、退出码与资源；若回放失败，保留失败证据。
- [x] 严格审计每帧前端分层流失及逐 ID 寿命，和 PR #26 半窗合格计数与状态 SHA 比较。

### Task 3: 证据、复核、交付

- [ ] 报告可直接观察的流失阶段、未证实根因与飞行/VIO 闭环界限，封存原始证据与逐文件 SHA。
- [ ] 运行针对性和必要回归测试、Ruff、独立只读代码/证据审查，修正问题后提交并创建基于 PR #26 的草稿 PR。

## Review Focus

- 首帧仅检测、无数据库更新：测试不误判为缺失匹配。
- `perform_matching` 输入少于 10 点返回全零掩码：测试区分于空点提前返回。
- 匹配掩码通过而边界/传感器掩码剔除：测试阶段计数守恒。
- 重复 ID 或单目时间逆序：测试拒绝而非静默覆盖。
- 回放状态与 PR #26 不同：审计应报告失败，不宣称只读插桩无影响。
