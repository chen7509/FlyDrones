# Decentralized Mission Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured mission layer that lets 100 one-process-per-vehicle agents allocate, recover and complete a forest search/confirmation/rally mission after the task station exits.

**Architecture:** The ground process validates and broadcasts one immutable `MissionContract`. Each agent expands the same contract into identical work units, reaches assignment consensus through a bounded UDP gossip overlay, renews task leases, plans locally and applies a deterministic safety supervisor before producing a navigation intent. The parent never reads live telemetry for control and performs scoring only after all agent processes exit.

**Tech Stack:** Python 3.11+, standard-library dataclasses/JSON/hashlib/socket/multiprocessing, existing `UdpPeerNode`, pytest, Ruff, matplotlib for offline evidence.

**Spec:** `docs/superpowers/specs/2026-09-21-decentralized-mission-agents-design.md`

## Global Constraints

- First release supports only `schema_version=1` and `mission_type="search_confirm_rally"`.
- A contract contains no per-vehicle waypoints and must pass strict finite-number, polygon, deadline and safety-limit validation.
- Each logical vehicle owns one operating-system process, one mission state, one task ledger, one motion UDP endpoint and one task UDP endpoint.
- The task station may retry the immutable contract before start, but after mission acceptance it sends no waypoint, velocity, attitude, motor or avoidance commands.
- Position traffic stays in `peer_udp.py`; task traffic uses a separate `FDT1` protocol and separate port range.
- Task gossip uses overlay offsets `±1, ±3, ±7, ±13 (mod N)`, datagrams at most 1200 bytes and at most 10 transmitted task datagrams per agent per second.
- Active task leases last 3.0 seconds and renew twice per second; allocation merge runs at 5 Hz.
- Learning outputs are advisory; deterministic safety limits and emergency states always win.
- Existing five-PX4 distributed acceptance behavior must remain unchanged.

## Review Focus

- Malformed JSON, duplicate keys, non-finite numbers or booleans where numbers are expected must reject the whole contract without partial task creation; Task 1 pins this behavior.
- Same-round equal-utility bids arriving in different orders must converge to the smaller vehicle ID; Task 2 tests all delivery orders.
- Sequence wrap, stale mission hashes, oversized datagrams and a sender exceeding 10 messages/second must not corrupt or block task gossip; Task 3 covers each case.
- A sensor freeze and low-battery transition occurring during an active task must release the lease exactly once and never return to task execution without a new healthy state; Task 4 covers both transitions.
- Ten process deaths adjacent in vehicle-ID space must not disconnect gossip or leave their tasks permanently claimed; Task 5 includes this worst-case failure pattern in addition to random failures.

---

### Task 1: Strict Mission Contract and Deterministic Work Units

**Files:**
- Create: `src/flydrones/mission_contract.py`
- Create: `tests/test_mission_contract.py`
- Create: `configs/mission_search_confirm_rally.json`

**Interfaces:**
- Consumes: standard JSON-compatible dictionaries.
- Produces: `SafetyLimits`, `WorkUnit`, `MissionContract.from_dict(data)`, `MissionContract.to_dict()`, `MissionContract.digest`, `MissionContract.expand_work_units()` and `load_mission_contract(path)`.

- [ ] **Step 1: Write failing validation and determinism tests**

