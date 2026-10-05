# OpenVINS 板面粗块纹理单变量开发试验

## 目标与依据

PR #29 的固定输入已证明预解锁每帧新返回的 13 条候选记录全部在边界带，无法补足 15/15 半窗门槛。当前 512×512 随机细纹理在实际 160×120 相机中只投影成约 36×60 像素的板面。本阶段只改变两块现有板的 albedo 贴图，检验真实渲染的内区视觉内容能否改善持续跟踪；不更改板几何、碰撞、相机、估计器或控制策略。

考虑三种方案：改变板面纹理、移动/改变板几何、提高相机分辨率。采用第一项，因为其物理与图像负载变化最小且可隔离验证；几何方案会改变通道，分辨率方案会增加已经受限的 WSL2 负载，暂不采用。人工图案是接口开发资产，不代表陌生自然环境泛化，也不进入 20 个封存场景。

## 开源调研与复用

继续使用 Apache-2.0 的 [Gazebo Sim](https://github.com/gazebosim/gz-sim) 8.15.0 和已安装的 Ogre2 渲染路径；2026-10-05 GitHub 核查仓库未归档且当日仍有推送。[Gazebo 的材质加载代码](https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/rendering/SceneManager.cc)和 [PBR API](https://gazebosim.org/api/common/7/classgz_1_1common_1_1Pbr.html)定义 albedo 贴图接口。继续使用 Pillow 12.0.0（本地许可证 MIT-CMU；GitHub 许可证检测为 NOASSERTION，不能以此替代本地 LICENSE）生成确定性 PNG，不增加依赖。OpenVINS 沿用 GPL-3.0 固定提交 `69488123ed9362dd44b6f28e7f4680abbff1442b` 及原配置，算法依据为 [ICRA 2020 论文](https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf)与 [Grider_GRID 官方文档](https://docs.openvins.com/classov__core_1_1Grider__GRID.html)。不引入替代前端，不混合 GPL 源码到 MIT 飞行栈。贴图生成成本很小；静态探针需要一个 Gazebo 渲染实例；实际采集沿用慢速、决策间暂停的单机物理仿真，不能称机载实时。

## 设计

从 PR #25 的 `fixture-v2` 复制独立派生场景，校验来源 manifest 和全部源文件哈希。世界 JSON、ground/obstacle albedo 字节不变；SDF 只允许 `wall_0`、`wall_1` 的 `visual/material/pbr/metal/albedo_map` 改为 `board_albedo.png`。用移除这两处 URI 后的规范化 XML 哈希证明其他 SDF 内容不变。新贴图为 512×512、背景灰度24，六块白色矩形的中心 x=128/384，y=112/280/424，宽112高96，灰度按固定顺序 232/208 交替。图案在运行前冻结，不因单帧或测试结果静默调参。

生成器拒绝已存在、篡改或不完整输入/输出；写出失败保留 `INCOMPLETE.json`。真实采集器只增加显式可选的 `board_albedo.png` 复制与哈希记录，源文件缺失/符号链接必须拒绝；旧两张贴图行为保留。

先创建相同相机/机体/起点的基线与变体静态 Gazebo 探针，各采一张实际 RGB 和相机位姿。保存原始图像、SDF/模型版本和日志；在同一 OpenCV FAST-20 设置下统计整体及距边界10像素内区的角点，仅作为采集筛选。变体相机位姿与基线一致、图像确实改变且内区 FAST 点至少15时，才运行一次带4秒预解锁静止窗口的完整果蝇 PX4/Gazebo开发采集；否则保留失败并诊断渲染，不用静态计数宣称VIO通过。

实际采集后核对 RGB/相机信息/ULog、时间/内参/版本，再用冻结 OpenVINS 回放。预解锁 15/15 半窗持续轨迹、静止初始化时间、MSCKF 视觉更新、ATE和实际延迟分别报告。控制器失败（包括越界）仍保留为失败，VIO 输出仍处于离线评估，不得宣称已进入 EKF2。只有离线 VIO 证据合格后才设计健康门禁和在线融合。
