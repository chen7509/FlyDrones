# Hybrid Local Trajectory Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the distributed PX4 worker's yaw-only reflex with a deterministic onboard rolling obstacle memory and short-horizon trajectory selector whose hard safety gate cannot be overridden by PPO preferences.

**Architecture:** Each worker converts its own nine-ray depth observations into time-bounded world-frame evidence, predicts UDP peers with constant velocity, samples bounded body-frame trajectories and rejects any path that enters unknown space or violates static/peer clearance. A separate adapter supplies mission targets and learned-policy preferences; the parent process remains a launcher and offline evaluator only.

**Tech Stack:** Python 3.12, NumPy, pytest, existing `FlightCommand`, `DepthObservation`, `PeerTrack`, PX4 SITL, Gazebo Harmonic, PowerShell/WSL launch scripts.

**Spec:** `docs/superpowers/specs/2026-09-21-hybrid-local-trajectory-planner-design.md`

## Global Constraints

- One operating-system process owns one vehicle, one MAVLink connection, one depth subscription, one policy and one UDP endpoint.
- The parent process cannot receive live telemetry or issue flight commands.
- Use NumPy and existing project types only; do not add ROS, Nav2 or EGO-Planner as runtime dependencies.
- A candidate is rejected below 0.60 m static point clearance (`0.25 m` vehicle radius plus `0.35 m` margin) or 0.90 m predicted peer separation.
- Unknown, stale and rear space is blocked by default.
- Planning horizon is 2.0 seconds with 0.10-second integration steps and a 20 Hz control target.
- Safety is a Boolean gate. A learned preference cannot compensate for a safety violation.
- Persistent absence of safe motion ends in fail-closed landing; distance limits are never relaxed.
- Existing UDP wire format and mission task protocol remain unchanged.
- Final acceptance requires five consecutive five-PX4/Gazebo passes with zero central flight commands.

## Review Focus

- Yaw wraparound at `-pi/pi` must map adjacent rays to adjacent sectors; Task 1 pins this with `test_memory_wraps_world_bearing_across_pi`.
- A max-range ray is evidence of free space but not an obstacle endpoint; Task 1 pins this with `test_max_range_ray_does_not_create_false_obstacle`.
- A peer timestamp in the future or a peer velocity containing NaN must fail closed; Task 2 pins this with `test_invalid_peer_prediction_rejects_every_moving_candidate`.
- Identical candidate scores must resolve deterministically across processes and Python runs; Task 2 pins this with `test_equal_scores_use_stable_candidate_order`.
- A takeoff/preflight failure must remain distinct from a navigation failure and must not be counted as a passing repetition; Task 6 pins this with `test_repeatability_rejects_preflight_failure`.

---

### Task 1: Rolling world-frame obstacle memory

**Files:**
- Create: `src/flydrones/local_planner.py`
- Create: `tests/test_local_planner.py`

**Interfaces:**
- Consumes: observation objects with `captured_at: float` and `ray_distances_m: tuple[float, ...]`.
- Produces: `LocalPlannerConfig`, `WorldRay`, `ObstacleSnapshot`, and `RollingObstacleMemory.update(...)` / `snapshot(...)`.

- [ ] **Step 1: Write failing memory tests**

Create `tests/test_local_planner.py` with literal observations and these assertions:

```python
import math
from types import SimpleNamespace

from flydrones.local_planner import LocalPlannerConfig, RollingObstacleMemory


def depth(captured_at, rays):
    return SimpleNamespace(captured_at=captured_at, ray_distances_m=tuple(rays))


def test_depth_rays_become_world_frame_evidence_and_expire():
    memory = RollingObstacleMemory(LocalPlannerConfig(obstacle_memory_s=2.0))
    memory.update(
        now=10.0,
        position=(1.0, 2.0, 1.8),
        yaw_rad=math.pi / 2,
        depth_observation=depth(10.0, [19.1] * 4 + [2.0] + [19.1] * 4),
    )
    live = memory.snapshot(now=11.9)
    assert live.obstacle_points
    assert live.is_observed_free((2.0, 2.0), margin_m=0.10)
    assert not live.is_observed_free((1.0, 1.0), margin_m=0.10)
    assert memory.snapshot(now=12.01).rays == ()


def test_memory_wraps_world_bearing_across_pi():
    memory = RollingObstacleMemory(LocalPlannerConfig(sector_count=72))
    memory.update(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        yaw_rad=-math.pi + 0.01,
        depth_observation=depth(1.0, [3.0] * 9),
    )
    sectors = {ray.sector for ray in memory.snapshot(now=1.1).rays}
    assert 0 in sectors or 71 in sectors
    assert max(sectors) - min(sectors) > 60


def test_max_range_ray_does_not_create_false_obstacle():
    memory = RollingObstacleMemory(LocalPlannerConfig(sensor_range_m=19.1))
    memory.update(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        yaw_rad=math.pi / 2,
        depth_observation=depth(1.0, [19.1] * 9),
    )
    snapshot = memory.snapshot(now=1.1)
    assert snapshot.obstacle_points == ()
    assert snapshot.is_observed_free((3.0, 0.0), margin_m=0.10)
```

