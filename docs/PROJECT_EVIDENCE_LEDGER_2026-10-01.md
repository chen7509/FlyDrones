# FlyDrones evidence ledger — 2026-10-01

This ledger distinguishes a working interface from an accepted flight result.
It audits `codex/px4-sensor-readiness` at `9208a10` and the separate, dirty
`codex/fly-ego-benchmark` worktree at `18587dd`. No training or simulation was
started for this audit. No `AGENTS.md` was found in either repository or their
workspace ancestors. Raw result directories are preserved in place.

## Verified at the stated evidence level

| Capability | Evidence and level | Boundary |
|---|---|---|
| Five independent PX4 sensor starts | [PX4 readiness report](PX4_SENSOR_READINESS_REPORT.md): 10/10 five-vehicle starts, 50 ULogs, EKF2 and sensor subscriber checks; PX4/Gazebo SITL | A patched no-lockstep PX4 build and this host only; no real sensor or flight evidence. |
| Truth-relayed visual fusion and stale-input response | [VIO safety gate](VIO_SAFETY_GATE.md) and [degradation stress](VIO_DEGRADATION_STRESS.md): PX4/Gazebo fault injection, EKF2/ULog and command-gate sequences | External vision is relayed Gazebo pose truth. Several five-vehicle task/fault runs failed; no camera+IMU VIO. |
| Camera timing mechanism | [Camera phase report](CAMERA_PHASE_STABILITY_REPORT.md): five 10 Hz streams with phased triggers in a development run | Five-vehicle mission/readiness and 0.95 RTF gates failed; single-vehicle result cannot open the fleet gate. |
| Frozen WSL2 zero-steady-trigger capacity baseline | [Capacity report](FIVE_CAMERA_RENDER_CAPACITY_REPORT.md): three committed-byte scored RTFs 0.8695/0.8773/0.8717; hash, renderer, five PX4, ULog and cleanup evidence | Repeatability passed; 0.95 RTF failed. No one/five sustained-camera expansion or accepted 12-slot rerun. Native Linux is deferred, not passed. |
| Historical 20-world controller comparison | Separate `fly-ego-benchmark/results/fly-ego-comparison/formal/`: 60 result JSON files and 60 CSV rows; raw fly 0/20, guided fly 0/20, pinned EGO 2/20. All 89 freeze-manifest input files match their present SHA-256; local upstream checkout is clean at `23a8d5a191711dd65633df689bd00f55d4dea8f9`. | Local PX4/Gazebo software-in-loop result only. Its benchmark source and raw outputs are uncommitted in a separate worktree; no per-episode ULog is present. The frozen comparator is GPL-3.0. It is not a project-wide accepted safety or reproducibility gate. |
| Offline connectome infrastructure | Separate benchmark worktree: `results/connectome-training/stage-a/baseline_profile.json`, `results/connectome-training/stage-b/smoke_report.json`, and `results/connectome-curriculum-smoke/summary.json` | Stage A full 166,700-neuron inference p95 was 1.798 s against a 0.035 s gate: failed. Stage B loss improved on synthetic sequences, and the resume smoke used a tiny synthetic connectome; neither proves full-model flight learning. |

The comparison's `fly_raw` controller has no goal input; its arrival rate does
not isolate its reflex quality. `fly_guided` adds an explicit goal vector and
is a different mixed controller. Do not relabel either as a trained complete
fly swarm. The 20 worlds are an initial paired sample, not evidence of general
superiority or commercial readiness. All recorded failures remain counted.

## Implemented, not accepted

- Local task contracts, bidding/leases, failure takeover, constrained velocity
  targets, PX4 offboard interface, safety gating, and 100-process kinematic
  experiments exist. The 100-process result is not 100 PX4 vehicles.
- The resumable multi-task PPO path and `geometric-v1` reflex can run offline.
  `MaleCNSReflexBridge` checks for a live 166,700-neuron, 25,582,837-synapse
  source and zero fallback; a geometric/PPO run is never labelled a full-fly
  run. Learning speed and task gain for the live full graph are unproven.
- The historical EGO comparator runs upstream ROS 2 code in a pinned container,
  but its local source/evidence package has not been committed and its PX4 ULog
  trace is absent. Preserve this result as historical evidence; do not rerun
  its sealed test worlds for tuning.

## Untested or failed prerequisites

