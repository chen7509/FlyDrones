# 固定源码两份缺项：已按授权恢复并回读

用户明确批准“允许精确两份条件恢复及回读”。本次只处理`/home/yuchen7509/flydrones-upstream/open_vins/LICENSE`和同目录`ReadMe.md`；两份目标实际均不存在，使用本地保存的固定提交原始字节独占创建，没有覆盖已有文件。两份随后均完整stable回读，SHA256、Git blob SHA1和大小与固定清单一致。

| 文件 | 实际写入及回读字节 | SHA256 |
|---|---:|---|
| LICENSE | 35149 | 3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986 |
| ReadMe.md | 13100 | 2553e1d5d570a391a1f8376ae4037760d84d45668d781ccf6683ccfc2a54a044 |

固定上游commit为`69488123ed9362dd44b6f28e7f4680abbff1442b`。复制前仅重新读取获准的两份保存源，校验大小、SHA256与Git blob SHA1，两个输入都正确后才进入Linux。该步骤是已授权复制输入校验，没有执行旧档案或其它payload审计。原提案保留未授权时状态；新authorization-receipt记录真实后续批准，旧报告不回填。

## 实际执行范围

一次`wsl -d Ubuntu -- /usr/bin/python3 -I -S -B -`；父进程0.234s、Linux0.015646s、exit0、readers_closed=true。两份创建、两份完整stable回读，共写48249B、读48249B，无partial/errors/触限。metadata正文6526B+14LF=JSONL6540B；stderr132B为既有localhost代理未镜像提示，没有网络请求或修复重试。

创建前逐层必要目录metadata及held directory fd/no-follow边界检查，目标缺失时O_EXCL/O_NOFOLLOW创建。精确目标before/after回读身份相同，实际create intent、created identity、write_complete和end分别记录。父目录时间可能因授权创建而变化，没有宣称父目录全部元数据不变。原3459路径拼写/3117已知native inode作为内容排除，不能证明所有未知hardlink已发现。没有目录枚举、符号链接跟随、建目录、删除、rename、chmod、覆盖或重试。

原file67108864B、total201326592B、共享restore/read27s（首metadata最多10s仍在27内）、parent30s+terminate5s+kill5s、outer45s、metadata/stderr各2097152B、40linkhops均未扩。更窄目标写界为48249B，只两份。Python标准库观察器及隐式运行依赖未获来源认证或完整保全；同步filesystem和父进程终止机制不是敌对文件系统认证、hardcancel、crashdurability或完整后代保管链证明。

本轮新helper AST、实际保存的新JSON/字节与新ZIP完整性核验之外，没有tests、旧archives/payload核验、第二source/native/delivery审；没有compiler/configure/link/native目标、SDK、资源查询、生产部署、toolchain创建或其它Linux写入。旧raw/report/ZIP/map、生产源码、45bindings和admissiontemplates保持未修改。

## 现在到哪一步

原固定143份清单已有143份跨时点实际内容回执：上一轮141份与本轮2份。两份缺项已补齐，不能继续把它们列成缺内容；但这不是同一时点的143份原子快照，上一轮141份本次没有重读或刷新，也没有证明实际构建消费。两份是本次恢复副本，不能冒称原Linux checkout一直包含它们或证明旧库历史。

第一阶段尚未完成，剩余顺序为：

1. 绑定当前Linux生产源码与capture入口。
2. 形成并绑定显式toolchain_file/toolchain_receipt，以及完整命名输入闭包。
3. 按原资源、无竞争、cgroup/pidfd、预算、停止和清理门槛，独立取得fresh一次构建准入。

新库/adapter成功构建及释放回执、实际ABI/递归与lazy loader闭包、实测calibration/noise和source-clock-runtime-wire、run准入仍属后续阶段。没有自动build→run。当前所有资格、runtime_graph_frozen、physical_dispatch_ready和dispatch均false，goal blocked、automation ACTIVE、仅personal原分支。旧库32/34/G1–G7与全部UNKNOWN/CONSUMED、原安全预算、完整单机和后续目标保持。

详细记录在`results/native-linux-missing-source-two-20261019/`。本精确两份选择已结束，不自动追加采集、写入、编译、运行或资源刷新。