- [ ] **Step 2: Run the memory tests and verify RED**

Run:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m pytest -q tests/test_local_planner.py
```

Expected: collection fails because `flydrones.local_planner` does not exist.

- [ ] **Step 3: Implement config, ray evidence and expiration**

Create `src/flydrones/local_planner.py` with these public types:

```python
@dataclass(frozen=True)
class LocalPlannerConfig:
    horizontal_fov_rad: float = 1.274
    sector_count: int = 72
    sensor_range_m: float = 19.1
    obstacle_memory_s: float = 2.0
    horizon_s: float = 2.0
    integration_step_s: float = 0.10
    vehicle_radius_m: float = 0.25
    static_margin_m: float = 0.35
    peer_minimum_m: float = 0.90
    unknown_is_blocked: bool = True
    max_speed_mps: float = 0.8
    max_acceleration_mps2: float = 1.2
    max_yaw_rate_rad_s: float = math.radians(45.0)

@dataclass(frozen=True)
class WorldRay:
    origin_xy: tuple[float, float]
    bearing_rad: float
    free_distance_m: float
    obstacle_xy: tuple[float, float] | None
    observed_at: float
    sector: int

@dataclass(frozen=True)
class ObstacleSnapshot:
    rays: tuple[WorldRay, ...]
    obstacle_points: tuple[tuple[float, float], ...]
    sector_width_rad: float

    def is_observed_free(self, point_xy, *, margin_m: float) -> bool: ...

class RollingObstacleMemory:
    def update(self, *, now, position, yaw_rad, depth_observation) -> None: ...
    def snapshot(self, *, now) -> ObstacleSnapshot: ...
```

Validate finite inputs and exactly nine positive rays. Convert PX4 yaw to the existing world heading convention with `world_heading = pi / 2 - yaw_rad`. Use ray-center offsets from `-horizontal_fov_rad / 2` through `+horizontal_fov_rad / 2`. Normalize bearings into `[-pi, pi)`, snap sector indices modulo 72, mark `distance >= sensor_range_m - 1e-6` as free-only evidence, and discard rays older than `obstacle_memory_s`.

`is_observed_free` must accept a point only when at least one retained ray covers its bearing within half a sector and the along-ray distance plus `margin_m` is no greater than that ray's free distance. It must reject points behind the ray origin and points without evidence.

- [ ] **Step 4: Run the memory tests and verify GREEN**

Run the Task 1 command again.

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add src/flydrones/local_planner.py tests/test_local_planner.py
git commit -m "feat: add rolling local obstacle memory"
```

---

### Task 2: Candidate rollout and hard safety gate

**Files:**
- Modify: `src/flydrones/local_planner.py`
- Modify: `tests/test_local_planner.py`

**Interfaces:**
- Consumes: Task 1 `ObstacleSnapshot`, current pose/velocity/yaw, a target, learned preferred command and UDP-derived peer predictions.
- Produces: `PlannerPeer`, `TrajectoryCandidate`, `PlannerDecision`, and `HybridLocalPlanner.plan(...) -> PlannerDecision`.

- [ ] **Step 1: Write failing safety and determinism tests**

Append tests using these public interfaces:

