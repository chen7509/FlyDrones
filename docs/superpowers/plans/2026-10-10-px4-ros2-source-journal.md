# PX4 ROS 2 source journal implementation plan

**Spec:** `docs/superpowers/specs/2026-10-10-px4-ros2-source-journal-design.md`.

1. [x] Pin local PX4 and matching official `px4_msgs` message blob, inspect installed Humble callback metadata APIs and resource state. Retain absence of `px4_msgs`/Agent as an explicit blocked runtime capability, not a PX4 failure.
2. [ ] Write failing journal/schema and fault tests for CDR bytes/hash, callback/metadata clocks, unsupported sequences, GID continuity, reset wrap, malformed fields, short write, duplicate and cleanup. Implement a typed, read-only ROS 2 C++ subscriber and independently verified journal reader; do not call the student recorder.
3. [x] Build fixed-commit `px4_msgs` under a bounded profile and run the local typed synthetic ROS 2 callback and source-fault cases. Retain the byte-level actual-build-tree versus canonical-manifest limit in the follow-up report; this does not qualify a live PX4 source.
4. [x] Independently review source binding and failure behavior, run targeted/adjacent tests, seal all evidence, commit and update draft PR65 through `personal` only. The review's actual-source byte mismatch is retained, not promoted to exact raw-blob build qualification.
5. [ ] Only after Agent, clock and memory prerequisites pass, predeclare a single unarmed PX4 SITL study with ULog/agent/DDS/receipt evidence. This is a separate stage; no physical study is authorized by merely completing steps 1–4.

2026-10-10 first checkpoint: Python reader and typed C++ source were implemented; 59 synthetic/adjacent tests and independent source review passed, but no C++ build ran then. `docs/PX4_ROS2_SOURCE_JOURNAL_REPORT.md` preserves that historical boundary.

2026-10-10 follow-up: after the competing process exited, bounded v4 built both ROS packages. Normal synthetic ROS callback produced 60 audited samples; reset and source loss failed closed. Independent review found the actual build consumed CRLF source while the predeclared manifest hashed canonical LF Git blobs; the text matches after newline normalization, but raw-byte build provenance remains limited. `docs/PX4_ROS2_SYNTHETIC_CALLBACK_REPORT.md` and its evidence archive give the precise results. Step 2 remains open for runtime short-write/cleanup fault testing. Step 5 is still unstarted.
