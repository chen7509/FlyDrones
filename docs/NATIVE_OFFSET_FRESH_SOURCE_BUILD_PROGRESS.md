# 固定源码 OpenVINS → offset-reset-v2：软件接入

2026-10-19。本轮用户授权修改既有一次构建入口、回执、预算及失败清理；没有授权或执行 configure、编译、链接、原生程序、WSL、SDK、资源刷新、旧证据核验或旧测试。此文不替代原生准入。

## 实际改动

- `native_offset_once.py` 改用 `native-offset-fresh-source-request-v1` / `native-offset-fresh-source-admission-v1` 与 `build_profile=fixed-source-openvins-v1`。旧请求/旧审查协议不能用于这条路线。构建阶段不再要求预先有库输出或旧库来源/ABI回执；旧库 file/dir/receipt bindings 明确拒绝。
- 继续要求固定上游 commit `69488123ed9362dd44b6f28e7f4680abbff1442b` 的原143文件清单与未来当前实物 pins 对应、当前生产源码及工具/头/包/库闭包、新适用审查。没有用保存的32对象构建或推断旧库来源。
- `native_offset_fresh_build.py` 显式列出原 NO_ROS 库34个编译单元。受管 scope 在独占构建目录生成一次 `openvins-fixed-sources.cmake`，不 glob、不安装依赖、不运行上游的 ROS 探测或 O3/g3 配方、不更改上游文件。
- 现有 CMake 入口创建新的 `ov_msckf_lib` shared target；固定 C++17/O2、ROS_AVAILABLE=0、ENABLE_ARUCO_TAGS=0、OpenCV4。适配器链接该 target，不能 `find_library` 回退旧 OpenVINS 库。其他依赖仍必须通过未来的完整当前闭包准入。
- 同一 scope、同一输出目录、同一300秒总预算内依次运行 configure → ov_msckf_lib → openvins_offset_reset_v2。新库成功且文件 pin 在原64MiB上限内后才允许适配器阶段；适配器之后再次比对这份新库，变化即拒绝。
- 每个子步骤仍保留 stdout/stderr、start/return、owned cleanup。任一步退出失败、清理结果未知、库超限或共享预算耗尽，不进入后续步骤；attempt 保持原 consumed 语义，不能重开或换目录重试。

## 新构建回执和运行边界

新 `native_offset_fresh_receipt.py` 由原 `produce()` 入口实际调用。要求35份唯一编译记录（34库+1适配器），每份绑定所选源码、工具、C++17/O2/NO_ROS命令、新对象及含系统头的 depfile；配置 trace 与显式 response/linker-script 输入保留在原界内。

分别记录新库与适配器的 link argv、对象覆盖及输出 pin；适配器必须消费本次新库，且新库必须与适配器启动前的 checkpoint 相同。输入前后、生成证据前后变化拒绝完整性。这里只观察配方、依赖文件、进程退出和产物字节，不证明编译器全部隐含 syscall 输入、ABI、加载闭包或真实性认证。

新 schema 为 `native-offset-fresh-source-build-receipt-v1`。`complete` 只是本次记录一致性；`native_qualified`、`runtime_closure_qualified`、`abi_verified`、`historical_old_library_proven` 均为 false。运行阶段还必须独立满足完整构建回执、inside/host 成功退出及释放、新库和适配器当前 pin，以及包含新库的 ELF closure、原实测标定/noise、runtime/wire/source/clock 等全部原门槛。原库ABI前提改为构建后、运行前的 `new_library_abi_receipt`：schema `native-offset-new-library-abi-v1`，须声明 abi_verified=true，精确绑定新 library/binary/build_receipt 和当前 file_pins，并由未来适用准入检查其真实依据；不能用本次构建的 complete 自动补出ABI。缺该回执即拒绝，软件fixture不提供真实ABI。不自动 build→run，不发送 PARAM_SET/ARM/EV-enable/control。

## 原上限保持

- 同一固定 `results/native-offset-once-attempt-v1/build|run`，不创建用于绕过失败的新 attempt 名称。已有 terminal/consumed/UNKNOWN 不重开。
- 双4GiB资源门槛不变；本轮没有刷新资源或判断本机可执行。
- build MemoryMax=1GiB、swap=0、CPU=100%、TasksMax=64；parallel=1，configure/两次build/回执共享300秒，原 scope/outer 限制不变。加入新库工作量没有增加可用预算，能否完成尚未知。
- 单文件64MiB、partial output inventory 512项/64MiB、response 深度4/65536 tokens、显式文本单项1MiB/累计4MiB不变。预算耗尽保留最小 incomplete receipt；同步文件系统/解析仍没有 hard-cancel 证明。
- 不 strip、不分块拼回、不扩大 cap；新产物若不满足上限就失败关闭，也不替换旧库。

## 软件验证范围

只运行新增 `tests/benchmark/test_native_offset_fresh_build.py`。原生进程、网络和资源入口使用拒绝边界；scope 用受控进程/cgroup/时钟协议替身验证编排，ELF/工具/源码仅为明确标注的 inert fixtures。没有运行旧测试、CMake、compiler、SDK 或真实 cgroup。

原始软件输出在 `results/native-offset-fresh-source-20261019/`。首轮14个失败包含尚缺新接口，不能全部称为行为RED；第一次实现14 pass/1 fixture断言错误（pytest目录名中含test_）；纠正fixture后26 pass。另有2个真实行为RED暴露未拒绝缺库checkpoint、冲突ROS宏，随后修复。受控scope的7个用例直接覆盖顺序、共享预算及失败清理，不冒充真实线程/原生行为或RED。

本轮结果不能授予实际构建、ABI、传播、PX4接收、正融合、RTF或单机飞行资格。旧库来源与当前完整 SHA/ELF/ABI仍未知；原32/34证据及其所有历史结论保持原样。总体资格、runtime_graph_frozen、physical_dispatch_ready、dispatch仍为false，goal保持blocked只读。

唯一源码审查记录 C0/I3/M0；原等级与“尚未进行原生验证”的结论保留。一次有界 executor fix 修复原pin别名消费、重验耗尽预算后的dispatch以及输出清单先全量遍历三个问题。3项均有新软件行为RED（3 failed/33 deselected），修复后3 pass/33 deselected；无第二次源码审查或原生批准。同轮自查补回构建后、运行前新库ABI门槛，`abi-red.txt` 保留1个真实门槛行为RED（当时先报缺capture输入，未显式要求新库ABI）；补齐后最终新增37项通过，38.72秒、无pytest warning（`final-abi.txt`）。Ruff通过（`ruff.txt`）；Git原CRLF转换提示保留，不声称无Git warning。

本轮发布源码、新测试、上述说明、审查/处置和原始测试输出；各轮隔离fixture目录留在本地新results目录，未全量打包或声称已发布完整fixture/environment/FFI闭包。旧raw/report/ZIP/map均未修改或重验。

新结果目录的 `.gitattributes` 仅对本目录txt关闭换行转换。全staged diff-check会报告pytest原始失败输出的空白行尾空格，原样保留；源码/测试/文档的独立diff-check无该问题。不清洗失败日志以制造全diff无告警。

下一真实执行仍需新增授权及完整新输入、预算可行性和唯一适用准入；当前软件交付不是执行批准。
