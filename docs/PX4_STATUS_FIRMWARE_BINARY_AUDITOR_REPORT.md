# PX4 EstimatorStatus binary audit preparation

The isolated candidate firmware **has not been compiled**. The frozen Windows
free-memory gate requires at least 4,294,967,296 bytes; sampled observations
included 2,980,065,280 and 1,727,979,520 bytes. No build, PX4, Gazebo, Agent, estimator or training
process was started in this stage. The one-shot result directory does not exist,
so the auditor's real WSL invocation refused with
`firmware_compiled_verified=false` and `isolated_root_or_evidence_invalid`.
This is a missing build result, not a failed fruit-fly policy or failed binary.

The new read-only auditor is preparation for plan Task 3. It binds the exact
build and source profile file hashes, original preflight and dispatch records,
successful exact WSL/systemd one-job launch/exit, independently rechecked
toolchain hashes and unchanged selected source files,
graceful owned-scope release, the frozen generated `dds_topics.h` SHA-256, a
new ELF file identity and Build ID, and Ninja's
`dds_topics.h` → `uxrce_dds_client.cpp.o` →
`libmodules__uxrce_dds_client.a` → `bin/px4` dependency chain. The archive
member bytes must match the standalone object hash, and a newly generated
Ninja log must show all three outputs once in causal order. It rejects a
stale Ninja dependency record and malformed nested run metadata. Its output
keeps live-source, fusion and training authority false. The dependency closure
field also stays false: selected graph evidence does not prove that every
offline build dependency has been enumerated.

The fixed PX4 checkout's **old** September binary was only used to confirm
the location and syntax of Ninja's query/dependency records and that `ar p`
returns the same object bytes as the standalone file. Its generated
header lacks the candidate `estimator_status` publication and cannot qualify
this study. The [PX4 uXRCE-DDS guide](https://docs.px4.io/main/en/middleware/uxrce_dds)
states that `dds_topics.yaml` controls compiled client topics; the pinned
[CMake source](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/uxrce_dds_client/CMakeLists.txt)
generates the header used by this module. A header alone is still not a
binary, and a binary alone is not an authenticated live DDS source.

Synthetic audit/refusal tests and adjacent source/build-runner regression:
`103 passed`. Changed Ruff and `git diff --check` pass. The isolated Python CLI
help test passes without site packages, and WSL invocation reached the
expected missing-result refusal without importing `torch`. These checks do
not validate a real build or live receipt. Once the original 4 GiB/one-job
admission and no-contention gates actually pass, only one frozen build attempt
may run; its complete output and every failure must be retained. The binary
auditor must then be run on that attempt before any claim of compiled firmware.
No `ODOMETRY` publication, EKF2 injection, unlocking or student capture is
authorized by this stage.

The independent review found an initial real-command mismatch and two
dependency/identity gaps; all were corrected and re-reviewed. A later minor
malformed-profile exception was closed with a refusal test. The preparation
archive `evidence/px4-status-firmware-binary-auditor-dev-1701.zip` has 14
CRC-checked members, SHA-256
`9d8e9c7072f69f304d39a4c58a22e66a9d7ae54e50bb7446c7faa3136b3466ff`.
It seals tests, fixed profiles, auditor/runner source and the resource-gate
refusal. It is **not** a firmware-build archive.
