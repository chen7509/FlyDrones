# 完整果蝇与 EGO-Swarm 对照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在同一 Gazebo/PX4 环境内，对原版完整果蝇、果蝇加目标引导、上游 EGO-Swarm 单机模式进行 20 场景配对评测，输出可复现证据和中文报告。

**Architecture:** 使用隔离的评测目录和顺序运行方式。场景/评分进程持有真值，控制器只通过观测接口接收 RGB-D、里程计、任务目标和仿真时间。完整果蝇保持全连接组积分，EGO 使用固定上游提交；共同网关统一速度指令、PX4 执行、仿真时间推进、终止和记录。

**Tech Stack:** Windows PowerShell、WSL Ubuntu 24.04、Gazebo Sim 8.15.0、现有 PX4 SITL、Python/NumPy/SciPy/OpenCV/pymavlink、Docker 中 ROS 2 Humble/CycloneDDS、上游 EGO-Swarm、pytest、Matplotlib。

**Spec:** `docs/superpowers/specs/2026-09-22-fly-ego-comparison-design.md`，已批准两种果蝇版本。

## Global Constraints

- 完整果蝇每个决策周期实际执行完整连接组，记录神经元数、连接数、模型哈希与神经积分时间。不使用 MiniFly、PPO 或蒸馏小网络冒充。
- EGO 必须用遮挡正确的深度输入，禁止用无射线遮挡的全局/局部真值点云代替相机。
- 两个控制器在同一世界的独立副本中运行。三种配置意味着每个正式世界运行三次，共 60 架次；EGO 结果在两项配对中复用，不重复跑出更有利的结果。
- 参数冻结后正式失败不得触发针对该场景的调参重赛。
- 若不能验证同步正确，停止正式评测并报告基础设施障碍，不能以普通墙钟运行替代后继续宣称公平。
- 不修改或覆盖现有群飞验收产物。输出独立保存到 results/fly-ego-comparison/ 下，以运行 ID 区分。
- 不对一次飞行结果使用“学得快”的表述。学习速度需要另行设计同预算训练实验。
- 每任务只提交该任务文件，保留既有未提交资产；不使用全目录 git add，不运行既有会批量结束其他实例的启动脚本。
- 实施由当前任务直接执行，最终再做独立审查；不创建新的用户任务。

## Review Focus

1. 暂停仿真时 ROS 墙钟定时器或 PX4 watchdog 仍运行：Task 3 必须检测时钟漂移和失控模式变化，不能用增大超时掩盖。
2. 同一深度帧配上新姿态或左右镜像：Task 4 用带帧时间戳的非对称障碍验证，重复帧不重投影。
3. 中途退出后恢复时把剩余回合当完整报告：Task 8 验证清单覆盖，保留缺失/异常项，不丢弃或自动重赛失败项。
4. 果蝇混合版被引导完全覆盖：Task 5 记录独立输出，测试神经输出改变最终命令，不允许偷偷接 PPO 或地图规划。
5. 两采样点之间穿过细障碍却未碰撞：Task 2/7 验证扫掠包络，所有碰撞优先于同一步抵达。

## 已核对环境与接入选择

- 现有 PX4 提交为 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`；其 Gazebo 子模块有本地改动，冻结时必须保存子模块状态及实际模型哈希。
- EGO ROS2 分支提交：`23a8d5a191711dd65633df689bd00f55d4dea8f9`，来源 `https://github.com/ZJU-FAST-Lab/ego-planner-swarm`。实施时拉取这个固定提交，不自动跟踪新 HEAD。
- 上游 Readme.md 使用 Humble 和 CycloneDDS。WSL 尚无 ROS，Docker 29.4.0 可用，优先以 `ros:humble-ros-base-jammy` 容器构建 EGO，记录解析后的镜像 digest。不要给现有 Ubuntu 强行装 Humble。
- 容器只挂载上游源码、适配器、公共配置和对应运行日志；不挂载场景文件或世界真值。与 WSL 网关通过专用端口交换长度前缀 JSON（图像使用 base64），控制器没有 Gazebo transport 接口。
- 现有 OakD-Lite-Fly 只有深度相机；新增专用 RGB-D 模型，保留旧模型。深度/RGB 同位姿、160×120、10 Hz、水平视场 1.274 rad、near 0.2 m、far 19.1 m。发布给三种控制器的帧均来自这一个虚拟传感器。
- 速度初始上限 0.8 m/s、加速度 1.2 m/s²、yaw_rate 0.6 rad/s、控制周期 0.05 s，开发结束时冻结。场地 24×16×5 m，起点 (-8,0,1.5)、目标 (8,0,1.5)，初始航向朝目标，飞行高度区间 0.5–3.5 m；目标半径 0.6 m、连续保持 1 s、任务时限 120 s。上述是评测设计值，不是既有性能结论。
- 先验证全时钟同步能否成立，再投入批量场景；不能为了得到结果退回自制简化动力学。

