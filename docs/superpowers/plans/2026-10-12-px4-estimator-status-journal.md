# Read-only PX4 EstimatorStatus journal plan

**Goal:** Make the missing EKF2 fault/status evidence observable without
granting capture or altering PX4. Follow the [design](../specs/2026-10-12-px4-estimator-status-journal-design.md).

1. [x] Audit the current one-shot status type build result and generated
   artifacts. Keep failure and cleanup evidence. Do not continue from an
   unverified or still-running build.
2. [x] Recheck fixed PX4 message/topic generator, installed ROS Humble
   serialization APIs and existing source-journal implementation; record
   exact versions, licenses, maintenance, interface and resource costs.
3. [ ] Specify a new status journal schema and executable without modifying
   the historical odometry collector. Write failing parser, source-identity,
   timestamp/sample-age, unavailable-innovation-ratio, CDR, terminal/I/O
   and legacy-regression tests first.
4. [ ] Implement the read-only C++ collector and Python auditor. Derive a
   separate sealed source tree from the verified status overlay; source must
   include every changed collector file and no preexisting build output.
5. [ ] Compile in a newly declared bounded offline container if resource and
   no-competition preflight pass. Preserve a failed attempt; never silently
   resume or label old build output as newly generated.
6. [ ] Run synthetic ROS callback/CDR parity and fault matrix under the exact
   built binary. Preserve all sample/failure journals and independently check
   source, image, type, generated output and process cleanup.
7. [ ] Run focused and adjacent regression, changed-file lint and independent
   review. Seal member hashes/CRC, report verified/implemented/untested/
   failed separately, commit and push only to `personal`, update PR65.
8. [ ] Separately plan fixed-firmware one-topic build and unarmed live receipt;
   run only when the unchanged 4 GiB physical gate and load/RTF conditions
   permit. Bind GID to owned PX4/Agent/ULog, separate DDS gaps from upstream
   loss, and map both publication and sample times before any
   downstream student capture eligibility.