```python
def test_contract_rejects_unknown_fields_nonfinite_values_and_boolean_numbers():
    valid = valid_contract_dict()
    for mutation in (
        lambda item: item.update(extra="forbidden"),
        lambda item: item.update(deadline_s=float("nan")),
        lambda item: item["safety"].update(maximum_speed_mps=True),
    ):
        candidate = copy.deepcopy(valid)
        mutation(candidate)
        with pytest.raises(ValueError):
            MissionContract.from_dict(candidate)


def test_contract_expands_identical_search_cells_and_rally_task_on_every_node():
    first = MissionContract.from_dict(valid_contract_dict())
    second = MissionContract.from_dict(json.loads(json.dumps(valid_contract_dict())))
    assert first.digest == second.digest
    assert first.expand_work_units() == second.expand_work_units()
    assert sum(unit.kind == "search_cell" for unit in first.expand_work_units()) == 100
    assert first.expand_work_units()[-1].kind == "rally"


def test_loading_contract_rejects_duplicate_json_keys_and_nan(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_mission_contract(duplicate)
    nonfinite = tmp_path / "nonfinite.json"
    invalid = valid_contract_dict()
    invalid["deadline_s"] = float("nan")
    nonfinite.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError):
        load_mission_contract(nonfinite)
```

- [ ] **Step 2: Run Task 1 tests and verify RED**

Run: `python -m pytest tests/test_mission_contract.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'flydrones.mission_contract'`.

- [ ] **Step 3: Implement immutable types and exact-key validation**

Implement these public types and reject `bool` explicitly before accepting `int`/`float`:

```python
@dataclass(frozen=True)
class SafetyLimits:
    maximum_speed_mps: float
    minimum_separation_m: float
    geofence_margin_m: float
    minimum_battery_return_pct: float


@dataclass(frozen=True)
class WorkUnit:
    task_id: str
    kind: Literal["search_cell", "confirm_detection", "relay", "rally"]
    center_m: tuple[float, float, float]
    payload: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MissionContract:
    schema_version: int
    mission_id: str
    mission_type: str
    area_polygon_m: tuple[tuple[float, float], ...]
    search_cell_size_m: float
    target_classes: tuple[str, ...]
    confirmation_quorum: int
    rally_position_m: tuple[float, float, float]
    deadline_s: float
    safety: SafetyLimits

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()


def _require_exact_keys(data: Mapping[str, object], expected: set[str], where: str) -> None:
    missing = expected - set(data)
    extra = set(data) - expected
    if missing or extra:
        raise ValueError(f"{where} keys differ: missing={sorted(missing)}, extra={sorted(extra)}")


def _finite_number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{where} must be a finite number")
    return float(value)
```

Implement `from_dict()`, `to_dict()` and `expand_work_units()` in the same edit. `expand_work_units()` must rasterize the polygon bounding box at `search_cell_size_m`, retain cells whose centers are inside the polygon by an even-odd point test, sort by `(y, x)`, number them `search-0000` upward, and append exactly one `rally-final` unit. Use `Mapping` plus exact expected-key sets at both contract and safety levels; require at least three polygon vertices, positive area, positive deadline/cell size, quorum at least two, speed/separation/margin above zero and battery return percentage in `[5, 95]`. `load_mission_contract()` must use an `object_pairs_hook` that raises on duplicate keys and a `parse_constant` callback that rejects `NaN` and infinities before calling `from_dict()`.

- [ ] **Step 4: Add the canonical example contract**

Write `configs/mission_search_confirm_rally.json` with the exact example from the spec, using a `200 × 200 m` polygon so 20 m cells produce exactly 100 `search_cell` units.

- [ ] **Step 5: Run focused and regression tests**

Run: `python -m pytest tests/test_mission_contract.py -q`

Expected: all Task 1 tests pass.

Run: `python -m pytest tests/test_distributed_stress.py tests/test_distributed_px4.py -q`

