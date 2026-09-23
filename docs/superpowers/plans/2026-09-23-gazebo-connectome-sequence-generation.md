# Gazebo 连接组课程序列生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This branch has unrelated dirty files; inspect the target path before every edit and commit only the task's named files.

**Goal:** 从独立开发世界采集可封存的六阶段 PX4/Gazebo RGB-D 与 EGO-Swarm 教师序列，并完成完整 MaleCNS 的实测单批训练门检。

**Architecture:** 复用现有 `Gateway`、`NativeGazeboPx4Backend`、`EgoController` 和 `TeacherSequenceRecorder`。新增语料配置、世界适配、采集会话、数据集封存与验证；训练入口只接受封存的 v2 数据集。采集进程串行运行，仿真全部退出后再启动离线完整模型门检。

**Tech Stack:** Python 3、PyYAML、NumPy、SciPy、PyTorch、pytest、WSL Ubuntu、Gazebo Sim 8、PX4 SITL、Docker 中固定 EGO-Swarm 镜像。

**Spec:** `docs/superpowers/specs/2026-09-23-gazebo-connectome-sequence-generation-design.md`

## Global Constraints

- 正式冻结封印 `9d10bb72c1fda4048f0439c9dfb823583d8464a8491349f9e732e9cced87d937` 及其二十场世界不可用于课程。
- 学生输入仅含现有 `Observation` 的 RGB、深度、帧时间、位置、速度、航向、角速度和目标。
- 完整候选必须使用 166,700 神经元、25,582,837 条连接及正式映射的 `ConnectomeConstrainedCore`。
- 统一使用 `configs/fly_ego_benchmark.yaml` 中的 50 ms 控制步长、0.8 m/s 速度上限、1.2 m/s² 加速度上限、0.6 rad/s 偏航角速度上限和 160×120、10 Hz RGB-D。
- 上游 EGO-Swarm 提交 `23a8d5a191711dd65633df689bd00f55d4dea8f9`；实际镜像 ID 要与冻结依赖清单及本地 `docker image inspect` 一致。
- 三个开发场景使用 1701、1702、1703。每个正式阶段至少六条训练回放、三条验证回放；训练与验证世界种子互斥。
- v1 smoke 的配置、结果与恢复身份保持原样；真实语料使用 v2 配置和独立目录。
- 采集与训练不并行；资源残留或身份不匹配时停止，不自动降低模型规模。

## Review Focus

- 恶意或误选的正式场景路径、种子或相同世界内容：配置校验和封存校验必须拒绝，即使目录名被改掉。
- 序列末尾缺少未来教师参考点：有效位只覆盖实际观测到的点，损失不得读取无效点。
- RGB-D 帧延迟、丢失或时间倒流：只能写入时间一致的样本，失败回放保留诊断。
- PX4/Gazebo/EGO 某一个进程未退出：只处理本会话记录的进程，停止后续采集并报告身份。
- 中断发生在序列写入或根清单更新之间：恢复时仅承认已回读且哈希正确的序列，不能重复覆盖或误封存。

## File Map

- `src/flydrones/connectome_training/corpus_config.py`：v2 语料配置、正式世界排除和身份校验。
- `configs/connectome_corpus_v2.yaml`：六阶段、回放种子、资源与扰动声明。
- `src/flydrones/connectome_training/corpus_worlds.py`：六阶段世界构造及可通行性检查。
- `src/flydrones/connectome_training/dataset.py`：兼容 v1 的 v2 教师轨迹有效位。
- `src/flydrones/connectome_training/recorder.py`：从连续 EGO 参考点完成离线轨迹标签。
- `src/flydrones/connectome_training/capture.py`：单回放采集、质量门槛、错误记录。
- `src/flydrones/connectome_training/corpus.py`：回放队列、原子提交、恢复与数据集封存。
- `src/flydrones/connectome_training/process_ownership.py`：仅管理采集会话创建的 EGO 容器和子进程。
- `tools/connectome_training/capture_sequence.py`：WSL 单回放命令入口。
- `tools/connectome_training/generate_corpus.py`：WSL 串行语料生成和验证入口。
- `src/flydrones/connectome_training/curriculum_config.py`、`curriculum_session.py`：解析 v2 封存字段并在加载前校验身份。
- `configs/connectome_curriculum_v2.yaml`：真实语料路径和完整模型训练档。
- `tools/connectome_training/profile_full_batch.py`：完整 MaleCNS 单批实测门检。
- `docs/CONNECTOME_TRAINING.md`：生成、校验、门检和恢复命令。
- 对应 `tests/connectome_training/test_corpus_*.py`：配置、世界、轨迹、会话、封存及门检测试。

