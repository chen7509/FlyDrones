# Hybrid Local Trajectory Planner Design

## Status and goal

This design replaces the current yaw-only forest reflex used by each distributed PX4 worker with an onboard rolling obstacle memory and short-horizon trajectory selector. The goal is repeatable, decentralized forest escape and rally flight in PX4/Gazebo while preserving the existing one-process-per-vehicle and peer-to-peer UDP architecture.

Success means five consecutive five-vehicle trials complete with every vehicle taking off, escaping, rallying and landing; zero tree contacts; at least 0.10 m evaluated forest clearance; at least 0.72 m intervehicle separation; and zero central flight commands. The design remains simulation work and is not a hardware flight-safety certification.

## Evidence motivating the change

Fresh PX4/Gazebo trials exposed three failure modes in the existing controller:

1. A front-facing depth camera turned away from a tree while an emergency routine commanded blind reverse motion. One vehicle contacted the tree and fell below the simulated ground.
2. Holding position after the emergency turn prevented the contact but produced a turn-hold loop that could not leave the obstacle.
3. Allowing low-speed motion into observed free space enabled escape in one run, but another run diverged during rally and reached only 0.3714 m intervehicle separation.

The common cause is architectural: the current controller reacts to one depth frame and one requested heading. It does not remember recently observed obstacles, predict moving peers, or evaluate the complete path swept by a velocity command.

## Reference model

The implementation will follow three established ideas without importing ROS or a large external planner:

- PX4 Collision Prevention maintains a 72-sector obstacle representation, treats directions without sensor data as unavailable by default, and constrains motion before the minimum distance is violated: <https://docs.px4.io/main/en/computer_vision/collision_prevention>.
- Nav2 DWB generates short candidate trajectories, rejects invalid trajectories and scores the survivors with independent critics: <https://github.com/ros-navigation/navigation2/tree/main/nav2_dwb_controller>.
- EGO-Planner demonstrates local receding-horizon planning for quadrotors, but its ROS/C++ stack and continuous optimization are larger than this prototype requires: <https://github.com/ZJU-FAST-Lab/ego-planner>.

The FlyDrones implementation will be a small Python planner specialized for the current five-PX4 trial. It will use only NumPy and existing project types.

## Architecture

Each PX4 worker continues to own exactly one MAVLink connection, one Gazebo depth subscription, one learned policy and one UDP endpoint. The parent process only launches workers and reads completed artifacts.

The worker control path becomes:

```text
local pose + velocity + yaw
        depth frame ──> rolling local obstacle memory
UDP peer tracks ─────> constant-velocity peer predictions
mission target ──────> candidate trajectory generator
PPO/fly output ──────> preference critic
                       hard safety rejection
                              ↓
                     selected FlightCommand
                              ↓
                            PX4
```

The learned policy proposes a preference. It never bypasses the trajectory safety checks.

## Components and interfaces

### Rolling obstacle memory

`src/flydrones/local_planner.py` will define:

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

class RollingObstacleMemory:
    def update(self, *, now, position, yaw_rad, depth_observation) -> None: ...
    def snapshot(self, *, now) -> "ObstacleSnapshot": ...