Expected: existing distributed tests pass unchanged.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- src/flydrones/mission_contract.py tests/test_mission_contract.py configs/mission_search_confirm_rally.json
git commit -m "feat: define autonomous swarm mission contracts"
```

### Task 2: Lease-Based Distributed Task Consensus

**Files:**
- Create: `src/flydrones/task_consensus.py`
- Create: `tests/test_task_consensus.py`

**Interfaces:**
- Consumes: `WorkUnit` and a mission digest from Task 1.
- Produces: `AgentCapability`, `Bid`, `TaskAssignment`, `TaskLedger.add_work_unit()`, `TaskLedger.assignment()`, `TaskLedger.bid_for()`, `TaskLedger.observe_bid()`, `TaskLedger.merge_assignment()`, `TaskLedger.renew()`, `TaskLedger.expire()`, `TaskLedger.complete()` and `TaskLedger.snapshot()`.

- [ ] **Step 1: Write failing convergence, expiry and completion tests**

```python
def test_equal_bids_converge_to_lower_vehicle_id_in_every_delivery_order():
    bids = [Bid("search-0000", 7, 4.5, 0, 1.0), Bid("search-0000", 2, 4.5, 0, 1.0)]
    winners = set()
    for order in itertools.permutations(bids):
        ledger = TaskLedger(9, "a" * 64, [search_unit()], lease_timeout_s=3.0)
        for bid in order:
            ledger.observe_bid(bid, now=1.0)
        winners.add(ledger.assignment("search-0000").winner_id)
    assert winners == {2}


def test_expired_owner_reopens_task_and_completion_never_regresses():
    ledger = TaskLedger(0, "a" * 64, [search_unit()], lease_timeout_s=3.0)
    ledger.observe_bid(Bid("search-0000", 3, 8.0, 0, 0.0), now=0.0)
    assert ledger.expire(now=3.01) == ("search-0000",)
    reopened = ledger.assignment("search-0000")
    assert reopened.status == "open" and reopened.allocation_round == 1
    ledger.complete("search-0000", winner_id=4, evidence_hash="b" * 64, now=4.0)
    ledger.merge_assignment(reopened, now=5.0)
    assert ledger.assignment("search-0000").status == "completed"
```

Also test invalid mission digests, unknown task IDs, two distinct confirmation agents, and deterministic snapshot ordering.

Add a dynamic-work-unit test: inserting the same `confirm_detection` ID and identical content twice is idempotent, while inserting the same ID with a different center or payload raises `ValueError`. `add_work_unit()` accepts only the four kinds declared by `WorkUnit` and creates an `open` assignment at allocation round zero.

- [ ] **Step 2: Run Task 2 tests and verify RED**

Run: `python -m pytest tests/test_task_consensus.py -q`

Expected: collection fails because `flydrones.task_consensus` does not exist.

- [ ] **Step 3: Implement immutable consensus records**

```python
@dataclass(frozen=True)
class AgentCapability:
    vehicle_id: int
    position_m: tuple[float, float, float]
    battery_pct: float
    sensor_classes: tuple[str, ...]
    active_tasks: int


@dataclass(frozen=True)
class Bid:
    task_id: str
    bidder_id: int
    utility: float
    allocation_round: int
    created_at: float


@dataclass(frozen=True)
class TaskAssignment:
    task_id: str
    status: Literal["open", "claimed", "active", "completed", "failed"]
    winner_id: int | None
    utility: float | None
    allocation_round: int
    lease_until: float | None
    evidence_hash: str | None
    confirmers: tuple[int, ...]
```

`TaskLedger` must store one assignment per known work unit. In the same edit implement these merge rules in order: valid completed evidence dominates every non-completed record; larger allocation round dominates; within one round a larger finite utility wins; equal utility uses smaller vehicle ID; completed records merge confirmer sets without changing evidence; a 3-second expiry reopens the task with `allocation_round + 1`. Reject mission-digest mismatch before reading payload fields.

- [ ] **Step 4: Implement auditable bid scoring**

Use one documented finite score:

```python
utility = (
    100.0
    - distance_m
    - 4.0 * capability.active_tasks
    + 0.25 * capability.battery_pct
    + (20.0 if required_sensor in capability.sensor_classes else -1000.0)
)
```

For `rally`, omit the sensor term. `TaskLedger.bid_for()` returns `None` when battery is at or below the contract return threshold, the required sensor is missing, or the task is completed.

- [ ] **Step 5: Run Task 2 tests**

Run: `python -m pytest tests/test_task_consensus.py -q`

Expected: all consensus tests pass, including every bid delivery permutation.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- src/flydrones/task_consensus.py tests/test_task_consensus.py
git commit -m "feat: add lease based swarm task consensus"
```