## 文件与接口地图

在 `src/flydrones/benchmark/` 新建 `__init__.py`、`contract.py`、`provenance.py`、`worlds.py`、`geometry.py`、`clock.py`、`sensors.py`、`fly.py`、`ego.py`、`gateway.py`、`score.py`、`runner.py`、`report.py`。它们只被新工具使用，既有飞行入口不变。

新增 `configs/fly_ego_benchmark.yaml`；`assets/gazebo/models/x500_benchmark/` 和 `OakD-Benchmark/`；`tools/benchmark/{Dockerfile.ego,ego.launch.py,ego_node.py,bootstrap.sh,run.py,report.py}`；`Start-Fly-Ego-Benchmark.ps1`；测试集中在 `tests/benchmark/`。每个工具的 CLI 在对应任务定义。

数据边界由以下类型定义，三维向量均为米、秒、ENU，yaw 为逆时针弧度；只有发送 MAVLink 前转换为 NED：

```python
@dataclass(frozen=True)
class Observation:
    sim_ns: int
    frame_ns: int
    rgb: np.ndarray          # uint8 H,W,3
    depth_m: np.ndarray      # float32 H,W; NaN means missing
    camera_pose: tuple[float, ...]  # xyz,qx,qy,qz,qw at frame_ns
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    yaw: float
    yaw_rate: float
    goal: tuple[float, float, float]

@dataclass(frozen=True)
class Command:
    velocity_enu: tuple[float, float, float]
    yaw_rate: float

@dataclass(frozen=True)
class Decision:
    command: Command
    elapsed_wall_s: float
    evidence: dict
```

`Controller.reset(seed: int) -> None`、`Controller.step(obs: Observation) -> Decision`、`Controller.close() -> None` 为公共协议。`Decision.evidence` 记录来源与状态，不含真值。评分数据 `ScoreSample` 单独定义且不通过控制器接口传输。

### Task 1: 隔离运行、上游构建与来源记录

**Files:** Create `provenance.py`、`contract.py`、`configs/fly_ego_benchmark.yaml`、`tools/benchmark/Dockerfile.ego`、`tools/benchmark/bootstrap.sh`、`tests/benchmark/test_provenance.py`。

**Interfaces:** `sha256_file(path: Path) -> str`；`freeze_files(paths: list[Path], root: Path) -> dict[str,str]`；`verify_files(manifest: dict[str,str], root: Path) -> None`。后者发现改变时抛 `ValueError`，不存在的文件不能跳过。

- [ ] 先阅读 using-git-worktrees 技能。创建独立 `codex/fly-ego-benchmark` 工作树；从现有目录只复制运行所需 `src/`、`configs/`、`assets/`、完整模型及候选读出等未提交依赖，生成文件哈希清单，保留源目录。基线复制不作为新增实验代码提交。
- [ ] 写入并运行以下失败测试：`python -m pytest tests/benchmark/test_provenance.py -q`。

```python
def test_changed_dependency_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("speed: 0.8")
    frozen = freeze_files([p], tmp_path)
    p.write_text("speed: 1.2")
    with pytest.raises(ValueError):
        verify_files(frozen, tmp_path)
```