## Task 1: 语料配置与正式证据排除

**Files:** Create `src/flydrones/connectome_training/corpus_config.py`, `configs/connectome_corpus_v2.yaml`, `tests/connectome_training/test_corpus_config.py`.

**Interfaces:** `load_corpus_config(path: Path, *, formal_manifest: Path) -> CorpusConfig`；`CorpusConfig.jobs(split: str | None = None) -> tuple[CorpusJob, ...]`；`CorpusJob(stage_id, split, world_seed, rollout_seed, ordinal)`。配置摘要由规范化配置、冻结正式清单摘要和教师身份共同生成。

- [ ] **Step 1: Write failing tests.** 用临时 YAML 和正式 `seed_manifest.json`，断言 1701/1702/1703、正式种子、重复世界种子、空回放集及错误输出根目录被拒绝；正常配置生成每阶段 2×3 条训练和 1×3 条验证任务。

```python
config = load_corpus_config(tmp_path / "corpus.yaml", formal_manifest=formal)
jobs = config.jobs()
assert len([j for j in jobs if j.stage_id == "forest" and j.split == "train"]) == 6
assert set(j.world_seed for j in jobs if j.split == "train").isdisjoint(
    j.world_seed for j in jobs if j.split == "val"
)
```

- [ ] **Step 2: Run red.** `python -m pytest tests/connectome_training/test_corpus_config.py -q`；预期导入失败或校验测试失败。
- [ ] **Step 3: Implement.** 使用 `yaml.safe_load`、严格字段集、`Path.resolve()` 后的目录包含检查，以及正式 `seed_manifest.json` 的 `verify_sealed_manifest` 和 `world_json_sha256` 集合。配置中声明六阶段原 v1 种子、每种子三个 `rollout_seed`、基准机体和相机配置的 SHA-256、EGO 提交与镜像 ID、回放上限和允许终止类型。配置摘要为排序 JSON 的 SHA-256。
- [ ] **Step 4: Run green.** 同一步 2；预期全部通过。再运行 `python -m pytest tests/connectome_training/test_curriculum_config.py -q` 防止 v1 配置回归。
- [ ] **Step 5: Commit.** 只暂存本任务三个文件，提交 `feat: define isolated connectome corpus`。

## Task 2: 六阶段确定性世界

**Files:** Create `src/flydrones/connectome_training/corpus_worlds.py`, `tests/connectome_training/test_corpus_worlds.py`.

**Interfaces:** `build_corpus_world(job: CorpusJob) -> dict`；`write_corpus_world(job: CorpusJob, directory: Path) -> tuple[Path, Path, str]`。输出复用 `benchmark.worlds.write_sdf()` 所需的世界字典字段。

- [ ] **Step 1: Write failing tests.** 为六个阶段各取一个训练种子，断言同一任务重复生成的排序 JSON 哈希相同、`has_route(world, vehicle_envelope_radius_m)` 为真、动态障碍不永久堵住路线、`stability` 无近障碍，以及 `disturbance` 含风和非零传感器扰动声明。

```python
a = build_corpus_world(job)
b = build_corpus_world(job)
assert a == b
assert has_route(a, a["vehicle_envelope_radius_m"])
```

- [ ] **Step 2: Run red.** `python -m pytest tests/connectome_training/test_corpus_worlds.py -q`。
- [ ] **Step 3: Implement.** 复用 `benchmark.worlds.generate_world`、`generate_development_world`、`has_route`、`write_sdf`。`stability` 和 `looming` 建立明确的较简单世界；`corridor`、`forest`、`dynamic`、`disturbance` 由现有族和固定种子生成，扰动参数另存世界元数据。动态障碍按一个完整周期采样检查可通行窗口；失败按确定性候选序号重试，有上限。
- [ ] **Step 4: Run green.** 同一步 2，并运行 `python -m pytest tests/benchmark/test_worlds.py -q`。
- [ ] **Step 5: Commit.** 提交 `feat: generate connectome curriculum worlds`。

## Task 3: 真实教师参考轨迹与有效位

