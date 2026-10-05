# OpenVINS odometry contract implementation plan

Use superpowers:executing-plans inline. Spec: docs/superpowers/specs/2026-10-06-openvins-odometry-contract-design.md.
Base: 21147414e7e7bde8e4f5f89e16a32fc6ee9b6957. Existing isolated worktree. Preserve evidence workspace (user requirement).

### Task 1: Offline coordinate, covariance and message contract

Interfaces: native state13/covariance12 and explicit synthetic session metadata → geometry/full covariance, file-only MAVLink2 packet and rejection reasons. No live consumer.

- [x] Capture pinned upstream source/license/package hashes and maintenance snapshot; document alternatives and resource costs before implementation.
- [x] Write failing analytic, finite-difference, covariance, clock/reset/quality and pymavlink roundtrip tests in tests/benchmark/test_openvins_odometry_contract.py; implement tools/benchmark/openvins_odometry_contract.py.40 focused Python cases plus9 WSL roundtrips/9 corruption rejections verified.
- [x] Verify sealed PR32 input SHA and convert every entry once without replaying estimator;2136 entries,2030 geometry candidates,106 unavailable,zero fusion eligible. Compatibility-fix conversion-only parity identical; no estimator rerun.
- [x] Run focused and full regression tests, Ruff and diff checks. Independent final code/evidence/report review. One Important SciPy1.10 API issue fixed RED→GREEN; final667 tests passed with2 existing warnings. No Critical/Minor.
- [ ] Seal evidence, report and create stacked draft PR; attach and update continuation automation.

Review Focus: JPL sign/direction, body-tangent versus Euler covariance; discarded cross terms visible; temporal metadata never invented from IMU lookahead; public initialized never bypassed; uint/float overflow, aliases and overwrite; no network or flight path; failed rows not silently dropped.