```python
from flydrones.local_planner import HybridLocalPlanner, PlannerPeer
from flydrones.motor.command import FlightCommand


def clear_front(now=1.0):
    return depth(now, [19.1] * 9)


def test_unknown_rear_space_forbids_reverse_motion():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        target=(6.0, 0.0),
        depth_observation=clear_front(),
        peers=(),
        preferred_command=FlightCommand(forward=-1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.command.forward >= 0.0
    assert decision.rejection_counts["unknown"] > 0


def test_remembered_tree_stays_blocked_after_camera_turns_away():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    obstacle = depth(1.0, [19.1] * 4 + [1.0] + [19.1] * 4)
    planner.observe(now=1.0, position=(0.0, 0.0, 1.8), yaw_rad=math.pi / 2, depth_observation=obstacle)
    decision = planner.plan(
        now=1.2,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=0.0,
        target=(3.0, 0.0),
        depth_observation=clear_front(1.2),
        peers=(),
        preferred_command=FlightCommand(lateral=-1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.minimum_static_clearance_m >= 0.60


def test_crossing_peer_is_rejected_from_constant_velocity_prediction():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    peer = PlannerPeer(7, (1.0, 1.0, 1.8), (0.0, -1.0, 0.0), age_s=0.1)
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8),
        velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2,
        target=(6.0, 0.0),
        depth_observation=clear_front(),
        peers=(peer,),
        preferred_command=FlightCommand(forward=1.0),
        corridor_center_y=0.0,
        inside_forest=True,
    )
    assert decision.minimum_peer_separation_m >= 0.90
    assert decision.rejection_counts["peer"] > 0


def test_invalid_peer_prediction_rejects_every_moving_candidate():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    peer = PlannerPeer(7, (1.0, 0.0, 1.8), (float("nan"), 0.0, 0.0), age_s=-0.1)
    decision = planner.plan(
        now=1.0,
        position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0), yaw_rad=math.pi / 2,
        target=(6.0, 0.0), depth_observation=clear_front(), peers=(peer,),
        preferred_command=FlightCommand(forward=1.0), corridor_center_y=0.0, inside_forest=True,
    )
    assert decision.mode == "hold-invalid-peer"
    assert decision.command.forward == decision.command.lateral == 0.0


def test_equal_scores_use_stable_candidate_order():
    kwargs = dict(
        now=1.0,
        position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0), yaw_rad=math.pi / 2,
        target=(6.0, 0.0), depth_observation=clear_front(), peers=(),
        preferred_command=FlightCommand(), corridor_center_y=0.0, inside_forest=False,
    )
    first = HybridLocalPlanner(LocalPlannerConfig()).plan(**kwargs)
    second = HybridLocalPlanner(LocalPlannerConfig()).plan(**kwargs)
    assert first.candidate_id == second.candidate_id
    assert first.command == second.command
```

- [ ] **Step 2: Run new tests and verify RED**

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m pytest -q tests/test_local_planner.py
```

Expected: import failures for `HybridLocalPlanner` and `PlannerPeer`.

- [ ] **Step 3: Implement deterministic trajectory rollout**

Add:

```python
@dataclass(frozen=True)
class PlannerPeer:
    sender_id: int
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    age_s: float

@dataclass(frozen=True)
class TrajectoryCandidate:
    candidate_id: str
    forward_mps: float
    lateral_mps: float
    yaw_rate_rad_s: float
    samples: tuple[tuple[float, float, float], ...]

@dataclass(frozen=True)
class PlannerDecision:
    command: FlightCommand
    mode: str
    candidate_id: str
    minimum_static_clearance_m: float | None
    minimum_peer_separation_m: float | None
    generated_candidates: int
    rejection_counts: dict[str, int]
    planning_time_ms: float

class HybridLocalPlanner:
    def observe(self, *, now, position, yaw_rad, depth_observation) -> None: ...
    def plan(
        self, *, now, position, velocity, yaw_rad, target, depth_observation,
        peers, preferred_command, corridor_center_y, inside_forest,
    ) -> PlannerDecision: ...
```

Use a fixed ordered lattice of candidate tuples `(forward, lateral, yaw)` containing hold; rotate left/right; forward speeds `0.12, 0.25, 0.45, 0.65`; lateral values `-0.35, 0.0, 0.35`; and yaw values `-0.65, 0.0, 0.65`. Apply acceleration and yaw limits from the current velocity before integrating 20 samples.

For each predicted sample:

1. require `ObstacleSnapshot.is_observed_free` for the sample point;
2. compute distance to every remembered obstacle endpoint and reject below 0.60 m;
3. predict peer position as `position + velocity * (age_s + t)` and reject below 0.90 m plus `min(0.30, age_s * 0.25)`;
4. reject corridor motion that increases absolute corridor error when inside the forest and already outside the configured half-width; and
5. reject non-finite inputs before candidate generation.

Score safe candidates with a lexicographically stable tuple: target progress, minimum clearance, negative corridor error, negative command delta, PPO agreement, then negative lattice index. Use the lattice index as the final tie-breaker.

The zero-velocity hold candidate may remain at the already occupied current point even when that point lacks a fresh free-space ray; it is still rejected if a remembered obstacle or predicted peer violates the hard distance. Moving candidates never receive this exception.

- [ ] **Step 4: Add the all-blocked and lateral-escape tests**

```python
def test_all_blocked_scene_returns_horizontal_hold():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    blocked = depth(1.0, [0.55] * 9)
    decision = planner.plan(
        now=1.0, position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0), yaw_rad=math.pi / 2,
        target=(6.0, 0.0), depth_observation=blocked, peers=(),
        preferred_command=FlightCommand(forward=1.0), corridor_center_y=0.0, inside_forest=True,
    )
    assert decision.mode == "hold-no-safe-trajectory"
    assert decision.command.forward == decision.command.lateral == 0.0