```

The nine depth sectors cover the camera's 1.274 rad horizontal field of view. Every update transforms observed free rays and obstacle endpoints into the local world frame. Observations expire after two seconds. A candidate may enter only space observed free during the memory window; missing, stale and rear sensor coverage remains blocked. This explicitly prevents blind reverse or side motion.

The memory is local to one worker. It is never shared through the launcher or another process.

### Peer prediction

The planner consumes the existing `PeerTrack` values, including position, velocity and receive time. Each peer is projected with constant velocity over the two-second horizon. Track age adds an uncertainty radius, and expired tracks continue to be removed by `UdpPeerNode`.

During a configured UDP blackout, a worker may continue through recently observed static free space but cannot enter a trajectory whose separation depends on a stale peer track. If no safe trajectory remains, it holds position.

### Candidate generation

At 20 Hz the planner samples bounded body-frame horizontal velocities and yaw rates. Candidates include stop, rotate in place, slow forward arcs, lateral escape, diagonal motion and direct target progress. Vertical speed remains the existing altitude hold for this stage because the simulated obstacles are vertical trunks.

Each candidate is integrated for two seconds in 0.10-second steps. Acceleration and yaw-rate limits are applied before collision checking so a trajectory represents what PX4 can approximately execute rather than an instantaneous velocity jump.

### Hard safety rejection

A candidate is rejected when any predicted sample:

- enters unknown or stale sensor space;
- approaches an observed static obstacle by less than vehicle radius plus 0.35 m;
- approaches a predicted peer by less than 0.90 m;
- leaves the assigned corridor recovery envelope while still inside the forest;
- exceeds the configured speed, yaw-rate or acceleration limits; or
- relies on invalid pose, non-finite data or stale depth.

If all moving candidates are rejected, the decision is horizontal hold with altitude stabilization. Persistent lack of safe motion transitions to the existing fail-closed landing path rather than relaxing a distance limit.

### Scoring safe candidates

Only safe candidates are scored. Critics are deterministic and ordered:

1. target progress;
2. minimum static and peer clearance;
3. corridor recovery while inside the forest;
4. control smoothness and low yaw churn;
5. agreement with the PPO/fly-inspired preferred motion.

Safety is a Boolean gate, not a weighted score. A high learned-policy score cannot compensate for a clearance violation.

The result is a `PlannerDecision` containing the normalized `FlightCommand`, predicted clearance, selected mode, rejected-candidate counts and timing. These fields are written to each worker's CSV for offline diagnosis.

### Distributed worker integration

`src/flydrones/distributed_px4.py` will instantiate one planner per worker and pass complete `PeerTrack` objects instead of positions only. A new agent adapter owns mission phase, target selection, obstacle memory, policy inference and the planner call. Existing UDP packet formats, launcher behavior and artifact aggregation remain compatible.

The current `LearnedDepthForestAgent` remains available for historical experiments. The distributed five-PX4 acceptance path switches explicitly to the new adapter.

### Preflight behavior

Navigation acceptance begins only after local depth, finite pose and PX4 readiness are present. A vehicle that cannot take off fails closed and does not enter the mission. Simulator startup failures are reported separately from navigation failures; the acceptance harness does not silently convert a failed vehicle into a passing run.

No automatic re-arm will be added for hardware. A simulation-only whole-trial retry may be used to diagnose Gazebo startup nondeterminism, but it does not count as a successful navigation repetition.

## Failure handling

- Stale depth: hold horizontal motion; land after the existing timeout.
- Invalid localization: land immediately through the existing worker cleanup path.
- No safe trajectory: hold and rotate only when the rotation itself is allowed; land after a bounded deadlock timeout.
- UDP loss or blackout: use only unexpired local tracks, enlarge uncertainty with age and hold if separation cannot be proven.
- Worker failure: other workers continue with their own sensors and UDP caches; no coordinator flight command is introduced.
- Planner exception or non-finite output: replace the output with hold, record the reason and enter fail-closed landing.

## Testing strategy

Implementation uses test-driven development.

Unit tests will prove:

- depth rays transform into the correct world sectors and expire;
- unknown rear space forbids reverse motion;
- a remembered obstacle remains blocked after the camera turns away;
- a lateral path through observed free space can escape a frontal obstacle;
- a crossing peer is rejected using its UDP velocity;
- stale peer uncertainty cannot be bypassed by the learned preference;
- an all-blocked scene returns hold;
- invalid inputs return fail-closed behavior; and
- the same inputs produce the same decision.

Integration tests will use fake PX4/depth/UDP components to verify one worker reads only its own telemetry and local peer cache. Kinematic randomized trials will cover crossing, corridor recovery, packet loss, blackout and stationary-worker failures before expensive Gazebo runs.

Final simulation acceptance requires five consecutive five-PX4/Gazebo runs with:

- 5/5 takeoff, escape, rally and landing;
- zero evaluated tree contacts;
- minimum forest clearance at least 0.10 m;
- minimum intervehicle separation at least 0.72 m;
- zero direct global-neighbor reads and zero central flight commands;
- UDP random loss and blackout exercised; and
- planner p95 execution time below 20 ms on the current computer.

Every run retains per-worker traces, planner diagnostics, aggregate JSON and a trajectory image. A failed repetition resets the consecutive-pass count.

## Scope limits

This stage validates five full PX4/Gazebo vehicles and the existing 100-process kinematic mission layer. It does not run 100 PX4 physics instances, certify real sensors, model prop wash or radio coexistence, or authorize an outdoor commercial show. Hardware-in-the-loop and small geofenced outdoor trials remain later stages.
