# PX4 camera file producer implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Existing user autonomy supersedes per-step approval waits.

**Goal:** Implement a real file-consuming PX4-state/camera-rig production interface while preserving all source/calibration/clock/flight qualification gaps.

**Architecture:** A bounded calibration loader binds intrinsic/extrinsic bytes; a bound ULog reader composes causal health/reset-selected state into camera poses; a write-once file CLI records every refusal. Existing live bridges and frozen build inputs remain unchanged.

**Tech Stack:** Existing NumPy/SciPy, pyulog1.2.4 in WSL, Python JSON/SHA256; no model or new global dependency.

**Spec:** docs/superpowers/specs/2026-10-14-px4-camera-file-producer.md

## Global constraints

-64KiB rig/evidence documents,16MiB ULog,100000 selected-topic rows,256 numeric scalar columns/topic,64MiB total selected-column copies,4096 frames; strictly increasing frame list.
-100ms state/status age,2s source-flag publication age and50ms state skew unchanged. Reset transition requires a new separately qualified session; no implicit rebase.
-No receipt/quality/reset/covariance fabrication, Gazebo pose, Observation/recorder/publisher/arming, full NN/optimizer, held-out tuning or old experiment overwrite.
-Outputs remain explicitly unqualified for live source, calibration, clock, capture/training and flight. User goal panel remains blocked without becoming an execution approval gate.

## Review focus

-Pre-existing linked ancestors and escaping evidence paths refuse. Require controlled static input/output directories; do not claim adversarial concurrent path replacement resistance.
-NED/FRD/optical transform direction must be checked with noncommuting rotations and lever-arm translation.
-An explicit unqualified epoch declaration must bind rig/ULog/canonical frame sequence before geometry; each row retains all four topic indices/times and source hashes.
-Source geometry must select publication-available state, not a future sample or receipt inferred from publication.
-Reset wrap/change and later stable counters must remain latched; missing counter fields cannot silently pass.
-CLI failures must retain artifacts and never overwrite an existing output directory or claim a completed live producer.

### Task1: Rig loading and production composition

- [x] Read fixed upstream message/coordinate and calibration documentation; record license/version/interface/cost/reasons. Freeze the new spec and implementation paths:src/flydrones/benchmark/px4_camera_source.py,tests/benchmark/test_px4_camera_source.py,tools/benchmark/produce_px4_camera_file.py.
- [x] Write RED for missing interface, exact-file binding/IDs/escape, transform composition, future/stale health, reset latch and byte-parsing boundary; distinguish constructed fixtures from real data.
- [x] Implement byte-bound rig and ULog loading plus actual causal camera geometry production without adding runtime authority. Run necessary focused/adjacent tests; preserve failures.

### Task2: File consumer and real development integration

- [x] Implement exclusive CLI; test failure retention/output reuse and actual producer/row publication without a live backend.
- [x] Read original development27201 ULog SHA55428c6d37e75d7fa2d53ab67a6527b4350fa020dca4a761a44fa7aec68d1028 via existing WSL pyulog. Keep simulation calibration unqualified (same-capture CameraInfo exists and is byte-identical to the actually selected historical copy; measured association is pending); run the new interface, retaining all rows/refusals, not repeating old audits as new progress.
- [x] Independent source/report/evidence review, CRC/member hashes, seal report and artifacts; publish only personal/PR65. State verified software/file behavior vs implemented/live/calibration/full-model/physical pending.

## Publication ledger (outside sealed prepublication plan)

- File-stage implementation/evidence committed; 29 focused/adjacent tests passed, Ruff/diff0.
- Actual WSL producer:251 retained rows,0 geometry, all source/clock/calibration/training/flight qualification false.
- Independent final review: no Critical/Important/Minor; canonical v2 ZIP186 members all CRC/size/SHA checked. Original182-member ZIP remains pre-correction.
- See evidence/px4-camera-file-producer-publication.json for implementation commit and exact prepublication/current plan hashes. Complete here means this file-stage only; the full goal remains incomplete.