def test_observed_lateral_clearance_allows_side_escape():
    planner = HybridLocalPlanner(LocalPlannerConfig())
    rays = [4.0, 4.0, 4.0, 0.7, 0.6, 0.7, 19.1, 19.1, 19.1]
    decision = planner.plan(
        now=1.0, position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0), yaw_rad=math.pi / 2,
        target=(6.0, 0.0), depth_observation=depth(1.0, rays), peers=(),
        preferred_command=FlightCommand(forward=1.0), corridor_center_y=0.0, inside_forest=True,
    )
    assert abs(decision.command.lateral) > 0.0 or abs(decision.command.yaw) > 0.0
    assert decision.command.forward < 1.0
```

- [ ] **Step 5: Run Task 2 tests and verify GREEN**

Run `python -m pytest -q tests/test_local_planner.py`.

Expected: all local planner tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/flydrones/local_planner.py tests/test_local_planner.py
git commit -m "feat: select safe local trajectories"
```

---

### Task 3: Learned preference and mission-phase adapter

**Files:**
- Create: `src/flydrones/hybrid_agent.py`
- Create: `tests/test_hybrid_agent.py`

**Interfaces:**
- Consumes: Task 2 `HybridLocalPlanner`, an object with `predict(np.ndarray)`, one target and local sensor/peer inputs.
- Produces: `HybridPlannerAgent.command(...) -> FlightCommand`, `HybridPlannerAgent.should_land`, and per-step `last_decision` diagnostics.

- [ ] **Step 1: Write failing adapter tests**

```python
import math
from types import SimpleNamespace
import numpy as np

from flydrones.hybrid_agent import HybridPlannerAgent
from flydrones.local_planner import LocalPlannerConfig, PlannerPeer


class UnsafeReversePolicy:
    def __init__(self):
        self.calls = 0
    def predict(self, observation):
        self.calls += 1
        assert observation.shape == (16,)
        return np.asarray((-1.0, 0.0), dtype=np.float32)


def test_policy_reverse_preference_cannot_enter_unknown_space():
    policy = UnsafeReversePolicy()
    agent = HybridPlannerAgent(0, (6.5, 0.0), policy, config=LocalPlannerConfig())
    clear = SimpleNamespace(captured_at=1.0, ray_distances_m=(19.1,) * 9)
    command = agent.command(
        now=1.0, global_position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2, peers=(), depth_observation=clear,
    )
    assert policy.calls == 1
    assert command.forward >= 0.0
    assert agent.last_decision.rejection_counts["unknown"] > 0


def test_stale_depth_holds_then_requests_fail_closed_landing():
    agent = HybridPlannerAgent(
        0, (6.5, 0.0), UnsafeReversePolicy(),
        config=LocalPlannerConfig(), deadlock_land_after_s=3.0,
    )
    first = agent.command(
        now=1.0, global_position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2, peers=(), depth_observation=None,
    )
    agent.command(
        now=4.1, global_position=(0.0, 0.0, 1.8), velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2, peers=(), depth_observation=None,
    )
    assert first.forward == first.lateral == 0.0
    assert agent.should_land
```

- [ ] **Step 2: Run adapter tests and verify RED**

Run `python -m pytest -q tests/test_hybrid_agent.py`.

Expected: collection fails because `flydrones.hybrid_agent` does not exist.

- [ ] **Step 3: Implement the adapter**

Implement `HybridPlannerAgent` with constructor parameters `(vehicle_id, rally_target, policy, *, config, target_altitude_m=1.8, corridor_center_y=None, deadlock_land_after_s=3.0)`. Reuse the existing 16-element learned observation layout: normalized target distance, sine/cosine target bearing, previous action, reserved zero, nine depth proximities and previous two actions.

Convert policy output to a preferred `FlightCommand`; do not send it directly. Pass it to `HybridLocalPlanner.plan`. Set `phase` from `escaping` to `rally` at `x >= 4.0` and to `arrived` within 0.35 m of target. Track consecutive hold duration; set `should_land=True` after `deadlock_land_after_s`. Keep altitude control as `clamp((target_altitude - z) / 0.5, -1, 1)` and apply it after the planner's horizontal decision.

- [ ] **Step 4: Add deterministic target-phase test**