### Task 3: Bounded Task Gossip over Real UDP

**Files:**
- Create: `src/flydrones/task_udp.py`
- Create: `tests/test_task_udp.py`

**Interfaces:**
- Consumes: JSON-compatible ledger snapshots from Task 2, mission ID/digest, full contract dictionaries and known member IDs.
- Produces: `TaskMessage`, `encode_task_message()`, `decode_task_message()`, `task_overlay_peers()`, `TaskUdpConfig`, `TaskUdpNode` with `send()`, `send_to_station()`, `poll()` and `close()`, plus `MissionTaskStation.offer()`, `MissionTaskStation.poll_accepts()` and `MissionTaskStation.close()`.

- [ ] **Step 1: Write failing wire validation and real-loopback tests**

```python
def test_task_message_rejects_oversize_wrong_hash_and_duplicate_json_keys():
    message = task_message(payload={"award": "x" * 1400})
    with pytest.raises(ValueError):
        encode_task_message(message)
    valid = encode_task_message(task_message())
    with pytest.raises(ValueError):
        decode_task_message(valid, expected_mission_id="other", expected_digest="a" * 64)
    duplicate = build_raw_task_datagram(b'{"kind":"bid","kind":"award"}')
    with pytest.raises(ValueError):
        decode_task_message(duplicate, expected_mission_id="m1", expected_digest="a" * 64)


def test_two_task_nodes_exchange_on_real_loopback_and_rate_limit_sender():
    first, second = make_real_nodes(count=2, max_messages_per_second=2)
    try:
        assert first.send("bid", {"task_id": "search-0000"}, now=1.0) == 1
        assert first.send("lease", {"task_id": "search-0000"}, now=1.1) == 1
        assert first.send("progress", {"done": 0}, now=1.2) == 0
        assert wait_for_messages(second, count=2)
        assert first.metrics["rate_limited_messages"] == 1
    finally:
        first.close()
        second.close()
```

Also test overlay peers for `N=100`, stale/out-of-order sequence rejection including `0xFFFFFFFF → 0` wrap, malformed checksum, wrong sender, and Windows `ConnectionResetError` tolerance. Add a real-loopback station test in which `MissionTaskStation.offer()` reaches every agent, every agent replies with `mission_accept`, the station observes all IDs and all sockets close cleanly.

- [ ] **Step 2: Run Task 3 tests and verify RED**

Run: `python -m pytest tests/test_task_udp.py -q`

Expected: collection fails because `flydrones.task_udp` does not exist.

- [ ] **Step 3: Implement the FDT1 wire envelope**

Use `struct.Struct("!4sBHIH32s")` for magic, version, sender, sequence, payload length and raw SHA-256 checksum, followed by canonical UTF-8 JSON. The JSON object must contain exactly `kind`, `mission_id`, `mission_digest`, `sent_at` and `payload`. Decode with `json.loads(payload_text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite)` where both callbacks raise `ValueError` on invalid input. Reject any full datagram larger than 1200 bytes.

```python
@dataclass(frozen=True)
class TaskMessage:
    kind: Literal["mission_offer", "mission_accept", "bid", "award", "lease", "progress", "evidence", "health"]
    mission_id: str
    mission_digest: str
    sender_id: int
    sequence: int
    sent_at: float
    payload: dict[str, object]
```

- [ ] **Step 4: Implement deterministic overlay and token-bucket node**

`task_overlay_peers(vehicle_id, member_ids)` must return unique existing IDs at modular offsets `-13, -7, -3, -1, 1, 3, 7, 13`, sorted numerically, excluding self. For fleets below nine, return every other member.

