# EGO whole-trajectory observation plan

Use executing-plans inline, TDD and requesting-code-review under existing user blanket approval. Keep existing worktree/PR65, push onlypersonal.

- [x] Inspect pinned EGO Bspline/traj_server, current bridge and build admission; record source/license/interface/maintenance/resource choices before code.
- [x] Independent payload tests and two observed behavior RED cases, curve/interior/knots/yaw/start differences, strict journal raw/decoded binding, duplicates/incomplete/failed outputs, clock and I/O refusals. Bootstrap/dependency/fixture failures are separately labelled; actual DDS loss coverage remains unproven.
- [x] Implement separate read-only observer with no publisher and bounded lifecycle; pure payload auditor/comparator; preserve existing bridge and upstream patch bytes.
- [x] Verify real rosbags codecs against pinned message and synthetic raw transport;33focused/171affected, lint/diff, independent review/corrections. One declared actual Humble serialization-only codec probe passes3cases, no Node/PX4/planner; no memory-gated full build here.
- [ ] Seal code/research/failed tests/final results/report with per-member hashes/CRC; publish personal/PR65 and update continuation. Runtime numerical equivalence remains pending; full goal active.
