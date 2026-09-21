# Independent swarm agents over UDP

This prototype runs one controller process per vehicle. Each five-aircraft PX4 worker owns exactly one MAVLink connection,
one Gazebo depth-camera subscription, one local policy instance and one UDP endpoint. The launcher supplies only static
configuration. It does not receive live telemetry or issue flight commands; it reads worker artifacts after every process
has exited.

## Run the five-PX4 forest trial

From PowerShell:

```powershell
.\Start-PX4-Distributed-Swarm.ps1
```

The result is written to `results/px4-sitl-five-process-udp`. Every worker produces its own CSV, JSON and stdout/stderr
logs. `summary.json`, `flight.csv`, `trajectory.png` and `五进程去中心化报告.md` are offline aggregate artifacts.

## Run the process and UDP scale trial

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
python tools/run_distributed_udp_stress.py --vehicles 20,100 --duration 12 --rate 10
```

This starts 20 and then 100 operating-system processes. Each process integrates only its own kinematic state and receives
neighbor tracks from its own `UdpPeerNode`. A synchronized start file is static trial coordination, not a live control
channel. The parent computes collision and completion metrics only after all workers exit.

## Communication model

- Direct UDP unicast; one bound port per vehicle and no message broker.
- Versioned binary position/velocity datagrams.
- Receiver-local range filter, track cache and stale-track expiry.
- Configurable latency, jitter, random packet loss and communication blackouts.
- A peer closing its UDP port is treated as loss of that peer, including Windows `WSAECONNRESET` behavior.

## Verified result and boundary

The recorded five-PX4/Gazebo run used five distinct controller PIDs. All five vehicles escaped the forest, rallied and
landed with zero tree contacts. The 20- and 100-process kinematic trials completed with one distinct PID per vehicle,
all 120 logical vehicles arriving, zero collisions and no direct global-neighbor reads in the control path.

The 20/100 trials validate process isolation, the local avoidance interface and UDP load on one computer. They do not run
100 PX4 physics instances and do not model real radio contention, GNSS error, actuator faults or aerodynamic interaction.
The navigation policy is a trained forest PPO actor combined with fly-inspired visual and safety logic; it is not a full
biophysical simulation of every fruit-fly neuron. Real commercial flight still requires staged hardware-in-the-loop and
outdoor tests, geofencing, an independent emergency stop, redundant localization and the applicable aviation approvals.

## Run five consecutive hybrid-planner trials

The hybrid controller treats the learned forest policy as a preferred direction. A deterministic two-second local
trajectory planner makes the final horizontal decision from each vehicle's own depth camera, rolling obstacle memory and
UDP peer position/velocity tracks. Run the complete repeatability gate from PowerShell:

```powershell
.\Start-PX4-Hybrid-Swarm.ps1
```

Each repetition starts five fresh PX4/Gazebo instances, uses a unique UDP port range, and writes worker-owned artifacts
to `results/px4-hybrid-repeatability/run-1` through `run-5`. The aggregate files are
`results/px4-hybrid-repeatability/summary.json` and `report.md`.

Acceptance requires five consecutive complete passes. Every documented run check must pass, the planner P95 must remain
below 20 ms, and `central_control_commands` must remain zero. The logs include the chosen trajectory, rejected unknown,
static and peer candidates, predicted clearances, and per-step planner time. Any failed startup, navigation, separation,
planner-performance or infrastructure check resets the consecutive count.

This is software-in-the-loop validation on one computer. It exercises real PX4 processes, Gazebo dynamics, depth topics
and loopback UDP, but it does not reproduce physical radio contention, GNSS multipath, aerodynamic interaction, hardware
timing, motor failure or aviation approval. Hardware-in-the-loop and progressively larger geofenced outdoor tests remain
necessary before physical fleet use.

## Run the autonomous 100-agent mission

This trial adds decentralized task choice above the existing local flight and avoidance layer. From PowerShell:

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

The mission contract contains a schema version and mission ID, a bounded area polygon and search-cell size, target
classes and confirmation quorum, one rally position, a deadline, and hard limits for maximum speed, minimum separation,
geofence margin and return battery percentage. It deliberately contains no per-aircraft waypoint list. Unknown fields,
duplicate JSON keys, non-finite values and unsupported mission types are rejected before a worker can accept the mission.

The task station repeatedly sends the immutable contract and collects a matching SHA-256 acknowledgement from every
worker. It then closes its UDP socket and records `station_closed_at`; only afterwards does the launcher atomically write
the start marker with `start_at`. The acceptance evaluator requires `station_closed_at < start_at`. During control, each
worker chooses tasks from its local ledger, renews three-second leases, resolves conflicting bids deterministically and
uses bounded peer-to-peer UDP gossip. The parent reads no live state and the recorded central command count must remain
zero.

Learning or local task scoring may choose which open task to attempt and may propose a velocity. Deterministic safety
rules retain final authority: stale depth stops forward motion and then lands, low battery releases the lease and returns,
invalid localization lands, speed is clamped, and fresh physical-peer tracks enforce separation. A task decision cannot
override these limits.

`task-timeline.png` shows each worker's local task-state changes over mission time; dense vertical bands correspond to
auctions, injected failures, partition recovery and terminal anti-entropy. `trajectories.png` shows the offline XY paths.
The per-agent JSON files are the source evidence; `summary.json` and `report.md` are calculated only after workers exit.

The verified run on 2026-09-21 used 100 distinct worker PIDs. Ten configured workers exited, all 90 survivors continued,
100/100 search cells completed, all three targets obtained two distinct confirmations, every surviving ledger converged,
and no central control command was issued. All ten tasks held by failed workers were reassigned; the maximum observed
reassignment latency was 3.000 s. There were zero collisions and the minimum observed 3-D separation was 3.481 m
against a 3 m contract minimum. The task layer transmitted 76,763 UDP datagrams while enforcing a per-agent limit of
10 actual task datagrams per second and a 1,200-byte maximum. The offline evaluator accepted every required check.

This is a single-computer kinematic and real-loopback-UDP validation. It does not represent 100 physical radios, 100 PX4
physics instances, aerodynamic interaction, GNSS multipath, motor failure or legal approval for a commercial show. The
next validation level is hardware-in-the-loop with real autopilots, followed by small, geofenced outdoor groups under an
independent emergency-stop system.