| Item | Current state | Needed before claiming passage |
|---|---|---|
| Stage 0 unified reproducibility | Incomplete | Unified capability/evidence matrix (this file), three fresh runs for each named baseline where feasible, and failure/missing-log rejection. WSL capacity failure must remain a failure. |
| Realistic sensor model and real VIO | Partial / untested | Camera+IMU-derived estimate through the same deployment-visible channel, calibration/time alignment, covariance, dropout/relocalization, PX4 fusion ULog; Gazebo truth excluded from controller inputs. |
| Five-camera physical simulation at real time | Failed on WSL2 | Keep five vehicles, camera load, physics and 0.95 threshold fixed; diagnose elapsed critical-path time. Do not credit slower simulation as real-time latency evidence. |
| Full fly learning and division of labor | Unproven | Real full-connectome training/evaluation with separate seeds, learning curves, inference latency, old-skill regression, task takeover and safety statistics. PPO/geometry must remain separately named. |
| Formal reproducible upstream comparison | Historical local run, evidence gap | Versioned adapter/source, upstream commit/license, immutable 60-run evidence including PX4 ULog, independent recomputation and replay; new held-out worlds only after a new freeze, never retune the 20 sealed worlds. |
| 20/100 PX4 vehicles, HITL, real flight | Untested | Prior single/five gates, host capacity or additional hardware, then staged physical/HITL/field validation. |

## Upstream research before any new sensor or baseline integration

Checked 2026-10-01. Repository activity indicates maintenance evidence, not a
guarantee of support. The full commit IDs below are candidate revisions; no
VIO candidate has been integrated or performance-tested in FlyDrones.

| Candidate | License / checked revision / activity | Interface and resource needs | Decision and adaptation cost |
|---|---|---|---|
| [EGO-Swarm](https://github.com/ZJU-FAST-Lab/ego-planner-swarm), [ICRA paper](https://ieeexplore.ieee.org/document/9561902/) | GPL-3.0; local frozen ROS 2 `23a8d5a191711dd65633df689bd00f55d4dea8f9`; upstream default HEAD `92fe9f7227b2da819133eb8e0e8c7fc000f6ae20`, last default commit 2025-03-08, not archived | ROS 2, depth-derived obstacles, odometry, goal and trajectory output; separate Docker/ROS/PX4 bridge and CPU budget | Retain as the historical navigation comparator, not as a VIO substitute. Commercial redistribution needs license review. Reusing its frozen adapter is lower cost than reimplementing its planner; current benchmark packaging and ULog gaps must be fixed before a new formal claim. |
| [OpenVINS](https://github.com/rpng/open_vins), [official docs](https://docs.openvins.com/), [ICRA paper](https://yangyulin.net/papers/2020_icra_ov.pdf) | GPL-3.0; HEAD `69488123ed9362dd44b6f28e7f4680abbff1442b`, last default commit 2025-11-30, not archived | Monocular/stereo image plus IMU, ROS 1/2 or ROS-free C++; state, covariance and camera/IMU time-offset support; OpenCV/C++ CPU and calibrated images | Candidate for a research comparison because the covariance/time interfaces fit PX4's [external-position path](https://docs.px4.io/main/en/ros/external_position_estimation). Medium-high adapter cost: camera/IMU Gazebo bridge, frame/time conversion, EKF2 and ULog validation. GPL-3.0 requires license review for a commercial deliverable. |
| [Basalt](https://github.com/VladyslavUsenko/basalt), [RA-L paper](https://www.usenko.net/pdf/usenko2020nfr.pdf) | BSD-3-Clause; HEAD `0f3b2b52c807f70ff4e2973ce253c73329eea7bc`, last default commit 2026-03-22, not archived | Stereo image plus IMU and camera/IMU calibration; C++/CMake/vcpkg dependencies, substantial CPU/RAM to measure on this host | Preferred permissive-license candidate for a future VIO integration, pending a measured dataset preflight. Higher initial build/bridge cost than the existing truth relay; do not adopt until timestamp, coordinate, covariance and real-time feasibility checks pass. |

The VIO choice is provisional. The current 160×120 depth-only capacity trial is
not a calibrated stereo/IMU VIO workload, and no candidate has been timed on
this host. OpenVINS and Basalt must receive the same recorded image/IMU data
and PX4 interface checks before either is selected for control. Upstream
project documentation and papers describe their intended algorithms, not
FlyDrones acceptance evidence.

## Verification of this audit

- Current PX4 branch targeted tests: 124 passed; Ruff on the inspected PX4,
  capacity and reflex modules passed.
- Separate benchmark-branch `tests/benchmark` plus `tests/connectome_training`:
  122 passed without launching PX4/Gazebo/training.
- Current branch full suite: 873 passed, 1 skipped, 3 failed. All three
  failures are legacy camera/takeoff config tests comparing historical frozen
  hashes against today's changed source files. Do not rewrite historical
  hashes to make them green; preserve the old evidence and define a new
  current-source gate separately.

Next independent work: package and verify the historical benchmark source and
raw evidence without overwriting it; define a new held-out acceptance run only
after its ULog and source-revision gaps are closed. In parallel, a bounded VIO
dataset/bridge preflight can proceed on one vehicle without claiming the WSL
five-camera gate passed. No 20/100-vehicle or real-flight escalation is
authorized by the present evidence.
