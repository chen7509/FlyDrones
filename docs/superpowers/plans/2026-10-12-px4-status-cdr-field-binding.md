# EstimatorStatus CDR field binding execution plan

User authorization already covers this offline work. Use the existing worktree/PR65 and push only `personal`.

- [x] Inspect existing structural auditor, collector and sealed three-sample ROS parity evidence; inspect official fixed message and Rosbags APIs. Confirm private pinned decoder availability; global package absence is not a test result.
- [x] Add pure-format/decoder tests and the separate offline companion, preserving historical structure-only API and source snapshots.
- [x] Add behavioral mismatch REDs (15 failed/8 passed), implement every-sample JSON-to-CDR field binding and fail-closed IO/version/definition checks, then GREEN.
- [x] Independently audit sealed normal and failed-writer records plus malformed partial-write refusal; retain every original failure and byte hash without running a source process. LF framing review repair had separate RED/GREEN; read-only final-source retained-v2 is kept alongside v1.
- [x] Run targeted24/adjacent85 passed plus one existing symlink skip, Ruff/diff, independent review with no outstanding issues; record final import/source/dependency hashes and report for evidence sealing.
- [ ] Commit/push only `personal`, update draft PR65 and continuing automation. Do not grant source, clock, fusion, capture/training or flight authority.