- [ ] 实现哈希用 `hashlib.file_digest(stream, "sha256").hexdigest()`，相对路径规范化，禁止 root 外文件；新增配置采用上述固定设计值，启动读取后校验正数、范围和有限值。
- [ ] bootstrap 在 WSL 专用 `~/fly-ego-benchmark/ego_ws/src/ego-planner-swarm` 拉取上游并 detached checkout 固定提交。Dockerfile 基于 Humble，安装 `python3-colcon-common-extensions python3-rosdep ros-humble-rmw-cyclonedds-cpp libarmadillo-dev`，执行 `rosdep install --from-paths src --ignore-src -r -y` 和 `colcon build --symlink-install`。网络/依赖失败原样保存日志；只修构建兼容，不重写规划算法。
- [ ] 执行 `docker build -f tools/benchmark/Dockerfile.ego -t fly-ego-benchmark:humble ~/fly-ego-benchmark/ego_ws`，记录镜像 ID、上游 LICENSE、Git SHA、构建输出、PX4/Gazebo 版本及本地补丁。若上游必须作兼容修改，保存独立 patch 并审查。
- [ ] 重跑 provenance 测试；运行容器中的 `ros2 pkg executables ego_planner`，必须包含 `ego_planner_node` 与 `traj_server`。只提交本任务新文件，消息 `feat: pin benchmark dependencies and provenance`。

### Task 2: 场景几何和确定性生成

**Files:** Create `worlds.py`、`geometry.py`、`tests/benchmark/test_worlds.py`。

**Interfaces:** `generate_world(seed: int, family: str) -> dict` 返回仅评分/生成器可见的 `bounds,start,goal,boxes,cylinders,dynamic,wind`；`write_sdf(world: dict, path: Path) -> None`；`segment_box_clearance(a: np.ndarray, b: np.ndarray, lo: np.ndarray, hi: np.ndarray, radius: float) -> float`；`has_route(world: dict, radius: float) -> bool`。

- [ ] 添加重复种子一致、起终点合法、不可通行拒绝、薄墙穿透四项测试，先运行 `python -m pytest tests/benchmark/test_worlds.py -q` 确认失败。

```python
def test_thin_wall_crossing_is_collision():
    d = segment_box_clearance(np.array([-1.,0.,1.5]),
        np.array([1.,0.,1.5]), np.array([-.01,-1.,0.]),
        np.array([.01,1.,3.]), .25)
    assert d <= 0

def test_seed_is_reproducible():
    assert generate_world(1701, "forest") == generate_world(1701, "forest")
```

- [ ] 使用 `np.random.default_rng(seed)`，先生成静态障碍再一次性生成扰动参数。森林使用圆柱，通道用墙体箱，混合组同时使用二者；第四组增加按仿真时间的横移障碍与有界风场。每种障碍同时生成 visual 和 collision，不能有仅渲染或仅评分的树。
- [ ] 通行检查使用 0.2 m 三维栅格、共同保守机体包络膨胀和 6 邻域 BFS。栅格边与障碍做扫掠检查，禁止角落穿越；最多 100 次确定性候选，无有效场景抛 `ValueError` 并保留所有候选种子。不保存/传递 BFS 路线给控制器。
- [ ] 包围球半径从 X500 全部碰撞几何计算，不能任意沿用 0.25 m；扫掠距离以凸距离最小化计算，圆柱使用线段到有限圆柱距离。保存使用的保守包络及对窄通道的影响。
- [ ] 测试通过后，仅生成三个开发世界：1701 单障碍、1702 通道、1703 混合遮挡；正式集尚不生成。提交 `feat: generate reproducible benchmark worlds`。

### Task 3: 可暂停的 Gazebo/PX4 共同执行网关

**Files:** Create `clock.py`、`gateway.py`、`tests/benchmark/test_clock.py`、`Start-Fly-Ego-Benchmark.ps1`；修改本评测 `bootstrap.sh` 增加独立进程运行目录。

**Interfaces:** `StepClock.accept_time(sim_ns: int) -> None`、`StepClock.next_target() -> int`、`StepClock.assert_paused(before_ns: int, after_ns: int) -> None`；`Gateway.start(world_path: Path) -> None`、`Gateway.observe() -> Observation`、`Gateway.advance(command: Command) -> None`、`Gateway.close() -> None`。

