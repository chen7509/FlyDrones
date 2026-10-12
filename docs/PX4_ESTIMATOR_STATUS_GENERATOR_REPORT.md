# PX4 EstimatorStatus topic generator: source-only probe

The pinned PX4 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` checkout was
read, not modified. Its `dds_topics.yaml` (`7e9c730d...5c89cbc0`) omits
`/fmu/out/estimator_status`. The previously frozen candidate adds exactly that
publication with `px4_msgs::msg::EstimatorStatus` and `rate_limit: 20.`; the
existing source preflight again returned `source_candidate_ready=true` and
all runtime, fusion and training qualifications false. The candidate YAML
SHA-256 is `783247c76b0af04519681d61546756522847590f0758a675154e12bd2d332e8c`.

The fixed upstream `generate_dds_topics.py` and `dds_topics.h.em` are clean at
that commit, with SHA-256
`107bc83c587dff56b5260f3f1d9ec9f2fa722629cc7155a68bb203052da77e98`
and `156e9a096db3321689185a6f791a1392cca75b854bbc4f04b54f1076ced43256`.
They carry PX4's BSD-3-Clause notice. The unchanged `EstimatorStatus.msg` is
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`.
The prior [transport report](PX4_ESTIMATOR_STATUS_TRANSPORT_REPORT.md) records
PX4 and `px4_msgs` maintenance observations, ROS message mismatch and
adaptation cost. PX4's [official bridge guide](https://docs.px4.io/main/en/middleware/uxrce_dds)
states that YAML topics are compiled into the client at build time and the
ROS definitions must match the firmware. The fixed [generator source](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/uxrce_dds_client/generate_dds_topics.py)
and [CMake rule](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/uxrce_dds_client/CMakeLists.txt)
were inspected before this probe. Reusing the upstream generator costs a
short Python/EmPy run and does not add a package or approximate PX4's bridge.

With `PX4_UXRCE_DDS_NS` unset, one upstream generator invocation used the
original YAML and another used the candidate. Outputs were written only to
independent directories under `results/px4-status-topic-generator-dev-1701`.
Both commands exited 0. The base header SHA-256 is
`7f67c418df4254aea600b320b987943c13d8e2d17f868a87789e9af053a3d04c`;
the candidate header is
`bef5afc679cb23ede466cd1ce22db270d3611492ab2326a1e41ce513cbe1c4fc`.
An independent byte and line-opcode audit found exactly five edits: two
`estimator_status` includes, one size assertion, `send_subscriptions[27]` to
`[28]`, one nine-line status subscription, and `fds[27]` to `[28]` (the five
edit *groups* include both includes together). The new subscription names
the exact ROS type and `/fmu/out/estimator_status`, serializes with
`ucdr_serialize_estimator_status` and uses the generated `1e3 / 20.0` interval.
No other generated header line changed. This is a code-generation result,
**not** a compiled PX4 binary or a measured 20 Hz stream.

The first independent audit script exited 1 because it used list equality to
count a substring; the generated header itself had one matching line. That
failure and the corrected `audit-v2.json` are retained. A sealer preflight
comparison also initially disagreed because in-memory edit tuples were
compared directly with JSON arrays; the audit was normalized without rerunning
the generator, and both comparison outcomes were retained. An initial upstream
copy command also failed before copying because a shell variable was lost
across the Windows/WSL invocation; the direct-path copy succeeded and the
original failure log remains. The fixed checkout has an unrelated modified
`VehicleIMU.cpp`, so it must not be used as a supposedly clean firmware
build. The four generator inputs were clean and rehashed before and after.

The local evidence archive `evidence/px4-status-topic-generator-dev-1701.zip`
contains source copies, both generated headers, raw command logs, the unified
diff, preflight, failed/corrected audit and a per-member hash manifest. Its
SHA-256 and CRC check are recorded separately after one-shot publication.

**Verified:** fixed-source generation and the exact generated-header delta.
**Implemented only:** the already frozen one-topic YAML candidate; no PX4
checkout or firmware code was changed here. **Untested:** a clean isolated PX4
firmware build, actual Agent/ROS receipt, GID/PX4/ULog binding, sample age,
packet loss, CPU/RTF cost, EKF2 fusion, arming or training. **Still failed or
closed:** the prior first-TIMESYNC two-second miss and five-camera 0.873 RTF
below 0.95. The current Windows host had about 2.24 GiB free, below the
unchanged 4 GiB physical-trial gate, and another test process was active; no
PX4/Gazebo/Agent or model training run was started.

The next step is an isolated fixed-commit firmware build with the single YAML
addition and exact ROS type, then an unarmed one-topic live receipt only when
the existing resource and no-competition gates pass. The live study must
cross-check PX4/Agent identity, DDS GID, timestamp/sample age, ULog and
original physical load before status can inform capture eligibility.
