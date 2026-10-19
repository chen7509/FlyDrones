# 固定源码两份缺项修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans after explicit authorization. 本计划只有两份文件的条件恢复与当前观察；不能据此部署生产代码、创建toolchain或启动构建。

**Goal:** 在不删减固定143份清单的前提下，为两个缺项准备精确、可否决的最小修复。

**Architecture:** 使用此前保存的固定上游原始字节作为复制输入。用户批准后，先验证这两份输入，再在一次有界WSL观察器中仅对缺失目标独占创建；已有文件只观察，任何差异即停止。新回执仅证明本次实际行为，不认证历史库或未来连续性。

**Tech Stack:** Windows文件I/O、隔离Linux Python标准库；无编译器、网络、包工具或原生目标。

**Spec:** `results/native-linux-missing-source-two-plan-20261019/proposal.json`，依据上一阶段`missing-evidence.json`和现有生产`verify_upstream`的143份要求。

## Global Constraints

- 当前状态为PREPARED_NOT_AUTHORIZED_NOT_EXECUTED。本轮仅保存本地方案，没有读取两份旧payload、访问Linux或写入Linux。
- 原只读授权已经结束；本项首次涉及Linux条件创建，须人类明确批准本精确两份。
- 固定上游commit为69488123ed9362dd44b6f28e7f4680abbff1442b；清单、生产代码、45bindings和准入模板不改。
- file67108864B、total201326592B、read27s、parent30s+terminate5s+kill5s、outer45s、metadata/stderr各2097152B、link40hops均不扩。目标写入最多48249B。
- 不覆写、删除、rename、建目录、修权限、换路径或失败后补批；partial或清理不明保留UNKNOWN。所有旧CONSUMED状态不重开。
- 不采CMake/重读141源码/旧库对象日志；不部署生产、不创建toolchain、不刷资源、不编译/native/SDK/tests。仅personal原分支，PR正文不改，goal blocked、automation ACTIVE、全部资格和dispatch false。

## Review Focus

1. 目标当前是否缺失未知；若已有regular文件，应只读比对，相同则不写，差异即停。
2. 保留源不等于当前Linux输入；批准后的复制前校验与复制后实际回执必须分开记录。
3. 祖先或目标重定向、身份变化或已知旧payload别名应拒绝，不能跟随或修复。
4. 中途写入失败可能留下partial文件；没有end不得生成完整pin，不删除重试。
5. 两份成功也只补选中缺项；141份旧时点观察不刷新，第一阶段其余闭包/部署/toolchain/准入仍未完成。

## Task 1: 独立批准精确范围

**Files:** Create `results/native-linux-missing-source-two-plan-20261019/authorization-receipt.json` only after a real human reply.

- [x] 从保存manifest字段冻结路径、大小、SHA256与Git blob SHA1；没有读取原payload或重hash旧档案。
- [x] 完成方案自查：新建仅限下表两份，0新增目录/其它写入，全部上限和失败未知保留。
- [ ] 获得明确批准并记录真实原文；“方案已准备”不能改写成“已授权/已修复”。

| 保留复制源（仓库内） | Linux精确目标 | 字节 |
|---|---|---:|
| results/native-offset-run-plan-20261018/upstream-source/LICENSE | /home/yuchen7509/flydrones-upstream/open_vins/LICENSE | 35149 |
| results/native-offset-run-plan-20261018/upstream-source/ReadMe.md | /home/yuchen7509/flydrones-upstream/open_vins/ReadMe.md | 13100 |

SHA256和Git blob SHA1完整值见proposal.json。两个保留源路径仅通过文件名定位，本轮未再次读取内容。

## Task 2: 批准后一次条件恢复及观察

**Files:** New helper/start/raw/results under a new explicitly named two-file execution result directory, not an old attempt/build directory; exact directory is frozen before execution and never changed for retry.

**Consumes:** Task1批准、proposal两项、原固定manifest字段及保存的既有路径/身份排除索引。

**Produces:** 每份实际来源校验、Linux目标before/after、创建或已有只读结果、完整end/pin或partial/UNKNOWN；所有资格false。

- [ ] 完整读取继承历史与必要约束后，准备一项标准库观察器及Windows有界父进程；仅AST检查新helper，不重跑旧tests。
- [ ] 只读两份保留源，校验大小、SHA256和Git blob SHA1；任一差异在Linux写入前停止，无网络回源。
- [ ] 一次执行：必要祖先无链接检查，既有文件只读；缺失时O_EXCL/O_NOFOLLOW独占创建且不扩大48249B写界。任一步失败即停止，无删除重试。
- [ ] 校验新回执和本次新字节，保留真实错误与未完成状态；不得复核旧档案来冒本次进展。
- [ ] 仅封存新结果并发布personal；不自动进入生产部署、toolchain或build阶段。

## 后续顺序和本轮边界

两份处理完才回到Linux生产源码绑定、显式toolchain及剩余输入闭包；最后才准备fresh一次构建准入。构建后的实际新库/adapter、ABI、loader、实测标定/noise和run准入仍是后续要求。已有软件链不重做，旧库来源G1–G7仍UNKNOWN。

本轮一次本地文本搜索误包含旧fixture JSON，工具报告输出截断；未执行tests/WSL或修改payload，不声称该控制台原文完整保全。后续限定为精确JSON字段或文件名读取。此诊断不是新native失败或闭环进展。