- [ ] 写测试并运行 `python -m pytest tests/benchmark/test_clock.py -q`。

```python
def test_pause_drift_is_not_hidden():
    clock = StepClock(dt_ns=50_000_000)
    clock.accept_time(1_000_000_000)
    assert clock.next_target() == 1_050_000_000
    with pytest.raises(RuntimeError):
        clock.assert_paused(1_000_000_000, 1_010_000_000)
```

- [ ] 使用 Gazebo world control 的 pause/multi_step 服务，基于 world stats 确认达到目标而不是墙钟 sleep。PX4 使用现有锁步 SITL；关掉上游自带动力学仿真。所有 ROS 节点设置 use_sim_time，并核对 C++ 定时器：必要的时钟兼容改动单独记录 patch，不能改变代价函数。
- [ ] 公共速度网关使用 `SET_POSITION_TARGET_LOCAL_NED`，ENU `(x,y,z)` 转 NED `(y,x,-z)`，yaw_rate 取负。速度向量按范数限幅，相邻命令按 `a_max*dt` 限制增量；该规则三种控制器一致。拒绝 NaN/Inf 命令并记控制器异常。
- [ ] 初始起飞/悬停由公共网关完成，模型/滤波器在静态观测下预热后统一开始计分。保持 MAVLink 链路存活不能推进仿真时间；冻结期间不得让 PX4 进入失联模式。
- [ ] 进程 PID/启动时间、容器 ID、端口和 world 名写入运行清单，close 只停止清单中的自有进程。不复用原始群飞脚本的 pkill/rm 清场逻辑。
- [ ] 开发实测：悬停后暂停墙钟 5 秒，验证仿真时钟不前进、PX4 不切换模式；随后固定推进 20 个周期，仿真时间增加 1 秒且传感/里程计一致。失败则记录基础设施障碍并停止正式集。
- [ ] 测试通过提交 `feat: synchronize benchmark flight and simulation clocks`。

### Task 4: 共同 RGB-D 和帧姿态接口

**Files:** Create `sensors.py`、`assets/gazebo/models/OakD-Benchmark/{model.config,model.sdf}`、`assets/gazebo/models/x500_benchmark/{model.config,model.sdf}`、`tests/benchmark/test_sensors.py`。

**Interfaces:** `camera_matrix(width: int, height: int, hfov: float) -> np.ndarray`；`optical_to_body(point: np.ndarray) -> np.ndarray`；`FrameCache.add(frame_ns: int, rgb: np.ndarray, depth_m: np.ndarray, camera_pose: tuple) -> bool`，重复帧返回 False；`encode_observation(obs: Observation) -> bytes` 和 `decode_observation(payload: bytes) -> Observation`。

- [ ] 先测试 optical 右方向映射为机体右、完整二进制图像往返、重复帧拒绝及缺姿态帧拒绝。运行 `python -m pytest tests/benchmark/test_sensors.py -q`。

```python
def test_optical_right_is_body_right():
    assert np.allclose(optical_to_body(np.array([1.,0.,0.])), [0.,-1.,0.])

def test_duplicate_frame_not_reprojected():
    cache = FrameCache()
    rgb = np.zeros((120,160,3), np.uint8)
    depth = np.ones((120,160), np.float32)
    pose = (0.,0.,1.5,0.,0.,0.,1.)
    assert cache.add(100, rgb, depth, pose)
    assert not cache.add(100, rgb, depth, pose)
```

- [ ] 新模型采用 Gazebo RGBD sensor，颜色和深度共享光学中心与时间戳；原始 32FC1 米制输入保持 NaN，避免把无返回误变成零距离。相机内参用 `fx=fy=width/(2*tan(hfov/2))`、`cx=(width-1)/2`、`cy=(height-1)/2`。
- [ ] 观测网关保留姿态历史，使用 frame_ns 对应位姿插值（四元数 SLERP）；不能用接收帧时的当前姿态。开发时提供双方相同的真值里程计并在报告披露；不宣称使用视觉里程计。
- [ ] 注入噪声/丢帧时以场景 seed、frame_ns、像素坐标计算确定性随机值；不使用共享随调用次数变化的随机流。容器协议只允许白名单观测字段，任何 boxes/world/route 字段拒绝。
- [ ] 在非对称开发场景目视检查 RGB、深度与重投影：左侧树保持左侧、后方遮挡物不可见，5 秒暂停不改变姿态配对。保存诊断截图和帧日志。测试通过提交 `feat: provide common timestamped RGB-D observations`。