`TaskUdpNode.send()` canonicalizes once, sends only to overlay peers whose partition filter currently allows traffic, and consumes one token per logical message rather than per destination. Refill tokens continuously up to capacity 10. `poll()` drains nonblocking UDP, validates envelope/mission/sender/sequence, and returns messages sorted by `(sent_at, sender_id, sequence)`. Treat a sequence as newer only when `0 < ((new - previous) & 0xFFFFFFFF) < 2**31`, which permits the single wrap from `0xFFFFFFFF` to zero while rejecting old packets. Metrics must distinguish sent datagrams, received messages, rate limiting, malformed, wrong mission, out of order, partition drops and connection resets.

Reserve sender ID `65535` and port `base_port + vehicle_count` for `MissionTaskStation`. Only `mission_offer` may use that sender ID. The station sends the immutable canonical contract to each agent port before start and accepts only `mission_accept` replies whose digest matches. Worker-to-worker task gossip never includes the station in its overlay.

- [ ] **Step 5: Run Task 3 and transport regressions**

Run: `python -m pytest tests/test_task_udp.py tests/test_peer_udp.py -q`

Expected: all task and motion transport tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- src/flydrones/task_udp.py tests/test_task_udp.py
git commit -m "feat: gossip swarm tasks over bounded UDP"
```

### Task 4: Autonomous Mission Agent and Safety State Machine

**Files:**
- Create: `src/flydrones/mission_agent.py`
- Create: `tests/test_mission_agent.py`

**Interfaces:**
- Consumes: `MissionContract`, `TaskLedger`, validated task messages, local `AgentState`, local `PeerTrack` values and optional `Detection` events.
- Produces: `MissionAgent.for_contract(vehicle_id, vehicle_count, contract)`, `MissionAgent.step()`, `AgentState`, `Detection`, `NavigationIntent` and `AgentDecision`.

- [ ] **Step 1: Write failing autonomous-progress and safety-preemption tests**

```python
def test_agent_accepts_one_contract_then_progresses_without_task_station():
    agent = MissionAgent.for_contract(vehicle_id=4, vehicle_count=10, contract=contract())
    first = agent.step(now=0.0, state=healthy_state(), peer_tracks=[], messages=[], detections=[])
    assert first.phase == "auction"
    claimed = drive_consensus_until_claimed(agent, now=0.4)
    assert claimed.intent.source == "local-task-planner"
    assert claimed.central_control_commands == 0


def test_depth_freeze_and_low_battery_release_active_task_once():
    agent = active_agent()
    held = agent.step(now=1.0, state=healthy_state(depth_age_s=0.51), peer_tracks=[], messages=[], detections=[])
    assert held.intent.velocity_mps == (0.0, 0.0, 0.0)
    landed = agent.step(now=3.01, state=healthy_state(depth_age_s=2.51), peer_tracks=[], messages=[], detections=[])
    repeated = agent.step(now=3.11, state=healthy_state(depth_age_s=2.61), peer_tracks=[], messages=[], detections=[])
    assert landed.safety_phase == "land"
    assert landed.released_task_ids == ("search-0000",)
    assert repeated.released_task_ids == ()

    battery_agent = active_agent()
    decision = battery_agent.step(now=1.0, state=healthy_state(battery_pct=29.0), peer_tracks=[], messages=[], detections=[])
    assert decision.safety_phase == "return"
    assert decision.released_task_ids == ("search-0000",)
```

Also test geofence rejection, peer avoidance overriding learned intent, confirmation quorum requiring distinct IDs, completed-task monotonicity and no transition from `land` back to `execute`.

Add dynamic-task tests: a new detection creates ID `confirm-<first 12 hex characters of SHA-256(class, quantized XYZ, first evidence hash)>`; receiving the same evidence creates no duplicate. Fewer than two fresh task peers for a continuous two seconds creates one `relay-<vehicle_id>-<five-second epoch>` unit centered between the current position and rally point; repeated steps in the same epoch create no duplicate.

- [ ] **Step 2: Run Task 4 tests and verify RED**

Run: `python -m pytest tests/test_mission_agent.py -q`

Expected: collection fails because `flydrones.mission_agent` does not exist.

- [ ] **Step 3: Implement the public state and decision types**

```python
@dataclass(frozen=True)
class AgentState:
    position_m: tuple[float, float, float]
    velocity_mps: tuple[float, float, float]
    battery_pct: float
    depth_age_s: float
    localization_valid: bool


