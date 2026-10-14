# Owned logger/source association implementation plan

> Execute inline with TDD, independent review and evidence-before-completion under existing autonomous authorization. No new task or per-step user approval. Current worktree; only personal/PR65.

**Spec:** ../specs/2026-10-14-owned-logger-source-association.md

- [x] Research actual capture spawn/step/cleanup, collector and owned identity APIs; distinguish private file collection from missing owned opener witness. Read primary procfs/PX4 logger sources; declare scope, bounds and unqualified statuses.
- [x] Write meaningful failures for missing producer, genuine matching-file association, missing witness, PID/exe changes, escaping/replaced files and exclusive sidecar; implement tools/benchmark/owned_ulog_source.py.
- [x] Add opt-in frozen contract/worker forwarding and production register/step/prestop/post-collection hooks in capture_disarmed_sensors.py. Test actual production orchestration with explicit service doubles; old path unchanged. No PX4/sim launched.
- [x] Run focused/necessary adjacent checks, independent code review, repair behavior with RED/GREEN and preserve failures. Real procfs fixture only under a separately frozen small test budget if needed, no live source qualification.
- [ ] Report implemented/verified/untested/failed separately, seal/hash/CRC, independently audit and publish only personal/PR65. Real new physical logger/source association remains pending4GiB and a newly frozen study.
