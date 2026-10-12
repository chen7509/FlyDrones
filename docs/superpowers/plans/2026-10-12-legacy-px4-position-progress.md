# Legacy PX4 position progress repair plan

Design: `docs/superpowers/specs/2026-10-12-legacy-px4-position-progress-design.md`.

- [x] Read legacy backend and callers; confirm `Telemetry.t` refreshes without source progress.
- [x] Check official MAVLink/PX4 message and Offboard semantics; record bounded software scope.
- [x] Exploratory fake-link tests and source guard; preserve initial wrong-worktree import/API failures separately from behavioral evidence.
- [x] Complete arming-exception and realtime cleanup behavior with behavioral RED/GREEN tests.
- [x] Review source-progress/clock/identity/failure latch and delayed-backlog limitation independently; repair actionable findings.
- [x] Run final targeted/adjacent regressions (57 passed), changed-file Ruff, diff check; prepare final source hashes and all available output for sealing.
- [x] Seal 36-member evidence ZIP, verify all member bytes/CRC and final source hashes, update report, push code/evidence commit `127ccc8` only to `personal`, and update draft PR65. Do not claim physical or complete safety-loop qualification.

Publication receipt: the evidence ZIP contains the plan immediately before publication; this final checkbox update is a subsequent documentation change. The monitoring prompt continues from the remaining clock/queue/EKF2 and private publisher gaps.