**Files:** Modify `src/flydrones/connectome_training/dataset.py`, `src/flydrones/connectome_training/recorder.py`; create `tests/connectome_training/test_corpus_horizon.py`.

**Interfaces:** `TeacherTarget.horizon_valid: np.ndarray | None = None`；`TeacherSequenceRecorder.finish_with_reference_horizon(path: Path, *, points: int) -> Path`。v2 序列使用 `flydrones-connectome-sequence-v2`，v1 加载继续返回全真有效位。

- [ ] **Step 1: Write failing tests.** 三个参考点、窗口长度四时，第一帧有效位为 `[1,1,1,0]`，最后一帧为 `[1,0,0,0]`；v2 回读保留掩码；v1 fixture 仍可加载；非有限参考点和未来伪填充被拒绝。

```python
sequence = load_sequence(out)
assert sequence.targets[-1].horizon_valid.tolist() == [True, False, False, False]
assert sequence.targets[-1].horizon_enu.shape == (4, 3)
```

- [ ] **Step 2: Run red.** `python -m pytest tests/connectome_training/test_corpus_horizon.py -q`。
- [ ] **Step 3: Implement.** 在录制期间保存每次 `decision.evidence["reference"]["position_ref"]`；回放结束后按采样索引切出真实未来参考点，缺位保持有限零占位并用布尔掩码标记无效。有显式 `horizon_valid` 时写 v2 与 `teacher_horizon_valid`；原有调用仍写逐字节兼容的 v1 schema。加载时按 schema 校验键集合；v1 加载时合成全真掩码。现有 `sequence_tensors` 只读取速度、偏航和净空，仍不读取未来轨迹或无效位。
- [ ] **Step 4: Run green.** 同一步 2，并运行 `python -m pytest tests/connectome_training/test_dataset.py tests/connectome_training/test_recorder.py tests/connectome_training/test_trainer.py -q`。
- [ ] **Step 5: Commit.** 提交 `feat: record masked ego reference horizons`。

## Task 4: 单回放采集与进程所有权

**Files:** Create `src/flydrones/connectome_training/capture.py`, `src/flydrones/connectome_training/process_ownership.py`, `tools/connectome_training/capture_sequence.py`, `tests/connectome_training/test_corpus_capture.py`.

**Interfaces:** `capture_job(job: CorpusJob, config: CorpusConfig, output: Path, *, gateway_factory, ego_factory) -> CaptureResult`；`OwnedSession` 管理本次创建的 EGO Docker 容器、WSL 采集进程和现有 `Gateway.close()`；`CaptureResult(status, sequence_path, diagnostics_path, resource_evidence)`。

- [ ] **Step 1: Write failing tests.** 假网关和假教师覆盖：同步 RGB-D 正常写入、过期帧拒绝、教师超时拒绝、碰撞仅在配置许可时写入、`Gateway` 的公共速度/加速度限制生效、关闭只作用于登记的进程 ID、残留时停止队列。

```python
result = capture_job(job, config, out, gateway_factory=fake_gateway, ego_factory=fake_ego)
assert result.status == "complete"
assert result.resource_evidence["all_owned_processes_exited"] is True
assert load_sequence(result.sequence_path).frames[0].rgb.shape == (120, 160, 3)
```

- [ ] **Step 2: Run red.** `python -m pytest tests/connectome_training/test_corpus_capture.py -q`。
- [ ] **Step 3: Implement.** 单回放照 `tools/benchmark/run_episode.py` 顺序调用 `Gateway.start/observe/advance/close`、`EgoController.reset/step/close`、`EpisodeScorer.update` 和 `backend.score_sample()`；记录教师实际墙钟时间、命令、安全投影、净空与终止原因。EGO 容器按独立名称启动并核对镜像 ID；进程拥有者记录容器 ID、子进程 PID、启动时间与退出状态；仅对记录的活进程执行停止。未产生有效序列时保存结构化错误和日志路径。
- [ ] **Step 4: Run green.** 同一步 2，并运行 `python -m pytest tests/benchmark/test_runner.py tests/benchmark/test_ego_adapter.py -q`。
- [ ] **Step 5: Commit.** 提交 `feat: capture owned px4 gazebo ego curriculum rollout`。

## Task 5: 原子语料提交、恢复与封存

**Files:** Create `src/flydrones/connectome_training/corpus.py`, `tools/connectome_training/generate_corpus.py`, `tests/connectome_training/test_corpus_seal.py`.

