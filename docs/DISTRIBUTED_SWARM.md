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
