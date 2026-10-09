# PX4 ROS 2 source journal implementation plan

**Spec:** `docs/superpowers/specs/2026-10-10-px4-ros2-source-journal-design.md`.

1. [x] Pin local PX4 and matching official `px4_msgs` message blob, inspect installed Humble callback metadata APIs and resource state. Retain absence of `px4_msgs`/Agent as an explicit blocked runtime capability, not a PX4 failure.
2. [ ] Write failing journal/schema and fault tests for CDR bytes/hash, callback/metadata clocks, unsupported sequences, GID continuity, reset wrap, malformed fields, short write, duplicate and cleanup. Implement a typed, read-only ROS 2 C++ subscriber and independently verified journal reader; do not call the student recorder.
3. [ ] Build official fixed `px4_msgs` under a prospectively bounded resource profile when host memory permits. Compile and run a local synthetic ROS 2 publisher/subscriber with exact type; keep any OOM/build failures. Freeze image/package/executable hashes.
4. [ ] Independently review source binding and failure behavior, run targeted/adjacent tests, seal all evidence, commit and update draft PR65 through `personal` only.
5. [ ] Only after Agent, clock and memory prerequisites pass, predeclare a single unarmed PX4 SITL study with ULog/agent/DDS/receipt evidence. This is a separate stage; no physical study is authorized by merely completing steps 1–4.

2026-10-10 checkpoint: Python reader and typed C++ source are implemented; 59 synthetic/adjacent tests and independent source review passed. Steps 2–4 remain unchecked because the C++ writer is not compiled or callback-tested and the source package is not built in the low-memory, concurrently busy host. `docs/PX4_ROS2_SOURCE_JOURNAL_REPORT.md` separates those levels of evidence. Resume at the bounded fixed-commit ROS build when resources permit; do not infer a live capture producer from this checkpoint.
