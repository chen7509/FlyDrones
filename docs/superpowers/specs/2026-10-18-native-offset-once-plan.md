# openvins_offset_reset_v2 一次运行准备范围

用户本轮要求：补齐当前源码、构建配方、依赖闭包、预算和停止条件，形成可审查方案；不编译、不运行原生程序、不刷新资源、不重跑旧测试、不降门槛。

交付包括当前本地源码快照、固定 OpenVINS 提交的构建源输入、静态依赖清单及未绑定项、精确构建/生产捕获 argv 模板、一次性状态转换、原预算及故障停止/证据要求。方案必须明确区分已经取得的源码、未取得的工具/库/运行配置实物、以及未发生的构建和运行结果。

只允许修正本轮静态发现的构建标准冲突：适配器包含 std::filesystem，独立目标要求 C++17；不改旧 native/header/NativeClient，不改上游源、算法、标定值、offset、质量、协方差或安全限制。当前方案只覆盖一个固定非零 offset 的新进程和禁用 EV 的未解锁接收；不能承诺覆盖两种符号或实际 reset。

沿同工作树/分支/personal draft PR65。旧报告/raw/review/ZIP/map 不改；goal blocked 只读、automation ACTIVE。原历史 UNKNOWN/CONSUMED/缺 payload/DL-M1/AV/recorder gap、truth 仅 score/abort、pidfd fail-closed、原 sensor/precision/speed/RTF/once/cleanup 和后续完整目标均继承。本交付不是运行准入、源认证或编译/ABI/融合/飞行证明。
