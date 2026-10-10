# OpenVINS feature rejection trace plan

- [x] Record fixed upstream, license, maintenance, build, local-patch and input
  identities; retain adopted and rejected approaches.
- [x] Add RED parser/auditor tests for exact fields, count conservation,
  timestamp identity, missing stages and tampering.
- [x] Build an isolated GPL diagnostic worktree and trace-only patch without
  changing estimator decisions or inputs.
- [x] Compile a separately identified native worker and run negative protocol
  checks plus an uninstrumented control.
- [x] Replay the complete sealed input once through the diagnostic worker,
  parse the actual KLT/database/MSCKF/SLAM rejection chain, and compare state
  outputs to control.
- [x] Run focused/full regression, independent audit, report/status update,
  evidence seal, commit, push and update draft PR 65.