@dataclass(frozen=True)
class Detection:
    target_class: str
    position_m: tuple[float, float, float]
    confidence: float
    evidence_hash: str


@dataclass(frozen=True)
class NavigationIntent:
    velocity_mps: tuple[float, float, float]
    target_m: tuple[float, float, float] | None
    source: str


@dataclass(frozen=True)
class AgentDecision:
    phase: str
    safety_phase: str
    intent: NavigationIntent
    outbound_messages: tuple[tuple[str, dict[str, object]], ...]
    released_task_ids: tuple[str, ...]
    central_control_commands: int = 0
```

- [ ] **Step 4: Implement deterministic task and safety transitions**

`MissionAgent.step()` must execute in this order: validate/merge inbound messages; expire leases; update evidence; apply safety state; release once if degraded; bid/renew at scheduled rates; choose the highest-utility locally won task; form a preferred velocity toward its work-unit center; pass it through local separation; clamp to contract speed; emit immutable `AgentDecision`.

Safety precedence must be `emergency > land > return > degraded > nominal`. Invalid localization enters `land`; battery at/below return threshold enters `return`; depth age over 0.5 seconds emits zero velocity and starts a timer; continuous depth staleness for 2.0 seconds enters `land`. Once in `land` or `emergency`, the phase is terminal. Use the existing closest-approach helpers from `high_speed_swarm.py` only for pure geometry; do not import its global simulator loop.

- [ ] **Step 5: Run Task 4 tests**

Run: `python -m pytest tests/test_mission_agent.py tests/test_task_consensus.py -q`

Expected: all agent and consensus tests pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add -- src/flydrones/mission_agent.py tests/test_mission_agent.py
git commit -m "feat: add autonomous mission agent state machine"
```

### Task 5: Independent-Process Mission Stress Harness

**Files:**
- Create: `src/flydrones/mission_stress.py`
- Create: `tests/test_mission_stress.py`
- Create: `tools/run_mission_swarm.py`

**Interfaces:**
- Consumes: Task 1 contract, Task 3 UDP nodes, Task 4 agent and existing `UdpPeerNode` motion tracks.
- Produces: `MissionStressConfig`, `run_mission_process_trial(config) -> dict`, per-agent CSV/JSON files, `summary.json`, `report.md`, `task-timeline.png` and `trajectories.png`.

- [ ] **Step 1: Write failing six-process real-UDP integration test**

```python
def test_six_processes_finish_after_station_exit_and_reassign_failed_agent(tmp_path):
    config = MissionStressConfig(
        vehicle_count=6,
        output_dir=tmp_path,
        duration_s=8.0,
        search_columns=3,
        search_rows=2,
        failed_vehicle_ids=(2,),
        failure_at_s=2.0,
        partition_window_s=(3.0, 4.0),
        task_udp_base_port=0,
        motion_udp_base_port=0,
    )
    summary = run_mission_process_trial(config)
    assert summary["checks"]["task_station_absent_during_control"]
    assert summary["checks"]["one_process_per_vehicle"]
    assert summary["checks"]["failed_tasks_reassigned"]
    assert summary["checks"]["ledgers_converged_after_partition"]
    assert summary["metrics"]["central_control_commands"] == 0
    assert summary["metrics"]["collisions"] == 0
```