**Interfaces:** `run_corpus(config: CorpusConfig, root: Path, *, max_jobs: int | None = None) -> CorpusState`；`verify_corpus_seal(root: Path, config: CorpusConfig) -> dict`。根清单文件名为 `dataset_manifest.json`，以免 `_sequence_directories()` 把它识别为训练序列。

- [ ] **Step 1: Write failing tests.** 临时目录模拟：一个作业成功后中断可恢复；`.writing` 目录和半写根清单不算完成；重复运行不覆盖；修改 `samples.npz`、替换世界内容或加入正式世界哈希会拒绝封存；失败作业有诊断但不在训练目录；全部 54 条回放成功后封存。（六阶段 × 每阶段九条。）

```python
state = run_corpus(config, root, max_jobs=1)
assert state.completed == 1
assert not (root / "dataset_manifest.json").exists()
state = run_corpus(config, root)
assert state.completed == 54
assert verify_corpus_seal(root, config)["schema"] == "flydrones-connectome-corpus-v2"
```

- [ ] **Step 2: Run red.** `python -m pytest tests/connectome_training/test_corpus_seal.py -q`。
- [ ] **Step 3: Implement.** 每个作业单独输入快照和诊断目录；序列由 `write_sequence` 原子提交。`run_corpus` 按确定性任务顺序逐个执行，启动前验证先前文件哈希，写状态时使用同目录临时文件加原子替换；全部预期序列完成且跨 split 的种子和世界哈希互斥后写带哈希的封存清单。正式 seed manifest 的世界哈希集合必须逐条排除。封存后调用只读 `verify_corpus_seal`。
- [ ] **Step 4: Run green.** 同一步 2，并运行 `python -m pytest tests/connectome_training/test_governance.py -q`。
- [ ] **Step 5: Commit.** 提交 `feat: seal resumable connectome corpus`。

## Task 6: 三个开发场景接入和 v2 课程绑定

**Files:** Create `configs/connectome_curriculum_v2.yaml`, `tests/connectome_training/test_corpus_curriculum.py`; modify `src/flydrones/connectome_training/curriculum_config.py`, `src/flydrones/connectome_training/curriculum_session.py`, `docs/CONNECTOME_TRAINING.md`.

**Interfaces:** `_full_components()` 在读取 v2 路径前调用 `verify_corpus_seal()`；v2 配置绑定数据集封存摘要。v1 路径仍按旧行为读取，以保留 smoke 证据。

- [ ] **Step 1: Write failing tests.** 使用小型封存 fixture 检查 v2 加载成功、未封存与被篡改目录失败、v1 smoke 仍可运行。三个开发场景只产生 `development/1701..1703` 产物，不进入 `train` 或 `val`。

```python
with pytest.raises(ValueError, match="seal"):
    ConnectomeCurriculumSession(unsealed_v2_config, connectome_path=male_cns, parameters_path=params)
```

- [ ] **Step 2: Run red.** `python -m pytest tests/connectome_training/test_corpus_curriculum.py -q`。
- [ ] **Step 3: Implement.** v2 YAML 保持现有课程配置 schema，增加可选 `dataset_manifest_path`/`dataset_manifest_sha256`，两字段必须同时存在且进入配置 digest；v1 未声明时沿用原加载路径。v2 在 `_full_components()` 读取任何序列前校验根封印及摘要。文档给出 WSL 开发验证命令 `python tools/connectome_training/generate_corpus.py --config configs/connectome_corpus_v2.yaml --development-only --max-jobs 3`、六阶段生成和 Windows 离线训练命令。实际运行三场并审查相机时间、教师时延和资源释放证据，之后才冻结 v2 参数与生成器提交。
- [ ] **Step 4: Run green.** 同一步 2，加 `python -m pytest tests/connectome_training/test_curriculum_config.py tests/connectome_training/test_curriculum_cli.py -q`；人工核对三场报告全部通过，否则停在开发阶段修复。
- [ ] **Step 5: Commit.** 提交 `feat: bind sealed corpus to complete connectome curriculum`，仅在三场接入通过后继续下一任务。

## Task 7: 六阶段真实采集与数据审计

**Files:** Create `results/connectome-training/sequences/v2/dataset_manifest.json` 及 `results/connectome-training/sequences/v2/development_report.json`；大型序列、日志和检查点保留本地并由目录 `.gitignore` 排除。

