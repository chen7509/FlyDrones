# Kalibr Native Target Consumption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans plus superpowers:requesting-code-review.

**Goal:** Actual pinned native tag extraction of the sealed AprilGrid design asset.
**Architecture:** New once-only driver uses sealed upstream source and copied helpers in bounded owned compile/runtime scopes. Native wrapper emits raw detections; independent audit reports geometry and all limits/failures.
**Tech Stack:** GCC/O3/fPIC/OpenCV4.6.0/Eigen, pinned Kalibr ethz_apriltag2; Python stdlib+existing psutil/admission/scope.
**Spec:** docs/superpowers/specs/2026-10-14-kalibr-native-target-consumption.md

## Global Constraints
New independent dual1GiB reserve; compile512MiB/swap0/CPU100/pids64/300inner330outer; runtime256MiB/30inner60outer. Old2GiBCSV/PNG and4GiBphysical/fullMaleCNS/firmware unchanged. Keep O3/fPIC/source bytes; consumedEGO/cached cannotrerun. Study creation consumes attempt, exclusive first admission and all failed artifacts retained. All qualifications false.

## Review Focus
Source mutation: all40officialblob/SHA matches. Missing guard: persist refusals before creation, never repeat consumedstudy. Missing realhandle: onlyown scope/popen stop and release audit. Bad detector outputs: retainall rows/missing/duplicates/hamming/nonfinite. Native ID/pixel acceptance must not imply measured target/clock/source/calibration.

### Task1 production native driver
Files tools/benchmark/run_kalibr_target_detector.py, tools/benchmark/native/kalibr_target_detector.cpp; tests/benchmark/test_kalibr_target_detector.py.
Interfaces execute_once(record:Path)->dict; fixed STUDY and SOURCE/input constants; no dynamic resource override/retry.
- [x] Write missingdriver/refusal/source binding/compile argv tests; actual RED before driver.
- [x] Implement copied immutable source/helper/wrapper and two admissions plus separate runtimeadmission; smallsoftware GREEN/Ruff/diff, independent preflightreview before actual dispatch.
- [x] Run frozen execute-once if originaldeclared newgates fresh and no study. Followhandle only, preserve any real failure, neverblindrerun. Audit actualcompile/runtime/ELF/deps/detections/memory/release independently.
### Task2 evidence/publication
- [ ] Independent code/raw/report/ZIP audit, retain all failures/old archives, stage-specific verified/implemented/untested/failed.
- [ ] Seal and onlypersonal/PR65 publish exacthead/body; separate prepublication plan/ledger. Update heartbeat pointer, no overall completion claim.
