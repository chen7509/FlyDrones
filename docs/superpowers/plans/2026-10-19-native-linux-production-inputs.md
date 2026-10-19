# Linux生产源码、toolchain与命名输入绑定执行计划

> **For agentic workers:** Use superpowers:executing-plans inline. 用户已明确要求继续补齐三项，先不编译或运行；在此范围内执行，不再索取相同授权。没有源码行为修改或旧测试复跑。

**Goal:** 取得Linux实际可见生产源码及toolchain文件身份，并把已保存和本次补齐的命名输入整理为可核查闭包回执；任何无法静态证明的消费或递归缺项明列，不伪授准入。

**Architecture:** WSL读取同一工作树的`/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility`路径，避免复制生产代码。Windows静态追踪当前根入口的本地Python imports与C++显式源，生成独立toolchain文本；分开冻结生产源码选择、尚缺内容/当前哈希的已知依赖选择和最后新生成回执的回读选择，各执行一次隔离标准库文件观察，不分批逃逸某次触限。记录每个输入的phase和时间，保留跨时点、动态导入、CMake及ELF无法解析项。

**Tech Stack:** Python标准库静态AST/JSON/ELF字节解析、CMake toolchain文本（不执行）、WSL只读文件观察。

**Spec:** 用户“继续按顺序补齐Linux生产源码绑定、toolchain回执和完整输入闭包，先不编译或运行”，现有native_offset_once的BUILD_KEYS/143manifest及上一阶段missing-evidence。

## Global Constraints

- 原分支/personal/PR65，旧生产源码、143清单、45bindings/准入模板、旧证据不改。所有资格/dispatch false，goal blocked，automation ACTIVE。
- 不configure/compiler/link/native/SDK/tests/资源查询/网络/安装，不创建原once attempt。仅Windows保存新文件，Linux观察器不写文件。
- 每次file67108864B/total201326592B/read27s（首metadata10s在27内）/parent30+5term+5kill/outer45s/metadata-stderr各2097152B/40linkhops/最多6000paths，任一触限停止整项，不补批/重排/扩限/换folderretry。
- 新授权覆盖上述三项必要只读绑定和新toolchain/回执准备，不外推为重采所有历史、旧库对象日志来源审计、native准入或资源刷新。
- 已完整阅读继承历史的coverage沿本对话前次实际完整读取；不冒新history/native审。

## Review Focus

1. WSL实际路径和Windows预期字节有差异时停止，不复制或normalize生产代码。
2. AST仅静态可见，动态导入/外部包/旧条件分支不执行；无法归入闭包时明确保留未知。
3. toolchain是声明的编译器/sysroot/搜索根文本；实际driver选择与CMake消费只有未来已准入构建能证明。
4. 依赖内容只选保存索引已知精确路径；别名/未知resolved目标/大小或时间metadata触限停止，不目录扩搜或填满上限。
5. 新回执文件最终实际Linux回读与生成阶段分开；命名组都有文件不等于真实隐式/loader闭包已经认证。

## 顺序与交付

- [x] 在新results/native-linux-production-inputs-20261019保存用户授权、静态源码图、生产选择、toolchain文本、执行ledger。必要source roots含现有12必需源码/CMake及capture生产可见imports；不执行imports。
- [x] 一次Linux只读观察生产文件及toolchain，逐个绑定实际path/resolved/bytes/SHA/identity并比对Windows预期；保存current_linux_source_manifest。
- [x] 仅从既存精确依赖索引补齐尚无内容/当前内容哈希的必要已知文件；复用已完整Linux观察pin时逐项标明phase/非fresh，不重采已有新头/五组件/143源码冒进展。
- [x] 静态整理tools/system_headers/cmake_modules/link_implicit/libraries/packages六命名组，给出可证明的覆盖、具体未解析CMake/ELF/Python输入和完整性判定；toolchain_receipt绑定实际观察，不捏造执行/版本/ABI。
- [x] 一次回读新生成source-manifest/toolchain-receipt/closure回执文件，保持生成与观察边界；不把这些声明当认证或build许可。
- [x] 新JSON一致性、helperAST、新ZIPCRC/memberSHA及必要diffcheck后仅personal发布，旧封存不动。若真正全闭包无法静态闭合，交付具体缺项与下一步，不把部分成功称完整。

实际执行已完成上述准备、观察和缺项交付；不是完整消费闭包完成。最终以final-v3及final-receipt-bindings为准，full_input_closure_complete仍false。新引用共12次观察，累计payload/metadata/read时间均在原预算内；没有构建或运行。
