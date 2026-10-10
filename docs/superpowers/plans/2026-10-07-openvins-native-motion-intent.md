# OpenVINS native motion-intent adapter plan

- [x] Add RED tests for the exact `M` packet, strict schema, session hashes,
  option acknowledgement and pre-initialization/duplicate refusal.
- [x] Extend the Python single-worker transport and `MotionIntentGate`
  acknowledgement without adding truth or changing the two-second bound.
- [x] Add the narrow GPL-linked `OnlineManager` method and native parser/ack.
- [x] Compile against pinned OpenVINS `6948812`; freeze build and dependency
  identities and run native negative protocol checks.
- [x] Replay sealed fixed input through initialization, apply one intent, and
  retain post-intent state evidence without PX4/Gazebo.
- [x] Run focused and full regression, independent evidence checks, update the
  report/status matrix, seal evidence, commit, push and update draft PR 65.
