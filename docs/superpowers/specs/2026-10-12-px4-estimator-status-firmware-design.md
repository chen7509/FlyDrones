# Isolated PX4 EstimatorStatus firmware candidate design

## Purpose and current evidence

The checked student-capture gate needs a fresh `EstimatorStatus.filter_fault_flags`
sample from the *same owned PX4* as the episode. Fixed PX4
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4` omits that DDS publication.
The [source candidate](../../PX4_ESTIMATOR_STATUS_TRANSPORT_REPORT.md),
[offline ROS collector](../../PX4_ESTIMATOR_STATUS_JOURNAL_REPORT.md), and
[upstream generator probe](../../PX4_ESTIMATOR_STATUS_GENERATOR_REPORT.md)
are separate verified prerequisites. The generator probe establishes an exact
five-edit generated-header delta, not a firmware binary or live PX4 source.

PX4's [uXRCE-DDS guide](https://docs.px4.io/main/en/middleware/uxrce_dds)
states that `dds_topics.yaml` selects topics compiled into the client and
requires matching ROS message definitions. The fixed [CMake rule](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/uxrce_dds_client/CMakeLists.txt)
generates `dds_topics.h` from that YAML. PX4 is BSD-3-Clause and the pinned
generator/template hashes are in the generator report. Existing `px4_msgs`
must use the exact fixed `EstimatorStatus.msg` SHA-256
`44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5`;
the newer snapshot with an extra constant is not a matched source. A research
paper cannot establish which topics this fixed firmware compiles; the pinned
code and build outputs are the authority for this narrow interface question.

## Isolated build contract

Prepare a new detached WSL PX4 worktree at the fixed commit. Do not modify or
copy the existing `~/PX4-Autopilot` working tree: it has an unrelated modified
`VehicleIMU.cpp`, and its September build cannot prove a clean candidate.
Record pinned submodule commits and verify required submodules are present at
those commits. Refuse missing, dirty or drifting dependencies; do not silently
fetch a different revision. Apply only the exact candidate YAML bytes,
SHA-256 `783247c76b0af04519681d61546756522847590f0758a675154e12bd2d332e8c`.
The base YAML hash is
`7e9c730d45b22af92acfebbb81cb5de4e4a69ac0ca46b012b71ed8fa5c89cbc0`.
Unset `PX4_UXRCE_DDS_NS` during this build and pin compiler, Python, EmPy,
PyYAML, CMake, Ninja, generator/template and selected source/dependency
identities before execution.

Do one build-only `px4_sitl_default` attempt in that isolated tree, with a
90-minute wall limit, one build job and an enforced 4 GiB/one-CPU cgroup scope
using the installed WSL systemd/cgroup-v2 support. Refuse if that scope cannot
be verified; do not substitute an unbounded shell run. Require Windows and
WSL available memory each at least 4 GiB, 15 GiB free on the destination and
no simultaneous FlyDrones simulator/training or unrelated high-load test. The
actual build command must be confirmed not
to launch PX4/Gazebo. Do not start while the predeclared host-resource gate is
closed. Preserve the entire failed attempt if build or cleanup fails; any
repair needs a separately named attempt. Afterward verify the generated
`dds_topics.h` against the probe's candidate SHA-256
`bef5afc679cb23ede466cd1ce22db270d3611492ab2326a1e41ce513cbe1c4fc`,
record the build dependency graph and binary hash, and rehash all selected
source and submodule inputs. Header presence or `strings` alone cannot prove
the binary; successful exact build, stable inputs and binary identity are
required. A successful build establishes only `firmware_compiled_verified`.

## Live gate and safety boundary

Only after the build stage passes, freeze a new unarmed single-vehicle study
using the existing physical workload: 25 seconds, 1 ms physics, 250 Hz raw
IMU, 10 Hz 160×120 RGB-D, unchanged airframe, gravity, force and safety
thresholds. Keep the existing 4 GiB Windows-host-free and no-contention
physical gate. The status collector must share the owned PX4/Agent episode;
bind DDS publisher GID, PX4 and Agent process identities, exact ROS type,
publication/sample/callback clocks and ULog. Report missing, delayed,
out-of-order or dropped status messages and measure 20 Hz effective rate,
age at camera frames, CPU and RTF. Keep failures and trajectories. Do not
increase timeouts, reduce load or trim failures to pass.

This live study is read-only, without `ODOMETRY` publication, EKF2 injection,
arming or training. `source_authenticated` can become true only from the
live identity and clock evidence. Capture eligibility remains false until
separate VIO, EKF2 heading/fusion, calibrated camera, teacher and safety gates
pass. Gazebo truth never substitutes for VIO or status.

## Validation and scope

Before build: mutation/refusal checks for wrong base commit, YAML addition,
message hash, namespace, dirty/missing submodule, resource shortage, existing
process, reused result path and partial cleanup. Build: fixed generator/header
hash, clean source after, exact compiler/dependency/binary evidence. Live:
source identity, timestamp and loss audit, fail-closed timeout/restart matrix,
ULog and no-arming proof. Seal hashes and all failures; independent review the
build and live stages separately. Current verified scope ends at source
generation. Native Linux, HITL and flight remain outside this WSL2 study.