### Task 5: 两种完整果蝇适配器

**Files:** Create `fly.py`、`tests/benchmark/test_fly_adapter.py`。

**Interfaces:** `FullFlyController(config: dict, model_path: Path, guided: bool)` 实现公共 Controller；`blend_goal(raw: Command, position: tuple, yaw: float, goal: tuple, *, gain: float, limit: float) -> Command`。

- [ ] 测试 raw 不使用目标、混合输出保留神经变化、每周期调用一次完整 brain.tick、reset 清除神经/读出/相机状态。先运行 `python -m pytest tests/benchmark/test_fly_adapter.py -q`。

```python
def test_neural_turn_survives_goal_guidance():
    a = blend_goal(Command((.2,0.,0.), .2), (0.,0.,1.5), 0.,
                   (8.,0.,1.5), gain=.5, limit=.6)
    b = blend_goal(Command((.2,0.,0.), -.2), (0.,0.,1.5), 0.,
                   (8.,0.,1.5), gain=.5, limit=.6)
    assert a.yaw_rate > b.yaw_rate
```

- [ ] 复用 Retina、InputEncoder、Brain、MotorDecoder，加载 forest-trained-v2.yaml 和候选 readout。assert 神经元 166700；关闭外部 VisualAvoidance，不导入 PPO/hybrid_agent/local_planner。预热结束调用 decoder.reset_transients。
- [ ] 每个 50 ms 周期执行 `brain.tick(inputs, ms=50.0)`，RGB 10 Hz 时允许原版视觉处理复用最近帧，记录 frame_age。固定原版状态逻辑；无新帧时不伪造光流。
- [ ] raw 输出按原有轴含义转换成 ENU：forward 沿机头、lateral 正值沿机体右侧、throttle 正值向上、yaw 正值顺时针。归一化尺度取现有 MAVLink 配置并写入冻结表，最终同过公共网关。
- [ ] guided 只增加 `clip(0.5*wrap(target_heading-yaw), -0.6,0.6)` 到神经 yaw 后限幅，速度保留神经输出；不强制正向油门、不恢复障碍路径、不加入地图。目标方向在当前位置定义，不参考真值障碍。保留 `raw/guidance/final/spikes/neuron_count/brain_wall_s` 证据。
- [ ] 运行完整网络至少 10 个周期，保存实际耗时、神经活动和模型哈希；测试通过提交 `feat: adapt full connectome with explicit goal guidance`。

### Task 6: 原版 EGO 节点接入统一网关

**Files:** Create `ego.py`、`tools/benchmark/ego.launch.py`、`tools/benchmark/ego_node.py`、`tests/benchmark/test_ego_adapter.py`。

**Interfaces:** `EgoController(endpoint: str, config: dict)` 实现 Controller；`track_reference(position_ref: tuple, velocity_ref: tuple, position: tuple, yaw_rate: float, gain: float) -> Command`。

- [ ] 测试非法消息/过时轨迹拒绝、ENU 输出与公共限幅一致、发布白名单无 global_cloud。运行 `python -m pytest tests/benchmark/test_ego_adapter.py -q`。

```python
def test_reference_tracking_is_explicit():
    cmd = track_reference((1.,0.,1.5), (.2,0.,0.), (0.,0.,1.5), 0., .5)
    assert np.allclose(cmd.velocity_enu, [.7,0.,0.])
```