```python
def test_agent_enters_arrived_phase_only_inside_target_radius():
    agent = HybridPlannerAgent(0, (6.5, 0.0), UnsafeReversePolicy(), config=LocalPlannerConfig())
    clear = SimpleNamespace(captured_at=1.0, ray_distances_m=(19.1,) * 9)
    agent.command(
        now=1.0, global_position=(6.2, 0.0, 1.8), velocity=(0.0, 0.0, 0.0),
        yaw_rad=math.pi / 2, peers=(), depth_observation=clear,
    )
    assert agent.phase == "arrived"
    assert agent.last_decision.command.forward == 0.0
```

- [ ] **Step 5: Run Task 3 tests and verify GREEN**

Run `python -m pytest -q tests/test_hybrid_agent.py tests/test_local_planner.py`.

Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add src/flydrones/hybrid_agent.py tests/test_hybrid_agent.py
git commit -m "feat: gate learned flight preferences through planner"
```

---

### Task 4: Integrate the planner into independent PX4 workers

**Files:**
- Modify: `src/flydrones/distributed_px4.py`
- Modify: `tests/test_distributed_px4.py`
- Modify: `tools/px4_distributed_agent.py`

**Interfaces:**
- Consumes: Task 3 `HybridPlannerAgent` and existing `PeerTrack` objects from `UdpPeerNode.poll`.
- Produces: `run_distributed_px4_agent(..., agent=None, ...)`, worker traces with planner diagnostics, and accepted worker results based on the new adapter.

- [ ] **Step 1: Write failing worker integration tests**

Add a `LocalPeerNode` track containing velocity and assert the worker passes complete peer motion into its own planner. Extend CSV assertions:

```python
def test_worker_records_hybrid_planner_diagnostics(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=2, output_dir=tmp_path, mission_timeout_s=20.0, land_timeout_s=5.0),
        drone=drone,
        depth_camera=LocalDepthCamera(),
        peer_node=LocalPeerNode(),
        policy=ForwardPolicy(),
        monotonic=clock.time,
        wall_time=clock.wall_time,
        sleep=clock.sleep,
    )
    assert result["accepted"], result
    assert result["metrics"]["planner_calls"] > 0
    assert result["metrics"]["planner_p95_ms"] >= 0.0
    assert all("planner_mode" in row for row in trace if row["phase"] != "land")
    assert all("planner_candidate_id" in row for row in trace if row["phase"] != "land")
    assert all("predicted_peer_separation_m" in row for row in trace if row["phase"] != "land")
```

Add a second test where a fake agent requests landing:

```python
class FailClosedAgent:
    phase = "escaping"
    should_land = True
    policy_calls = 0
    last_decision = None

    def command(self, **_kwargs):
        return FlightCommand.hover("planner fail closed")


def test_worker_honors_local_fail_closed_landing_without_waiting_for_timeout(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path, mission_timeout_s=70.0),
        drone=drone, depth_camera=LocalDepthCamera(), peer_node=LocalPeerNode(),
        policy=ForwardPolicy(), agent=FailClosedAgent(),
        monotonic=clock.time, wall_time=clock.wall_time, sleep=clock.sleep,
    )
    assert result["metrics"]["fail_closed_land"]
    assert clock.now < 10.0
    assert drone.land_called
```

- [ ] **Step 2: Run worker tests and verify RED**

Run `python -m pytest -q tests/test_distributed_px4.py`.

Expected: diagnostic metric and CSV field assertions fail.

- [ ] **Step 3: Replace the distributed worker adapter**

Add an optional `agent=None` dependency-injection parameter to `run_distributed_px4_agent`; when it is `None`, instantiate `HybridPlannerAgent` instead of `LearnedDepthForestAgent`. Convert each `PeerTrack` into:

```python
PlannerPeer(
    sender_id=track.sender_id,
    position=track.position,
    velocity=track.velocity,
    age_s=max(0.0, timestamp - track.received_at),
)
```

Pass the worker's measured velocity to `command`. If `agent.should_land` becomes true, set `fail_closed_land=True` and leave the mission loop for the existing `finally` landing path.

Add trace fields `planner_mode`, `planner_candidate_id`, `planner_generated_candidates`, `planner_rejected_unknown`, `planner_rejected_static`, `planner_rejected_peer`, `predicted_static_clearance_m`, `predicted_peer_separation_m`, and `planner_time_ms`. Aggregate planner call count and p95 time without reading data from another worker. Add aggregate `central_control_commands: 0` and require it to remain zero.

- [ ] **Step 4: Add invalid planner output test**

```python
class NonFiniteAgent(FailClosedAgent):
    should_land = False

    def command(self, **_kwargs):
        return FlightCommand(forward=float("nan"), note="invalid planner output")


