# Read-only ROS 2 source journal: bounded I/O fault check

The previously compiled `VehicleOdometry` subscriber was run four times in a network-isolated ROS 2 Humble container, with no publisher, PX4, Agent, Gazebo or policy process. This checks whether local journal system-call errors stop the receiver; it does not qualify a live PX4 source. The predeclared profile, shim, runner, four child exits, logs and journals are retained in `results/px4-ros2-io-fault-dev-1701` and the sealed evidence archive.

The subscriber binary was SHA-256 `7c6d7b117dc0bb54186b9b3d71692fb4a6c23125b5ea593669a4370674ea999b`, from the earlier synthetic ROS build. The image digest was `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`. The fixed `px4_msgs` and ROS/PX4 upstream versions, licenses, interface and resource choice are in [the source-journal report](PX4_ROS2_SOURCE_JOURNAL_REPORT.md). The run used one CPU, 192 MiB, 64 PIDs, no network, a one-second subscriber deadline and a 15-second outer timeout per case. The harness itself exited zero only after recording every child exit; that exit is not a subscriber pass.

| Local case | Predeclared / observed subscriber exit | Journal and independent audit |
| --- | --- | --- |
| No publisher, no injected error | 1 / 1 | Parseable `failed: no_messages`, zero samples, ineligible. |
| Partial write followed by injected `EIO` | 2 / 2 | `journal write failed`; terminal line stops after 77 bytes. Reader rejects the truncated line. |
| Injected `fsync` `EIO` | 2 / 2 | `journal fsync failed`; parseable failed terminal remains, but its storage durability is unproved. |
| Injected `close` `EIO` | 2 / 2 | `journal close failed`; parseable failed terminal remains, but exit is invalid and durability is unproved. |

The fault shim selects only the exact journal fd through `/proc/self/fd`. For the close case it performs the real close and then reports `EIO`, exercising the receiver's **reported-error handling**, not proving a real filesystem close failure or data loss. The partial-write fault occurs while writing the zero-message terminal, not during an actual CDR sample. Thus this experiment verifies those bounded receiver and reader paths, but not I/O behavior during a PX4 callback, real storage failure, an owned Agent, EKF2, camera calibration or flight. The independent reader always returns `eligible_for_live_capture=false`; a parseable terminal alone cannot establish writer exit or durability. The previous synthetic callback result still used CRLF compiler input, and the prepared exact Git-blob tree has not yet been rebuilt.

The audit script checks predeclared source/runner/subscriber hashes, all four child exits and error messages, and each journal with the product reader. Its output is `audit.json`. The adjacent source-journal/build-source suite passed **47 tests**; the audit script passed Ruff and `git diff --check` passed. The local process scan after the run found no running container or PX4/Gazebo/OpenVINS/test process. This stage did not start a competing physics or training run.

| Classification | Result |
| --- | --- |
| Verified locally | Expected exits and fail-closed reader behavior for three injected I/O errors; zero-message normal failure; retained truncated and parseable failure journals. |
| Implemented only | The existing read-only subscriber and journal reader. |
| Not tested | Real disk failure, I/O fault inside a live message callback, owned PX4/Agent DDS and ULog parity, exact-tree colcon rebuild, VIO/EKF2 integration and safety flight. |
| Existing failures | Earlier CRLF build provenance mismatch, first PX4 TIMESYNC missing the unchanged 2 s gate, and five-camera capacity 0.873 RTF below 0.95 remain open. |

This check closes the local short-write/fsync/close evidence requested by the source-journal plan. A real unarmed PX4 source trial remains gated on resource and Agent/clock preparation; the source journal still cannot feed a student corpus.
