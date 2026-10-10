# Byte-bound ROS 2 build preflight refusal

Date: 2026-10-10. The next ROS 2 subscriber build was prepared from the already fixed official `PX4/px4_msgs` Git commit `148bdb4b8214a4d8de83029777fe8d334c74db6f` and the four local collector files. The purpose was to close the earlier build's byte-level provenance gap. **No colcon build or Docker container started in this attempt.**

The original `workspace-v3` passed its 259-file byte verifier. An independent `workspace-v1` copy under `results/px4-ros2-byte-build-dev-1701` also passed before launch and after refusal. The declared image digest was the existing `fly-ego-benchmark:humble` digest `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`. The prospective [plan](superpowers/plans/2026-10-10-px4-ros2-byte-bound-build.md) kept the prior exact `colcon --base-paths src` command, one CPU, 768 MiB container memory without swap, 128 PIDs, no network and an 1,800-second outer limit. It required at least 900,000 KiB available host RAM immediately before Docker.

The initial host observation showed 1,058,744 KiB free. After the source copy and verification, the runner's actual immediate preflight measured **742,864 KiB**. It recorded no competing PX4/Gazebo/training process, no running container and the expected image/source hashes, then refused the build solely on the unchanged host-memory guard. `result.json` says `build_started=false`; there is no `launch.json` or colcon exit. This is an observed resource refusal, not a compilation failure or a passing build. The copy remains byte-verified by the source verifier; all original and new failure records are retained.

The run tool now has an opt-in `--resume-preflight` entry that re-verifies the existing independent copy and rechecks the same resource guard without copying it again. It accepts only a prior unlaunched preflight failure, reserves **one** resume atomically and refuses any earlier launch or repeated resume; the original failed record is preserved and a later preflight result has a separate name. The resume also compares the saved run profile and both source-profile copies against the fixed digest. Independent review found concurrency, mutable-pin, cleanup-query, generated-type and mutable-image gaps in the first draft; the final runner uses an exclusive reservation, launches the pinned image ID, checks cleanup-query exit, and requires hashes for selected generated `VehicleOdometry` files before any build-success classification. A separate RED/GREEN test also fixed the launch-failure accounting: if Docker process creation raises, `build_started=false` even though launch intent was recorded. These prospective launch checks are code/unit-test evidence only: the resume path has **not** launched Docker or colcon. A future attempt must first observe sufficient memory and no competing job, and must keep its own launch, build, generated-type, source-postcheck and cleanup evidence. It may not backfill the older CRLF build.

| Item | State |
| --- | --- |
| Exact prepared input and independent copy | Verified, 259 files each |
| Bounded build runner and guarded resume | Implemented; refusal path observed, resume refusal/pin paths unit-tested (13 focused/adjacent tests passed) |
| Exact-source colcon output and generated `VehicleOdometry` type | Not tested in this stage |
| Owned Agent/PX4 DDS, ULog and source clock relation | Not tested |
| Old CRLF build provenance, v6 TIMESYNC and five-camera 0.873 RTF | Historical gaps remain |

The user-facing objective remains broader: a trustworthy non-truth sensor/VIO/PX4 safety loop and full connectome learning still require their own evidence. This refusal says nothing about the fruit-fly policy's effectiveness.
