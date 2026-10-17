# PX4 EstimatorStatus ROS type build

## Result and evidence

The single declared offline Docker build completed with `docker_exit=0` in
2,346.906 seconds. `colcon` reported both `px4_msgs` and
`flydrones_px4_ros2_source` finished. The installed
`EstimatorStatus.msg` SHA-256 is
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`,
matching the fixed PX4 message and the source overlay. Generated IDL, C++
struct, C++ type-support header and type-support library were present and
their hashes were recorded in the run result. The 260-file source verifier
matched before copy, after copy and after build. The Docker daemon identity
was unchanged and the owned container was absent after exit.

The run used image ID
`sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a`,
one CPU, 768 MiB memory/no swap, 128 PIDs, no network, and the frozen
sequential `MAKEFLAGS=-j1` command. Its preflight recorded 1,626,772 KiB
host free memory, above the unchanged 900,000 KiB **offline type-build**
minimum. That is not the separate 4 GiB PX4/Gazebo physical-trial gate.

The build log emitted two short clock-skew warnings (0.094 and 0.23 seconds,
"build may be incomplete") from generated Rust/Python files. The build
exit and the specifically audited installed status type passed; no claim is
made that every generated interface has been independently exercised.

The one-shot evidence archive is
[`evidence/px4-status-ros-type-build-dev-1701.zip`](../evidence/px4-status-ros-type-build-dev-1701.zip),
SHA-256 `28810aeb46fdfba7879ec5dabbc0735405260ca1968dff3410c85237671571ff`.
It contains 18 members, including the declared command, preflight, source
verification records, raw build log, final result, pinned source seals and
generated status artifacts. The sealer independently rehashed all 260 source
files against the pinned parent archive, checked the full run profile and
runner success conditions, verified member CRC/size/SHA-256 and published
the ZIP only after verification. A separate read-only archive check repeated
the member-set, CRC, size and SHA-256 checks.

## Validation and limits

Focused runner tests: 20 passed. Runner plus adjacent source/build tests:
72 passed, one Windows symlink-permission skip. Thirteen additional sealer
integrity tests passed, including a tampered source file and a missing
failure log. Changed-file Ruff and
`git diff --check` passed. Initial validation commands failed because the
host Python invocation lacked this checkout's `src` path and because `ruff`
was not a shell command; the corrected in-process pytest and `python -m ruff`
commands passed. The independent sealer review found no remaining Important
or blocking issue after strict source, failure-log and publication fixes.

**Verified:** the offline matching ROS status message type was generated and
its selected artifacts sealed. **Implemented only:** a one-shot build runner
and integrity sealer. **Untested:** a status publisher/subscriber, CDR parity,
live uXRCE-DDS status topic, PX4 firmware candidate, Agent/PX4/ULog identity
binding, EKF2 health and VIO fusion. **Not authorized by this evidence:**
ODOMETRY injection, arming, training, five- or twenty-drone qualification.

Fixed PX4 `d6f12ad` still lacks `/fmu/out/estimator_status` in its compiled
DDS topic configuration. This build does not change the firmware. The next
stage is the separately specified read-only status journal with synthetic
CDR and fault validation; a live trial must wait for a pinned firmware build
and the unchanged physical resource gate. The historical first-TIMESYNC
failure, five-camera 0.873 RTF shortfall, and previous build failures remain
independent evidence and were not overwritten.