- [ ] 上游只启动 `ego_planner_node`、`traj_server`，不启动 map_generator、mockamap、fake_drone、pcl_render。设 drone_id=0、waypoint_num=1、唯一 waypoint 为共同任务终点；不下发中间路点。
- [ ] 向 EGO 发布同一 `/clock`、Odometry、Camera PoseStamped、32FC1 Image 与内参。上游 depth scaling 与实际消息编码核对后配置，禁止把米再错缩放 1000 倍。point cloud topic 不发布。
- [ ] 读取 `drone_0_planning/pos_cmd`，通过 `v_ref + 0.5*(p_ref-p)` 转为速度请求；yaw 按上游参考求误差控制，最终限幅由公共网关处理。这个跟踪器属于 EGO 系统适配，在报告明示。
- [ ] 每个观测序列等待规划处理完成或上游有效轨迹的当前采样；暂停期间不允许墙钟无限重规划。原版紧急停车仍属于 EGO 算法，记录状态而不外加导航。
- [ ] 单障碍场景核对 EGO 确实读取深度并产生绕行轨迹。禁用深度的诊断只在开发集运行，验证其不能偷读世界云。保存 ROS topic graph、节点参数及上游 diff。测试通过提交 `feat: integrate upstream EGO using benchmark observations`。

### Task 7: 独立评分和终止分类

**Files:** Create `score.py`、`tests/benchmark/test_score.py`。

**Interfaces:** `ScoreSample(sim_ns: int, position: tuple, clearance_m: float, contact: bool, in_bounds: bool)`；`EpisodeScorer(goal: tuple, radius: float, hold_s: float, timeout_s: float)`；`EpisodeScorer.update(sample: ScoreSample) -> str | None`；`EpisodeScorer.summary() -> dict`。

- [ ] 测试碰撞优先于抵达、停车超时、进入后离开会重置保持时间、时钟回退拒绝及扫掠接触。运行 `python -m pytest tests/benchmark/test_score.py -q`。

```python
def test_collision_has_priority_over_goal():
    scorer = EpisodeScorer((1.,0.,1.5), .6, 1., 120.)
    assert scorer.update(ScoreSample(0,(1.,0.,1.5),-.01,True,True)) == "collision"
```

- [ ] 终止优先级 `infrastructure_error/controller_error/collision/out_of_bounds/success/timeout`。异常优先级用于确定日志主原因，仍保留所有同时发生事件，不能抹掉碰撞。落地/起飞排除于自主阶段，越界结束计分。
- [ ] 评分从 Gazebo contacts 和扫掠包络联合判断接触；报告接触真值与保守包络结果两列，主碰撞指标取联合结果。动态障碍扫掠使用相对运动。
- [ ] 只对成功回合统计完成时间均值，同时显示成功样本数；全部回合保留路径、最低净空、执行状态、决策耗时分位数，能耗不估算。测试通过提交 `feat: score paired trials without hiding failures`。

### Task 8: 开发、冻结、正式批量运行与恢复

**Files:** Create `runner.py`、`tools/benchmark/run.py`、`tests/benchmark/test_runner.py`。

**Interfaces:** `build_jobs(seeds: list[int], controllers: list[str]) -> list[dict]`；`pending_jobs(jobs: list[dict], records: list[dict]) -> list[dict]`；`run_batch(config_path: Path, phase: str, output: Path, resume: bool) -> dict`。CLI `python tools/benchmark/run.py --phase development|freeze|evaluation --output PATH [--resume]`。

- [ ] 先测试 20×3=60 清单、失败不重排、未完成必须保留，以及无冻结清单禁止评测。运行 `python -m pytest tests/benchmark/test_runner.py -q`。

```python
def test_failed_run_is_not_silently_retried():
    jobs = build_jobs([1701], ["fly_raw", "fly_guided", "ego"])
    records = [{"seed":1701,"controller":"fly_raw","status":"collision"}]
    todo = pending_jobs(jobs, records)
    assert len(todo) == 2
    assert all(j["controller"] != "fly_raw" for j in todo)
```

