# Target-bearing measurement capture implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or subagent-driven-development, test-driven-development, requesting-code-review and verification-before-completion. Standing autonomous authorization applies; do not ask per-step approval.

**Goal:** Produce one actually target-bearing, multiaxis, owned PX4 camera/virtual-IMU measurement capture, then independently consume its measured artifact when the complete admitted toolchain exists.
**Architecture:** Add a distinct raw measurement dependency graph to the shared capture lifecycle. Bind a new target scene and time-only force/torque program before dispatch; retain all raw/safety/ULog/input identities. Keep every old physical/source/VIO profile unchanged and qualify nothing from design or fixtures.
**Tech Stack:** existing Python3/Gazebo8.15/SDFormat/owned PX4+Agent+wire+pidfd, existing sealed AprilGrid assets; separate pinned Kalibr1f602274 Noetic/native toolchain only after acquisition/resource freeze.
**Spec:** docs/superpowers/specs/2026-10-15-target-bearing-measurement-capture.md.

## Global constraints

Original25s/1ms/250Hz/RGBD10Hz160x120/near0.2far19.1 and each4GiB physical reserve/no competition remain. Old resource/clock/health/reset/skew/arming/LAND/RTF gates do not change. Truth is abort/audit only; no teleport/kinematic/gravity disable, frame drops/time correction or fake covariance/receipts. Every consumed attempt stays immutable. No toolchain build/solve until its separate complete resource+license+digest specification. This plan is not a dispatchable final load freeze.

## Task1: complete scene/motion/load design

- [x] Read pinned model SDF frames/inertias and current target9files; resolve complete merged semantic poses and aggregate inertia including camera/rotors. Exact source bill and instantaneous frozen-rotor coefficient limitation are retained in source-stage v3.
- [x] Create `tools/benchmark/calibration_capture_scene.py` as the source-stage scene materializer, binding the already produced target assets without regenerating/exporting a new board. Source-stage absolute target/model poses, lighting/collisions/frame conventions,25s schedule and force/torque/angular/target-clearance ceilings are frozen in v3; runtime graph/full physical study identity remains pending Task2.
- [x] Evaluate full requested corner visibility/collision bounds for startup/lift/six pulses/rest, including conservative1ms intersample bounds. No ideal renderer/projection result is called detection or measurement. Reject airborne nominal startup and incomplete designs before dispatch; all6-link inertia and per-link force requests are retained. Actual contact/dynamics/anchor deviations remain pending.
- [ ] Independent design review verifies no old scene edits/profile masquerading and all physical safety ceilings. Only then freeze the new full load/study, including exact bill and expected raw outcomes; no whole-goal qualification.

Source-stage production details: docs/TARGET_BEARING_SCENE_LOAD_PRODUCTION_REPORT.md and docs/superpowers/specs/2026-10-15-target-bearing-scene-load.md. The source-stage reviewer confirmed the v2 airborne-start defect and the new nominal-contact placement; full runtime study freeze is deliberately still pending. This checkbox is not a demand for new scene/export/validator work: next execute Task2 shared production graph and actual callback/readiness/owned-source integration.

## Task2: integrate actual raw measurement production

- [x] Add `tools/benchmark/calibration_capture_contract.py` and `calibration_excitation.py`: named typed contract/new graph, fixed schedule, actual per-linkCOM support/pure-torque Gazebo callback, successful journal/readiness anchor and latched faults. Implemented production methods; actual ECM/physics acceptance remains Task3.
- [x] Extend `capture_contract.py`/`capture_disarmed_sensors.py` with explicit new raw mode and scene selection using common lifecycle functions. Old source fan-out modes retain all native/reference requirements; new raw mode cannot use fake shadow/reference parameters or old seals. Preserve owned PX4/Agent/staged wire and mandatory diagnostic logger+owned ULog association; v4 runtime binding requires exact source-scene copies and original mapping/search coverage.
- [x] Write genuine behaviorRED against new source-stage selection and actual callback ordering/recorded partial failures before implementation; software fixtures are labeled as such. Test no force/torque on stale/armed/invalid clock or failed writer/witness; exact1ms continuity and all calls/rows retained. Independent review's legacy-wire, partial-post and invalid-collision-evidence defects each have retained genuine RED then production fixes/GREEN. No source-string or mass-only tests called physics proof.
- [x] GREEN and required adjacent capture/contract/owned-source/readiness regressions, Ruff/diff, independent review and pending-preparation seal. Do not rerun old producer/tests as primary progress; no claim native render/physical acceptance untilTask3.

Task2 software report: docs/TARGET_BEARING_RAW_PRODUCTION_REPORT.md. Concrete full runtime inventory/material/library closure and execution/binding documents, final load/study identity, resource-firstfacts and once-only physical executor remain pending before Task3. No prepared generic worker command is authorized to substitute for those prerequisites. Task1's final full-runtime freeze checkbox deliberately remains open.

## Task3: single admitted capture and source audit

- [ ] Read frozen bill/source hashes and observe fresh dual4GiB/no competition/own outputs+scopes absent. Existing actual handle only follow; no blindretry/cap increases or privilege changes. Preserve exact firstfacts even refusal.
- [ ] Dispatch once under the original physical worker/supervisor limits with the complete new graph; follow the actual handle and all owned cleanup. pidfd unavailable/denied fails closed; no low-level permission probe substituted for this source experiment.
- [ ] Independently inspect every actual frame/CameraInfo/IMU/ULog/native source-index/reset/clock/counter row, motion requested/returned/audited state, target visibility/detection and all failures. Preserve original epochs/times; missing witness or unhealthy data cannot become geometry. Publish actual result only after independent review/seal/onlypersonalPR65.

## Task4: separately freeze/build/use the actual measurement toolchain

- [ ] Research and freeze Noetic base digest, all source/dependency/license hashes, disk/network/runtime/build budgets and actual thread behavior for Kalibr1f602274. Do not dispatch the upstream mutable/unbounded Dockerfile; do not claim small AprilTag cache is a full solver. Costs are currently unknown.
- [ ] Freeze IMU intrinsic/noise/virtual interval-mean assumptions from measured evidence or declare missing prerequisites. No default/candidate YAML becomes a measured artifact. Preserve full bag/raw journal identities and all consumer/internal rejection counts; no new exporter called solve completion.
- [ ] Build/verify/execute once only within the separate admitted plan. Retain native target extraction, subpixel/pose/IMU solve, actual returned residual/coverage/covariance and upstream Jacobian/Schur observability evidence with scaling. No symmetry/mean/Hessian stand-in is accepted.
- [ ] Audit outputT_cam_imu/signed timeshift and measurement provenance, then consume the actual artifact through the existing Kalibr camera path with original+shifted health gates. Source/clock/calibration/accuracy/teacher/fusion/training/flight stayfalse unless separately qualified; failures and development vs sealed testing stay distinct.
