# Camera / PX4 IMU dataset production plan

> REQUIRED SUB-SKILLS: executing-plans, test-driven-development, requesting-code-review, verification-before-completion. Execute inline under existing explicit autonomy; no per-step approval. Reuse the current isolated worktree, only personal/PR65.

**Goal:** Produce actual calibration-input image/IMU files with complete raw provenance and structural refusals. Full source/clock/calibration/flight qualification remains false.

**Spec:** docs/superpowers/specs/2026-10-14-camera-px4-imu-dataset-producer.md

**Files:** src/flydrones/benchmark/camera_imu_dataset.py (bound raw parsing and streaming export); tools/benchmark/export_camera_px4_imu_dataset.py (exclusive file CLI); tests/benchmark/test_camera_imu_dataset.py and test_camera_imu_dataset_cli.py. Existing live collector/bridges/geometry producer/frozen profiles unchanged.

## Tasks

- [x] Research fixed SensorCombined API and native calibration-input format; save exact message/command/observed column metadata. Preserve publication vs gyro/accel sample distinction, FRD average semantics and no covariance invention. Windows still below4GiB; no heavy dispatch.
- [x] Write missing-interface RED and meaningful numerical/PNG/CSV/raw-journal/partial-failure cases; include differing accel/gyro times, sentinel, clipping and calibration reset latch. Distinguish constructed protocol fixtures from real pyulog parsing.
- [x] Implement bounded source reader and true dataset production. Candidate native CSV is whole-stream conditional, no failed-row filtering. Execute focused and necessary adjacent tests, Ruff/diff; retain every failure.
- [x] Run the new exporter once on actual development27201 pixels/ULog with original hashes, explicit unqualified rig/epoch inputs, exact argv/process/exit/retained output. Do not repeat the previous pose producer or any simulator probe.
- [x] Independently review source/implementation/report/complete dataset evidence, repair any behavior issue with RED first, seal immutable archives/CRC/hash manifests, publish report and only personal/PR65. Record final publication separately from the sealed prepublication plan.

## Publication ledger (outside sealed prepublication plan)

- 27 focused/adjacent tests passed4.82s; Ruff/diff0.
- Real file v1/v2 retained; v2 parent7760exit0,251PNG/6123rawIMU/6123candidateCSV; all eligibilityfalse and6frames outside IMU time range.
- Independent final code/report/1376-member archive review: no Critical/Important/Minor; CRC/size/SHA/currentbytes checked.
- See evidence/camera-px4-imu-dataset-producer-publication.json for code commit and prepublication/current plan hashes. This file-stage is complete; original full goal remains incomplete.