Add a second test with ten adjacent IDs removed from a 24-agent logical membership using deterministic in-process ledger exchange; assert the eight-neighbor overlay plus anti-entropy still propagates all completed records to every survivor. This directly pins the Review Focus worst case without adding a slow 24-process test to every unit run.

- [ ] **Step 2: Run Task 5 tests and verify RED**

Run: `python -m pytest tests/test_mission_stress.py -q`

Expected: collection fails because `flydrones.mission_stress` does not exist.

- [ ] **Step 3: Implement process lifecycle without a control backchannel**

```python
@dataclass(frozen=True)
class MissionStressConfig:
    vehicle_count: int = 100
    output_dir: str | Path = "results/mission-swarm-100"
    duration_s: float = 60.0
    rate_hz: float = 10.0
    search_columns: int = 10
    search_rows: int = 10
    failed_vehicle_ids: tuple[int, ...] = (8, 17, 29, 41, 52, 63, 74, 85, 91, 97)
    failure_at_s: float = 8.0
    partition_window_s: tuple[float, float] = (12.0, 17.0)
    low_battery_vehicle_id: int = 4
    depth_freeze_vehicle_id: int = 11
    sensor_fault_at_s: float = 6.0
    task_udp_base_port: int = 0
    motion_udp_base_port: int = 0
    seed: int = 20260921
```

The parent may write membership metadata, but each worker obtains the full contract from a real `mission_offer` UDP message and verifies its hash. Workers bind both UDP nodes, write `ready-N`, receive the offer, return `mission_accept` directly to the station and wait. The parent requires acknowledgements from every expected worker within 10 seconds, closes the task-station socket, records `station_closed_at`, and only then atomically writes `start.json` with a later `start_at`. Workers own their kinematic state and both UDP nodes and write logs only on exit. Fault injection is preloaded in each worker config: target workers terminate themselves at `failure_at_s`; partition filters change from mission elapsed time without parent messages.

At `sensor_fault_at_s`, the configured low-battery worker changes its local battery value to one percentage point below the contract threshold and the configured depth-freeze worker stops refreshing its local depth timestamp. Both processes remain alive so the acceptance evaluator can verify task release, `return`/`land` safety transitions and continued gossip without any parent intervention.

- [ ] **Step 4: Implement deterministic forest-search dynamics and detections**

Place agents on multiple altitude rings outside a `200 × 200 m` search grid. Each search task completes after its winner remains within 2.5 m for three frames. Seed three hidden targets in known cells; the first visit generates a detection, then a `confirm_detection` work unit whose completion requires two distinct evidence senders. Use the existing local speed/acceleration limiter and peer-track avoidance. Surviving agents enter rally after at least 95 search cells and all three targets are confirmed.

- [ ] **Step 5: Implement offline acceptance from worker artifacts**

The parent must wait for all surviving workers, then read only completed CSV/JSON files. Reconstruct assignment histories and trajectories by timestamp. Calculate completion percentage, duplicate valid winners, lease expiry-to-new-winner latency, post-partition convergence, distinct PIDs, target confirmer sets, minimum 3-D separation, UDP rates, malformed/stale rejects, low-battery/depth-failure safety outcomes and central command count. Set `accepted = all(checks.values())`; never accept based only on worker summaries.

- [ ] **Step 6: Add CLI and evidence plots**

`tools/run_mission_swarm.py` must accept `--contract`, `--vehicles`, `--duration`, `--output`, `--failed-ids`, `--failure-at`, `--partition-start`, `--partition-end`, `--low-battery-id`, `--depth-freeze-id`, `--sensor-fault-at` and `--seed`. It runs one trial, writes Chinese `report.md`, a task-state timeline, XY trajectories and prints `summary.json`. It exits `0` only when accepted and `2` for a completed but rejected trial.

- [ ] **Step 7: Run focused integration test**

Run: `python -m pytest tests/test_mission_stress.py -q`

Expected: the six-process trial passes with one process failure, a network partition and zero central control commands.