def test_worker_rejects_non_finite_planner_command_and_lands(tmp_path):
    clock = Clock()
    drone = LocalKinematicDrone(clock)
    clock.drone = drone
    _trace, result = run_distributed_px4_agent(
        DistributedAgentConfig(vehicle_id=0, output_dir=tmp_path),
        drone=drone, depth_camera=LocalDepthCamera(), peer_node=LocalPeerNode(),
        policy=ForwardPolicy(), agent=NonFiniteAgent(),
        monotonic=clock.time, wall_time=clock.wall_time, sleep=clock.sleep,
    )
    assert not result["accepted"]
    assert "non-finite" in result["error"]
    assert drone.land_called
    assert drone.last_command is None
```

- [ ] **Step 5: Run Task 4 tests and verify GREEN**

Run:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m pytest -q tests/test_local_planner.py tests/test_hybrid_agent.py tests/test_distributed_px4.py tests/test_peer_udp.py
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add src/flydrones/distributed_px4.py tools/px4_distributed_agent.py tests/test_distributed_px4.py
git commit -m "feat: use hybrid planner in PX4 workers"
```

---

### Task 5: Randomized local-planner stress harness

**Files:**
- Create: `src/flydrones/local_planner_stress.py`
- Create: `tools/run_local_planner_stress.py`
- Create: `tests/test_local_planner_stress.py`

**Interfaces:**
- Consumes: Task 2 planner and Task 3 adapter.
- Produces: `run_local_planner_stress(seed, scenario_count) -> dict` and JSON/Markdown artifacts.

- [ ] **Step 1: Write failing deterministic stress tests**

```python
from flydrones.local_planner_stress import run_local_planner_stress


def test_randomized_crossing_and_forest_cases_remain_collision_free():
    result = run_local_planner_stress(seed=20260921, scenario_count=100)
    assert result["accepted"], result
    assert result["metrics"]["scenarios"] == 100
    assert result["metrics"]["static_contacts"] == 0
    assert result["metrics"]["peer_contacts"] == 0
    assert result["metrics"]["minimum_static_clearance_m"] >= 0.60
    assert result["metrics"]["minimum_peer_separation_m"] >= 0.90


def test_stress_seed_is_reproducible():
    assert run_local_planner_stress(7, 10) == run_local_planner_stress(7, 10)
```

- [ ] **Step 2: Run stress tests and verify RED**

Run `python -m pytest -q tests/test_local_planner_stress.py`.

Expected: collection fails because the stress module does not exist.

- [ ] **Step 3: Implement 100 deterministic scenarios**

Generate four equal scenario classes: frontal trunk with asymmetric opening, head-on peer, perpendicular crossing peer and UDP-stale peer. Seed positions, headings and velocities within fixed safe ranges. Integrate the chosen command at 20 Hz for up to 20 seconds; independently compute point-to-obstacle and pairwise distances after every step. Fail a scenario on contact, non-finite state, geofence departure or timeout.

Use these public structures and entry point:

```python
@dataclass(frozen=True)
class StressScenario:
    kind: str
    start: tuple[float, float, float]
    target: tuple[float, float]
    obstacle_points: tuple[tuple[float, float], ...]
    peers: tuple[PlannerPeer, ...]


def run_local_planner_stress(seed: int = 20260921, scenario_count: int = 100) -> dict:
    rng = random.Random(seed)
    scenarios = _generate_scenarios(rng, scenario_count)
    outcomes = [_run_scenario(scenario) for scenario in scenarios]
    metrics = _aggregate_outcomes(outcomes)
    return {"accepted": all(outcome.accepted for outcome in outcomes), "metrics": metrics}
```

The CLI accepts `--seed`, `--scenarios` and `--output`, writes `summary.json` and `report.md`, prints JSON, and exits 2 when rejected.

- [ ] **Step 4: Run Task 5 tests and stress CLI**

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m pytest -q tests/test_local_planner_stress.py
python tools/run_local_planner_stress.py --seed 20260921 --scenarios 100 --output results/local-planner-stress
```

Expected: tests pass and CLI reports `accepted: true` with zero contacts.

- [ ] **Step 5: Commit Task 5**

```powershell
git add src/flydrones/local_planner_stress.py tools/run_local_planner_stress.py tests/test_local_planner_stress.py
git commit -m "test: stress hybrid local planner"
```

---

### Task 6: Consecutive PX4/Gazebo acceptance harness

**Files:**
- Create: `src/flydrones/px4_repeatability.py`
- Create: `tests/test_px4_repeatability.py`
- Create: `tools/report_hybrid_px4_repeatability.py`
- Create: `Start-PX4-Hybrid-Swarm.ps1`
- Modify: `docs/DISTRIBUTED_SWARM.md`

**Interfaces:**
- Consumes: five completed distributed worker run directories and their `summary.json`/agent JSON files.
- Produces: `evaluate_px4_repetitions(run_dirs, required=5) -> dict` and a repeatable five-run launcher.

- [ ] **Step 1: Write failing repeatability tests**

```python
import json
from flydrones.px4_repeatability import evaluate_px4_repetitions


