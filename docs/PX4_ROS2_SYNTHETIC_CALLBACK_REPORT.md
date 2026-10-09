# PX4 ROS 2 source: bounded build and synthetic callback validation

This follow-up validates the previously reviewed read-only `VehicleOdometry` subscriber in a local ROS 2 Humble container. It does **not** connect to PX4 or an owned Micro XRCE-DDS Agent. It publishes no ODOMETRY, changes no PX4 parameters, performs no training, and admits no student capture.

## Fixed inputs and actual build provenance

The fixed upstream references are PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, official `PX4/px4_msgs` commit `148bdb4b8214a4d8de83029777fe8d334c74db6f` (BSD-3-Clause), and the existing `fly-ego-benchmark:humble` image `sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`. The image provides ROS Humble rclcpp 16.0.19 and CycloneDDS RMW 1.3.5; no Agent was installed. The subscriber is the existing local C++ implementation. See [the source-journal report](PX4_ROS2_SOURCE_JOURNAL_REPORT.md) for upstream interface, maintenance, resource and adoption research.

The source archive identifies the fixed `px4_msgs` commit, but Windows line-ending conversion matters. The predeclared build profile hashed a canonical reconstruction from Git blobs under `src-canonical/px4_msgs`; the actual colcon `--base-paths src` build used `src/px4_msgs`, as the CMake cache confirms. All 255 common files have identical content after CRLF-to-LF normalization, with no missing or extra files, but **all 255 differ at the byte level**. In particular, the canonical `VehicleOdometry.msg` is SHA-256 `a528b3d0b4c1a9083a71b32c367bad71a900e959efd82b9d03a9eb0e99fe6017`; the actual built source file is CRLF SHA-256 `25fd863785f106af5b510cb4b7037a4bf5818e31c253ff73fe6ec646cfcc6c9c`. The installed message is canonical LF. The build therefore demonstrates fixed-commit **interface-text equivalence**, not byte-for-byte compilation from the declared canonical source tree. The actual built tree was not independently frozen before compilation. This provenance limit remains open for any stricter future build qualification.

The resource profile used one CPU, 768 MiB container memory and swap limits, 128 PIDs, no container network, sequential colcon and the existing image. The first profile failed before building because the canonical message bytes differed from a Windows-converted archive. The v2 command found duplicate `px4_msgs` packages; exit 1 is retained. The corrected v3 base-path build reached 26% of official message generation and hit its predeclared 600-second wall limit (exit 124); it did not report OOM or a source error. V4 retained source, flags and resource limits, extended only the wall limit to 1800 seconds, and completed both packages in 29 minutes 13 seconds (exit 0). The installed subscriber binary is SHA-256 `7c6d7b117dc0bb54186b9b3d71692fb4a6c23125b5ea593669a4370674ea999b`.

## Local callback and refusal observations

| Run | Actual result | Interpretation |
| --- | --- | --- |
| `synthetic-v1` | Shell setup stopped on an unbound ROS environment variable before pub/sub start. | Startup failure retained; no DDS conclusion. |
| `synthetic-v2` | Publisher sent 120 typed messages, but its startup took longer than the four-second subscriber deadline; subscriber recorded `no_messages`, exit 1. | Bounded start-order failure; no claim of DDS loss. |
| `synthetic-v3` | In an offline-network container, the typed synthetic publisher and subscriber exited 0. The source journal contains 60 callback CDR samples and a complete terminal. A separate generated `px4_msgs` decoder parsed all 60 and matched the selected timestamps, frames, reset, quality and synthetic position fields. | Confirms a real local ROS serialized callback and selected-field generated-type parity. It does not compare against PX4 output or authenticate its publisher. |
| `synthetic-reset-v1` | After 20 accepted samples, the publisher changed `reset_counter`; the subscriber retained the offending bounded CDR hash/bytes, wrote `source_invariant` and exited 1. | Expected fail-closed reset test. |
| `synthetic-loss-v1` | After five accepted samples, the publisher stopped; the subscriber wrote `source_silence` and exited 1. | Expected fail-closed source-loss test. |

The independent Python audit marks the normal journal complete and both fault journals incomplete; **all three remain `eligible_for_live_capture=false`**. The local CycloneDDS callback did not provide RMW sequence numbers; `observed_sequence_gap=false` means no gap was observable, not that loss-free transport was proved. The RMW receive timestamp was zero, so no RMW-to-PX4 clock relation was established. A GID is not Agent/PX4 process authentication. The standalone generated-type decoder covers selected fields of these synthetic CDRs only; the product reader still records its own missing qualifications and refuses live capture.

Independent read-only review rechecked the build cache, source trees, exits, normal and fault journals, and CDR evidence. The adjacent reader/causal-adapter suite passed 59 tests; changed-file Ruff and `git diff --check` passed. The retained [build and callback evidence](../evidence/px4-ros2-synthetic-callback-dev-1701.zip) includes profiles, all failed and successful run records, actual-source audit, selected binary/message hashes, generated-type parity, process exits, test output and archive member checks.

| Classification | Outcome |
| --- | --- |
| Verified | Fixed-commit message text equivalence, bounded ROS build, 60 local typed callbacks with selected-field generated decode, reset and source-silence rejection, 59 adjacent Python tests. |
| Implemented only | Read-only subscriber, bounded journal and independent reader. The byte-level source freeze does not cover the actual built tree. |
| Not tested | Owned Agent/PX4 DDS publication, live callback-to-ULog timing, publisher identity, camera calibration, EKF2 health, real teacher capture, hardware and flight. |
| Failed / retained | First byte-profile mismatch, v2 duplicate package, v3 wall timeout, synthetic v1 shell setup and v2 startup window; prior PX4 TIMESYNC and five-camera RTF failures remain separate. |

The next gate is an owned, unarmed Agent/PX4 trial with independently bounded process identity, clocks, source health and ULog evidence. The present build and synthetic success do not authorize such data for learning or control.