- [ ] **Step 8: Commit Task 5**

```powershell
git add -- src/flydrones/mission_stress.py tests/test_mission_stress.py tools/run_mission_swarm.py
git commit -m "feat: simulate decentralized mission completion"
```

### Task 6: Run 100 Processes, Verify the Repository and Document Evidence

**Files:**
- Modify: `docs/DISTRIBUTED_SWARM.md`
- Generate: `results/mission-swarm-100/summary.json`
- Generate: `results/mission-swarm-100/report.md`
- Generate: `results/mission-swarm-100/task-timeline.png`
- Generate: `results/mission-swarm-100/trajectories.png`

**Interfaces:**
- Consumes: `tools/run_mission_swarm.py` from Task 5 and all earlier modules.
- Produces: auditable 100-process acceptance evidence and operator documentation.

- [ ] **Step 1: Run the formal 100-process mission**

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python tools/run_mission_swarm.py `
  --contract configs/mission_search_confirm_rally.json `
  --vehicles 100 `
  --duration 60 `
  --failed-ids 8,17,29,41,52,63,74,85,91,97 `
  --failure-at 8 `
  --partition-start 12 `
  --partition-end 17 `
  --low-battery-id 4 `
  --depth-freeze-id 11 `
  --sensor-fault-at 6 `
  --seed 20260921 `
  --output results/mission-swarm-100
```

Expected: exit code `0`; 100 distinct initial worker PIDs; 90 processes survive the intentional process failures; the low-battery node enters `return`; the frozen-depth node enters `land`; at least 95 search cells complete; all targets have two distinct confirmations; zero collisions; all failed-node tasks are reassigned within 5 seconds; ledgers converge within 5 seconds after partition recovery; central command count is zero.

- [ ] **Step 2: Add exact run and interpretation documentation**

Append to `docs/DISTRIBUTED_SWARM.md`: the command above, the mission JSON schema fields, how to read the task timeline, proof that the task-station socket closes before flight start, the difference between autonomous task choice and hard safety limits, and the boundary that this is single-computer kinematic validation rather than 100 physical aircraft.

- [ ] **Step 3: Run the complete Python suite**

Run:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python -m pytest -q
```

Expected: all tests pass; the existing MaleCNS unmatched-group warning may remain, and no new warning is allowed.

- [ ] **Step 4: Run static and syntax checks**

```powershell
& "$env:APPDATA\Python\Python312\Scripts\ruff.exe" check `
  src/flydrones/mission_contract.py `
  src/flydrones/task_consensus.py `
  src/flydrones/task_udp.py `
  src/flydrones/mission_agent.py `
  src/flydrones/mission_stress.py `
  tools/run_mission_swarm.py `
  tests/test_mission_contract.py `
  tests/test_task_consensus.py `
  tests/test_task_udp.py `
  tests/test_mission_agent.py `
  tests/test_mission_stress.py

python -m py_compile `
  src/flydrones/mission_contract.py `
  src/flydrones/task_consensus.py `
  src/flydrones/task_udp.py `
  src/flydrones/mission_agent.py `
  src/flydrones/mission_stress.py `
  tools/run_mission_swarm.py
```

Expected: Ruff reports `All checks passed!`; `py_compile` exits zero without output.

- [ ] **Step 5: Perform a fresh whole-change review**

Review `git diff a64499f..HEAD` against the spec. Check parent/worker control boundaries, all message-size and rate limits, ledger monotonicity, terminal safety states, process cleanup, offline-evaluator independence and report claims. For every issue found, first add a failing regression test, then fix it and rerun the focused and complete suites.

- [ ] **Step 6: Commit final documentation and verified adjustments**

```powershell
git add -- docs/DISTRIBUTED_SWARM.md
git commit -m "docs: record autonomous mission swarm evidence"
```

Do not add generated `results/` artifacts to Git unless repository policy is changed explicitly; keep them in the workspace and link them in the final report.
