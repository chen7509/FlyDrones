# 多进程 UDP 压测启动信号竞态修复

上一阶段完整回归中，`test_four_independent_udp_processes_converge` 出现一次失败：四个独立工作进程里有两个在读取 `start.json` 时取得空内容，分别记录 `JSONDecodeError`，因此没有写出对应的轨迹 CSV，父进程随后在聚合时因 `agent-0.csv` 缺失而报错。失败发生在无人机运动开始前，两个进程的尝试发包数均为 0；单独重试该测试通过。事件摘要保存在 `evidence/udp-start-race-incident.json`，明确标记为从当时读取的临时日志重建的摘要，原始 pytest 临时目录随后已被清理。

原因是父进程原先直接对工作进程轮询的 `start.json` 调用 `write_text`。文件创建和内容写入不是一次可见操作；轮询仅检查“文件存在”，于是可在 JSON 写完前进入解析。现在父进程先在同目录写完 `start.json.pending`，关闭文件后调用 `os.replace` 一次发布最终文件。工作进程的启动时间、UDP 协议、机体运动、场景和验收条件均未改变；失败仍会正常暴露。旧的 `.pending` 会在下次运行被覆盖。

新增确定性测试在临时文件写完后暂停发布，确认最终 `start.json` 此时尚不存在；放行后验证 JSON 完整且时间戳正确。修复后该模块 3 项测试通过，同一四进程压测连续运行 **8/8 次通过**。完整项目回归为 **336 passed、1 warning**（159.29 秒）；警告仍是既有 Malecns 数据的神经元组无匹配项。Ruff 和 `git diff --check` 通过。本测试仍只是多进程运动学 UDP 仿真，不是 PX4/Gazebo 物理仿真、HITL 或实飞安全认证。
