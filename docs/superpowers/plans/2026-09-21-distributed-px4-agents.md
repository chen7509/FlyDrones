# Independent PX4 Agents and UDP Swarm Plan

**Goal:** Run each PX4/depth/PPO controller in its own operating-system process, exchange neighbor state over real UDP without a broker, and validate the same protocol at 20 and 100 logical vehicles.

**Architecture:** A `UdpPeerNode` binds one UDP port per vehicle and sends timestamped position/velocity packets directly to every peer port. Each PX4 worker owns one MAVLink connection, one Gazebo depth subscription, one PPO actor and one UDP node. A coordinator may launch processes and aggregate logs, but it cannot read telemetry or issue flight commands. A separate process stress harness uses the same UDP packet/node implementation with kinematic agents.

**Global constraints:**

- No worker receives current peer positions from the coordinator.
- No broker or shared-memory neighbor table is allowed in the control path.
- UDP packets expire locally and are subject to range, latency, jitter, random loss and blackout.
- Every PX4 worker must land independently on success, timeout or local failure.
- The five-PX4 aggregate must retain the existing 0.10 m forest-clearance and 0.72 m intervehicle gates.
- The 20/100-node stress test must report packet rates, stale tracks, completion and collision metrics.

## Task 1: Real UDP peer transport

**Files:** `src/flydrones/peer_udp.py`, `tests/test_peer_udp.py`

- Write failing tests for packet validation, loopback peer exchange, range filtering, packet loss/blackout and stale-track expiry.
- Implement versioned UDP datagrams, one bound port per vehicle, delayed outgoing queues and receiver-local track caches.
- Verify `tests/test_peer_udp.py` and the full Python suite.

## Task 2: Independent PX4 worker

**Files:** `src/flydrones/distributed_px4.py`, `tools/px4_distributed_agent.py`, `tests/test_distributed_px4.py`

- Write failing tests using kinematic drone/depth doubles to prove one worker uses only its own telemetry, depth and UDP cache.
- Implement takeoff, mission, local PPO inference, peer exchange, landing and per-worker artifacts.
- Verify worker timeout and cleanup paths.

## Task 3: Process-only coordinator and aggregate evaluator

**Files:** `tools/run_distributed_px4_swarm.py`, `src/flydrones/distributed_px4.py`, `tests/test_distributed_px4.py`, `Start-PX4-Distributed-Swarm.ps1`

- Write failing tests for command construction and time-aligned trace aggregation.
- Implement subprocess launch, bounded wait, failure propagation and aggregate evaluation without telemetry access.
- Run five real PX4/Gazebo workers under the configured loss/blackout scenario.

## Task 4: 20/100-process UDP stress test

**Files:** `src/flydrones/distributed_stress.py`, `tools/run_distributed_udp_stress.py`, `tests/test_distributed_stress.py`

- Write failing tests for independent process completion and collision-free convergence.
- Implement logical agents using the same UDP node and local collision avoidance.
- Run 20- and 100-process trials and write JSON/Markdown reports.

## Task 5: Final verification and documentation

- Run all Python tests, Ruff, Python compile checks and Bash syntax checks.
- Generate trajectory/stress artifacts and document exact decentralization limits.
- Perform a fresh whole-change review and fix all important findings.
