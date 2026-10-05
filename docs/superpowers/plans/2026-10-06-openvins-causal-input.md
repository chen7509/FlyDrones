# OpenVINS causal input implementation plan

Use superpowers:executing-plans inline. Spec: docs/superpowers/specs/2026-10-06-openvins-causal-input-design.md. Existing isolated worktree, basec02b20c; standing user authorization applies. Retain evidence/workspace.

### Task 1: Versioned raw input profile and bounded causal delivery

Interfaces: PR34 v2 recorded imu/rgb/info plus explicit stream session → immutable raw profile and native-delivery schedule; no estimator, network or flight command. Independent stdout/reporting is not a qualification grant.

- [x] Save upstream source/tag/license/maintenance records and compare source noise and causal-release semantics. Expected: no runtime install or data mutation.
- [x] Add tests in tests/benchmark/test_openvins_causal_input.py before tools/benchmark/openvins_causal_input.py. Expected RED missing API; implement raw_profile and CausalInput.accept/tick/finish for GREEN.
- [x] Add tools/benchmark/check_openvins_causal_input.py for hash-verified fixed capture and synthetic refusal matrix, preserving all deliverable and unavailable inputs. Expected no estimator/physical replay, last unmatched image retained.
- [x] Run focused/full tests, commit implementation, task-done; independent review of the whole range. Fix Important/Critical once with RED→GREEN and regression.
- [ ] Write docs/OPENVINS_CAUSAL_INPUT_REPORT.md, seal code/config/source/logs/results, create stacked draft PR and update continuation.

Review Focus: hidden lookahead; clock-domain mixing; dispatch using unavailable metadata; lost/orphan/duplicate frames; unbounded buffer or silent source; false reset/health; profile mutability and data aliasing; noise density versus per-sample stddev/calibration; treating offline schedule as online VIO.