**Interfaces:** `python tools/connectome_training/generate_corpus.py --config configs/connectome_corpus_v2.yaml --output results/connectome-training/sequences/v2`；`--verify-only` 只读封存校验；`--max-jobs N` 支持安全分段运行。

- [ ] **Step 1: Before running.** 校验 EGO 上游提交/镜像 ID、PX4/Gazebo 版本、正式封印、空闲端口、磁盘空间和三场开发报告；任一不符则失败关闭。调用 `--max-jobs 1` 观察首个正式作业的样本、墙钟、磁盘增长和资源退出。
- [ ] **Step 2: Resume sequentially.** 逐批运行 `--max-jobs N`，每批都从已提交状态恢复；记录每个失败作业，不能删除失败记录或暗中换种子。出现资源残留立即停止并精确定位本会话进程。
- [ ] **Step 3: Seal and audit.** 运行 `--verify-only`；检查 54 条预期回放、训练/验证世界哈希互斥、正式世界哈希零交集、全部序列能回读、相机帧和教师有效位统计、碰撞/超时分布与实际时延分布。失败则保留当前未封存状态。
- [ ] **Step 4: Commit small evidence.** 只暂存封存清单、开发报告、`.gitignore` 和摘要，不提交大型 `samples.npz`、PX4/Gazebo 日志或敏感运行时文件。提交 `data: record sealed connectome corpus provenance`。

## Task 8: 完整 MaleCNS 单批门检与离线课程

**Files:** Create `tools/connectome_training/profile_full_batch.py`, `tests/connectome_training/test_corpus_profile.py`, `results/connectome-training/sequences/v2/full_batch_profile.json`; modify `docs/CONNECTOME_TRAINING.md`.

**Interfaces:** `profile_full_batch(config: CurriculumConfig, *, sequence_path: Path, output: Path, device: str) -> dict`；调用现有 `ConnectomeCurriculumSession` 的真实完整模型路径，独立输出门检检查点。

- [ ] **Step 1: Write failing tests.** 用小型 fake session 验证计时段、峰值内存、设备和检查点恢复字段齐全；映射错误、OOM、非有限损失时报告失败且不写成功状态。

```python
report = profile_full_batch(config, sequence_path=sequence, output=out, device="cpu")
assert set(report["timings_s"]) >= {"load", "forward", "backward", "checkpoint"}
assert report["model_identity"] == expected_identity
```

- [ ] **Step 2: Run red.** `python -m pytest tests/connectome_training/test_corpus_profile.py -q`。
- [ ] **Step 3: Implement.** 使用真实 `data/malecns_full.npz` 和 `results/connectome-training/stage-b/full-initialization`，调用 `verify_source_digest`、`Connectome.load`、`load_parameter_set` 和 `ConnectomeConstrainedCore`，检查身份为 `full-male-cns`、166700/25582837 规模与映射摘要。对一条短序列调用 `sequence_tensors`，显式分段计时 `forward_sequence`、`sequence_loss` 返回的总损失执行 `backward`、优化器更新、验证前向和 `save_checkpoint`；记录 RSS、CUDA allocated/reserved 峰值、版本及恢复摘要。异常写 `status=FAILED` 和错误类别。
- [ ] **Step 4: Run green and measured probe.** 先跑本任务测试，然后在无 PX4/Gazebo/EGO 进程时执行实测 CLI；检查点回读成功才标记门检通过。若失败，保留报告并停止正式课程，优先调查稀疏执行、截断长度和设备内存，不改模型身份。
- [ ] **Step 5: Start or resume curriculum if gate passes.** 使用 v2 desktop 档执行 `--max-batches 1`，检查状态、损失和内存，再按实际资源逐批恢复至完成或硬门槛失败。保留所有失败报告；课程失败不写成功结论。
- [ ] **Step 6: Final verification and commit.** 运行 `python -m pytest tests/connectome_training tests/benchmark -q` 与完整 Python 测试集；校验冻结 manifest 未变化、所有采集进程退出。仅提交门检摘要、课程摘要和文档，提交 `test: record full connectome corpus training evidence`。

## Completion Report

报告必须列出每阶段有效/失败回放数、封存摘要、教师及仿真版本、真实采集与训练墙钟、峰值内存和显存、课程门槛结果及参数身份。明确说明 Gazebo 是仿真证据，完整 MaleCNS 的离线损失与实机安全、表演成功率和 35 ms 实时决策延迟仍是不同指标。