def write_run(path, *, accepted=True, preflight=True, planner_p95=4.0):
    path.mkdir()
    summary = {
        "accepted": accepted,
        "checks": {
            "all_reached_altitude": preflight,
            "all_escaped": accepted,
            "all_rallied": accepted,
            "all_landed": True,
            "zero_forest_contacts": True,
            "safe_forest_clearance": True,
            "safe_intervehicle_separation": True,
            "zero_direct_global_neighbor_reads": True,
            "udp_blackout_exercised": True,
        },
        "metrics": {
            "minimum_forest_clearance_m": 0.15,
            "minimum_intervehicle_distance_m": 1.0,
            "planner_p95_ms": planner_p95,
            "central_control_commands": 0,
        },
    }
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_repeatability_requires_five_consecutive_complete_runs(tmp_path):
    runs = [tmp_path / f"run-{index}" for index in range(5)]
    for run in runs:
        write_run(run)
    result = evaluate_px4_repetitions(runs, required=5)
    assert result["accepted"]
    assert result["metrics"]["consecutive_passes"] == 5


def test_repeatability_rejects_preflight_failure(tmp_path):
    runs = [tmp_path / f"run-{index}" for index in range(5)]
    for index, run in enumerate(runs):
        write_run(run, accepted=index != 2, preflight=index != 2)
    result = evaluate_px4_repetitions(runs, required=5)
    assert not result["accepted"]
    assert result["metrics"]["consecutive_passes"] == 2
    assert result["failures"][0]["category"] == "preflight"
```

- [ ] **Step 2: Run repeatability tests and verify RED**

Run `python -m pytest -q tests/test_px4_repeatability.py`.

Expected: collection fails because `flydrones.px4_repeatability` does not exist.

- [ ] **Step 3: Implement repeatability evaluation**

Read summaries in given order. Reset the consecutive counter after any failure. Classify failures as `preflight`, `navigation`, `separation`, `planner-performance` or `infrastructure`. Require every documented check, `central_control_commands == 0`, and `planner_p95_ms < 20.0`. Return worst clearances, worst planner p95, pass count and failure list.

Use this entry point and fixed classification order:

```python
def evaluate_px4_repetitions(run_dirs: Sequence[str | Path], *, required: int = 5) -> dict:
    summaries = [_load_summary(Path(run_dir) / "summary.json") for run_dir in run_dirs]
    consecutive = 0
    failures = []
    for index, summary in enumerate(summaries, start=1):
        category = _failure_category(summary)  # preflight, navigation, separation, planner-performance, infrastructure
        if category is None:
            consecutive += 1
        else:
            failures.append({"run": index, "category": category})
            consecutive = 0
    return {
        "accepted": len(summaries) >= required and consecutive >= required,
        "metrics": _aggregate_repeatability_metrics(summaries, consecutive),
        "failures": failures,
    }