- [ ] 输出目录通过原子 mkdir 获取独占锁，每回合先写 started.json，再写临时结果并原子 rename；残留 started 无结果标记 interrupted。恢复不覆盖原回合，显式保存 attempt 号和原因。
- [ ] 执行 `--phase development` 共 3×3 回合。先汇总同步/图像/动作来源证据与吞吐估计，再 `--phase freeze`：冻结配置、模型、代码、容器、PX4 资产的哈希清单。
- [ ] freeze 后用 `secrets.randbits(63)` 生成正式主种子并立即保存；SeedSequence 派生 20 个场景种子，按四组每组 5 个分配。派生顺序在清单中固定，不因运行结果变化。
- [ ] 执行 `--phase evaluation`，每场景三个方案轮换顺序以降低热负载影响；任一失败仍执行余下配对。不因碰撞、超时或低分改参数；基础设施错误停止批次并输出诊断，修复后统一标明受影响重跑范围。
- [ ] 正式启动前检查其他任务/系统资源，不结束他人进程。重新启用当前自动化仅用于跟进这一个 batch 状态；不得重复启动。
- [ ] 测试通过提交 `feat: run frozen paired benchmark with resumable evidence`。正式回合原始日志保留在结果目录，不把庞大文件无选择加入 Git。

### Task 9: 对照报告与可核验回放

**Files:** Create `report.py`、`tools/benchmark/report.py`、`tests/benchmark/test_report.py`、`docs/FLY_EGO_BENCHMARK.md`。

**Interfaces:** `paired_summary(records: list[dict], expected_jobs: list[dict]) -> dict`；`write_report(run_dir: Path) -> Path`。CLI `python tools/benchmark/report.py --run PATH`。

- [ ] 写全缺失、混合成功/失败、仿真时间与墙钟时间分离、配对不完整四项测试，运行 `python -m pytest tests/benchmark/test_report.py -q`。

```python
def test_empty_results_never_claim_completion():
    jobs = build_jobs(list(range(20)), ["fly_raw", "fly_guided", "ego"])
    summary = paired_summary([], jobs)
    assert summary["complete"] is False
    assert summary["missing"] == 60
```

- [ ] 生成 report.md、summary.json、episodes.csv、每场景三条轨迹叠图和基于原始轨迹的 HTML 时间滑块回放。回放是记录展示，不重算控制、不插入虚构避障动作；可逐帧查看命令来源和状态。
- [ ] 报告两个配对：fly_raw/ego、fly_guided/ego。显示各自全部 20 回合终态、成功率 Wilson 区间、配对胜负计数；时间比较只在双方均成功的子集中列出并注明选择范围。EGO 不代表全部开源技术水平。
- [ ] 明示原版没有目标输入、混合引导并非学习、真值里程计使用、RGB-D 合成条件、暂停式非实时计算，以及开发调参次数。完整报告必须覆盖 60 项清单；未完成时显著写 incomplete。
- [ ] 运行 `python -m pytest tests/benchmark -q`，检查新增文件 `python -m ruff check src/flydrones/benchmark tests/benchmark tools/benchmark` 和 `python -m compileall -q src/flydrones/benchmark tools/benchmark`；人工核对至少一个成功、一个失败（若有）、一个同步诊断的回放。
- [ ] 按 verification-before-completion 与 requesting-code-review 技能核对证据和改动；只有覆盖完整且基础设施有效才能宣布测试完成。提交报告工具与说明，消息 `docs: report full fly and EGO paired benchmark`，向用户展示真实结果，并关闭该自动化。

## 计划自审

- 覆盖：来源/隔离 Task 1；几何/陌生场景 Task 2/8；共同物理/时钟 Task 3；共同观测 Task 4；三控制器与归因 Task 5/6；评分 Task 7；完整样本与恢复 Task 8；证据/限制 Task 9。
- 公共输入输出仅 Observation/Command/Decision，评分样本单独持有；未知空间、障碍数据不在控制器接口中。
- 五项 Review Focus 均已对应具体测试和开发期实测。
- 正式种子尚未生成，上游尚未安装，未作任何性能/优劣结论。

## 执行审阅

建议由当前任务直接按顺序执行：任务主要依赖同一物理仿真与接口，逐项验证可避免共享资源冲突。用户审阅本计划后开始实施；自动化当前仍暂停，不会在审阅前启动飞行。
