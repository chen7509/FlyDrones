# FlyDrones evidence ledger — 2026-10-01

This ledger distinguishes a working interface from an accepted flight result.
The initial audit inspected `codex/px4-sensor-readiness` at `9208a10` and the
separate, dirty `codex/fly-ego-benchmark` worktree at `18587dd`. A later,
separately labelled development SITL episode is linked below. No `AGENTS.md`
was found in either repository or their workspace ancestors. Original raw
result directories remain in place.

## Verified at the stated evidence level

| Capability | Evidence and level | Boundary |
|---|---|---|
| Five independent PX4 sensor starts | [PX4 readiness report](PX4_SENSOR_READINESS_REPORT.md): 10/10 five-vehicle starts, 50 ULogs, EKF2 and sensor subscriber checks; PX4/Gazebo SITL | A patched no-lockstep PX4 build and this host only; no real sensor or flight evidence. |
| Truth-relayed visual fusion and stale-input response | [VIO safety gate](VIO_SAFETY_GATE.md) and [degradation stress](VIO_DEGRADATION_STRESS.md): PX4/Gazebo fault injection, EKF2/ULog and command-gate sequences | External vision is relayed Gazebo pose truth. Several five-vehicle task/fault runs failed; no camera+IMU VIO. |
| Camera timing mechanism | [Camera phase report](CAMERA_PHASE_STABILITY_REPORT.md): five 10 Hz streams with phased triggers in a development run | Five-vehicle mission/readiness and 0.95 RTF gates failed; single-vehicle result cannot open the fleet gate. |
| Frozen WSL2 zero-steady-trigger capacity baseline | [Capacity report](FIVE_CAMERA_RENDER_CAPACITY_REPORT.md): three committed-byte scored RTFs 0.8695/0.8773/0.8717; hash, renderer, five PX4, ULog and cleanup evidence | Repeatability passed; 0.95 RTF failed. No one/five sustained-camera expansion or accepted 12-slot rerun. Native Linux is deferred, not passed. |
| Historical 20-world controller comparison | [Archived comparison](https://github.com/chen7509/FlyDrones/tree/codex/benchmark-evidence-audit): 926 raw files; 60 result JSON files; raw fly 0/20, guided fly 0/20, pinned EGO 2/20. All 89 frozen inputs matched the original worktree, and 87 are represented in Git; two model/readout files remain external. | Local PX4/Gazebo software-in-loop result with **Gazebo-truth odometry and camera pose supplied to both controllers**, not image+IMU VIO. No formal per-episode ULog. The GPL-3.0 comparator is pinned, but binary execution cannot be independently proven from the archive. Not an accepted safety or reproducibility gate. |
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
- The historical EGO comparator used pinned upstream ROS 2 code. Its source
  and raw evidence are now archived on a separate branch, while two frozen
  model/readout inputs remain outside Git and formal PX4 ULogs are absent.
  Preserve this result as historical evidence; do not rerun its sealed test
  worlds for tuning.

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
- Current branch full suite after correcting three legacy test expectations:
  876 passed, 1 skipped (178.28 s). The old camera, renderer and takeoff
  configurations retain their original expected hashes. Tests now confirm
  those historical configurations are stale against current sources, which
  the campaign launchers reject; passing pytest does **not** make the old
  configurations runnable or validate their historical results. Several
  expected hashes also do not match the files in the configs' last Git
  revision, so the exact historical source tree remains unverified. A new
  campaign requires newly frozen inputs and its own evidence.

The historical comparison is now separately archived on
[`codex/benchmark-evidence-audit`](https://github.com/chen7509/FlyDrones/tree/codex/benchmark-evidence-audit),
with a [reconstruction report](https://github.com/chen7509/FlyDrones/blob/codex/benchmark-evidence-audit/docs/BENCHMARK_EVIDENCE_RECONSTRUCTION.md).
Its clean-checkout audit verifies 926 archived files, 20 worlds and 60
terminal records. It also detects the two model/readout inputs that remain
outside Git and the absence of formal per-episode ULogs. This archive has not
been merged into the PX4 branch and is not a fresh experiment.

The next [ULog capture branch](https://github.com/chen7509/FlyDrones/tree/codex/benchmark-ulog-capture)
now retains a PX4 ULog for a **development** world (`1701`) and rejects ULog-free
results in new formal reports. The single fly-raw episode ended
`out_of_bounds`; its 14.2 MB ULog parsed with EKF2, state and setpoint topics,
but it used GNSS and no real VIO. The [development evidence report](https://github.com/chen7509/FlyDrones/blob/codex/benchmark-ulog-capture/docs/BENCHMARK_ULOG_CAPTURE_DEV.md)
records the hashes, tests and limitations. This is not a new formal comparison.

The [single-vehicle RGB/IMU preflight](https://github.com/chen7509/FlyDrones/pull/4)
recorded 512 timestamped RGB frames and 12,107 PX4 ULog IMU samples in a
second development episode of world `1701`. The episode ended `out_of_bounds`.
Only 484 frames overlap the ULog IMU interval: 27 early frames and one
trailing frame have no matching IMU data, so full dataset coverage **failed**.
Using the PX4 log's first lockstep time as a provisional boundary, 18 of the
early frames precede it and nine follow it but precede the first logged IMU
sample. The clean-checkout
archive audit verified all 527 raw evidence files. There is no camera/IMU
calibration, image-derived VIO estimate, or VIO fusion into EKF2; both
controllers still consume Gazebo-truth odometry. See the
[preflight report](https://github.com/chen7509/FlyDrones/blob/codex/benchmark-vio-dataset/docs/IMAGE_IMU_PREFLIGHT_REPORT.md).

The preflight PX4 startup script already defaults `SDLOG_MODE=1`, and its
logger starts before arming. The early gap is at least partly due to Gazebo
advancing before PX4 joins the existing model; changing the log mode alone
is not an evidence-backed fix. The WSL five-camera 0.95 RTF gate remains
failed. Only after VIO, PX4 fusion/safety, and capacity gates can a new
held-out comparison be frozen; no 20/100-vehicle or real-flight escalation
is supported by this evidence.

The [decision-window audit](https://github.com/chen7509/FlyDrones/pull/5)
reused the immutable raw archive. From the first to last controller-observed
frame (29.0–51.0 s), all 221 RGB frames are within the logged IMU interval,
with 5,501 IMU samples and a maximum adjacent IMU gap of 4 ms. This passes
a declared 20 ms **data-availability** check for the decision window only;
the full raw-capture gap, `out_of_bounds` task result and truth odometry
remain unchanged. Repeating the same development episode solely to repair
the historical startup frames is unnecessary.

The [published camera-info preflight](https://github.com/chen7509/FlyDrones/pull/6)
then ran one more `1701` development episode. It retained 417 RGB frames,
417 stable Gazebo CameraInfo messages, a PX4 ULog and all failures in a
434-file hash-verified archive. Its published pinhole intrinsics match the
model's nominal horizontal FOV; all 126 decision-window frames overlap the
IMU log with a maximum adjacent IMU gap of 4 ms. The task ended `collision`,
25 early raw frames lack IMU coverage, and EKF2 external-vision fusion remains
zero. This verifies camera-info acquisition, **not** optical-to-IMU rotation,
time-offset calibration or image-derived VIO. The PX4 build has local changes;
its binary hash is recorded in the
[development report](https://github.com/chen7509/FlyDrones/blob/codex/benchmark-camera-info-preflight/docs/CAMERA_INFO_PREFLIGHT_REPORT.md).
The subsequent [optical-frame preflight](https://github.com/chen7509/FlyDrones/pull/7)
used Gazebo-only static probes, without another PX4 episode. At runtime,
`camera_link` is `(0.12, 0, 0.002) m` from `base_link`; the SDF include pose
`(0.12, 0, 0.242) m` is not the runtime camera-to-base translation. Four
known colored targets independently check the candidate Gazebo-link-to-image
rotation against the measured camera intrinsics, with a maximum 0.815 px
projection residual. The 12-file raw archive and hash index were checked
from a clean checkout. This validates only the **static simulated optical
geometry**. The PX4 bridge also rotates Gazebo FLU IMU vectors into FRD, but
dynamic image/IMU time offset, frame consistency in motion, VIO initialization,
and EKF2 visual fusion remain untested. The controllers still use truth
odometry; this evidence does not resolve the five-camera 0.95 RTF gate.
Next, validate motion timing and then run a pinned upstream VIO offline on
recorded images/IMU before considering any PX4 visual-fusion claim.
