# Supported online VIO implementation plan

> For agentic workers: use superpowers:executing-plans, inline execution under standing approval.

**Goal:** One reproducible, disarmed supported-motion online VIO study with honest accuracy and health evidence.
**Architecture:** Existing capture/fan-out/native worker remain unchanged; add offline fixed-gauge analysis and a frozen evidence launcher.
**Tech stack:** Python/NumPy/SciPy, pinned WSL PX4/Gazebo/OpenVINS.
**Spec:** docs/superpowers/specs/2026-10-06-supported-online-vio.md.

## Global constraints
All spec load, safety, source, truth isolation, one-run and hash invariants apply. Unknown quality/reset and uncalibrated covariance prohibit fusion authorization regardless of development screen.

## Review focus
Quaternion direction and FRD/FLU; exact time association vs stale state; failure/partial capture vs accuracy success; full source/config/binary immutability; journal and ULog retention.

## Tasks
- [ ] Research official evaluation/source/paper and record choices; check installed binding and immutable artifacts without launching physics.
- [ ] Add analytic fixed-gauge tests and observe RED; implement tools/benchmark/supported_vio_metrics.py, observe GREEN. Include finite/shape/norm/overflow refusals.
- [ ] Freeze launcher/profile/source commit; run existing fan-out/native targeted tests. Run at most one new physical capture with all required original arguments plus source fan-out and shadow config. Do not edit consumed files while running.
- [ ] Audit exact timestamps, all counts/identities, pre/post hashes, fresh truth/raw closures, accuracy/availability/timing, ULog and supervisor. Preserve partial failures without manufacturing pass flags.
- [ ] Full regression, independent branch review, report/ledger, immutable evidence ZIP, draft PR, update heartbeat with verified result and next dependency.