```

The report CLI accepts run directories plus `--required`, writes aggregate JSON/Markdown and exits nonzero on rejection.

- [ ] **Step 4: Implement the PowerShell five-run launcher**

`Start-PX4-Hybrid-Swarm.ps1` must:

1. resolve the Windows and WSL repository paths without string-built shell commands;
2. loop from 1 through 5;
3. launch five PX4 instances with a unique `/tmp/flydrones-hybrid-$run` directory;
4. run `tools/run_distributed_px4_swarm.py` with unique peer base ports `18000 + run * 10` and output `results/px4-hybrid-repeatability/run-$run`;
5. always invoke `tools/stop_px4_swarm_wsl.sh` in `finally`;
6. stop immediately on a failed run; and
7. invoke the Python repeatability reporter after five successful runs.

The launcher does not inspect live telemetry or send a flight command.

Use this control structure so cleanup runs after every repetition:

```powershell
$ErrorActionPreference = 'Stop'
$completed = @()
for ($run = 1; $run -le 5; $run++) {
    $runDir = "/tmp/flydrones-hybrid-$run"
    $outputDir = "$linuxRoot/results/px4-hybrid-repeatability/run-$run"
    try {
        wsl -d Ubuntu -- env "FLYDRONES_PX4_RUN_DIR=$runDir" bash "$linuxRoot/tools/launch_px4_depth_swarm_wsl.sh"
        if ($LASTEXITCODE -ne 0) { throw "PX4 startup failed for run $run" }
        wsl -d Ubuntu -- env "PYTHONPATH=$linuxRoot/src" python3 "$linuxRoot/tools/run_distributed_px4_swarm.py" `
            --peer-base-port (18000 + $run * 10) --output $outputDir
        if ($LASTEXITCODE -ne 0) { throw "PX4 acceptance failed for run $run" }
        $completed += $outputDir
    }
    finally {
        wsl -d Ubuntu -- env "FLYDRONES_PX4_RUN_DIR=$runDir" bash "$linuxRoot/tools/stop_px4_swarm_wsl.sh"
    }
}
python tools/report_hybrid_px4_repeatability.py --required 5 --output results/px4-hybrid-repeatability @completed
```

- [ ] **Step 5: Run Task 6 tests and syntax checks**

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m pytest -q tests/test_px4_repeatability.py
$null = [scriptblock]::Create((Get-Content 'Start-PX4-Hybrid-Swarm.ps1' -Raw))
```

Expected: tests pass and PowerShell parsing returns no exception.

- [ ] **Step 6: Document the command and acceptance boundary**

Add the exact launcher command, output paths, five-consecutive-pass rule, planner metrics and simulation limitation to `docs/DISTRIBUTED_SWARM.md`.

- [ ] **Step 7: Commit Task 6**

```powershell
git add src/flydrones/px4_repeatability.py tests/test_px4_repeatability.py tools/report_hybrid_px4_repeatability.py Start-PX4-Hybrid-Swarm.ps1 docs/DISTRIBUTED_SWARM.md
git commit -m "feat: verify PX4 planner repeatability"
```

---

### Task 7: Full verification and five-run simulation

**Files:**
- Modify only when a verified failure requires a TDD fix.
- Generate: `results/local-planner-stress/*`
- Generate: `results/px4-hybrid-repeatability/*`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: complete test evidence, five consecutive PX4/Gazebo results and final review package.

- [ ] **Step 1: Run focused planner and distributed tests**

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m pytest -q tests/test_local_planner.py tests/test_hybrid_agent.py tests/test_local_planner_stress.py tests/test_distributed_px4.py tests/test_peer_udp.py tests/test_px4_repeatability.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run the complete Python suite**

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m pytest -q
```

Expected: all tests pass; the existing MaleCNS unmatched-group warning may remain.

- [ ] **Step 3: Run static verification**

```powershell
python -m ruff check src/flydrones/local_planner.py src/flydrones/hybrid_agent.py src/flydrones/local_planner_stress.py src/flydrones/px4_repeatability.py tools/run_local_planner_stress.py tools/report_hybrid_px4_repeatability.py tests/test_local_planner.py tests/test_hybrid_agent.py tests/test_local_planner_stress.py tests/test_px4_repeatability.py
python -m py_compile src/flydrones/local_planner.py src/flydrones/hybrid_agent.py src/flydrones/local_planner_stress.py src/flydrones/px4_repeatability.py
git diff --check
```

Expected: Ruff, compilation and diff checks pass.

- [ ] **Step 4: Run deterministic 100-scenario stress**

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python tools/run_local_planner_stress.py --seed 20260921 --scenarios 100 --output results/local-planner-stress
```

Expected: `accepted: true`, zero contacts, minimum static clearance at least 0.60 m and peer separation at least 0.90 m.

- [ ] **Step 5: Run five consecutive PX4/Gazebo trials**

```powershell
.\Start-PX4-Hybrid-Swarm.ps1
```

Expected: all five run summaries and the aggregate repeatability summary report accepted; zero tree contacts; forest clearance at least 0.10 m; intervehicle separation at least 0.72 m; planner p95 below 20 ms; zero central control commands.

- [ ] **Step 6: Perform whole-branch review and one fix pass**

Generate the executing-plans review package from the merge base through `HEAD`. Review specifically the five Review Focus inputs. Re-grade findings by user effect. Fix every Critical or Important finding with a new failing test, watch it pass, and rerun the complete suite. Record Minor findings without modifying behavior.

- [ ] **Step 7: Commit final evidence documentation**

Update `docs/DISTRIBUTED_SWARM.md` with actual measured results and artifact paths, then commit only documentation and source-controlled report metadata. Keep generated `results/` artifacts untracked.

```powershell
git add docs/DISTRIBUTED_SWARM.md
git commit -m "docs: record hybrid planner verification"
```
