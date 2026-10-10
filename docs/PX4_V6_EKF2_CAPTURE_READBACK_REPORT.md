# v6 physical capture: read-only PX4 EKF2 health at RGB frames

The existing v6 development capture is **not** a source-qualified student corpus. The previously sealed 25-second unarmed PX4/Gazebo/OpenVINS run has 251 RGB frames and a genuine PX4 ULog, but its PX4 estimator health is usable under the repository's existing shadow rule at **1/251** RGB frames. That sole frame is at simulation time 3.2 s and carries `cs_gnss_pos=1`, `cs_ev_pos=0`. No frame proves EKF2 external-vision fusion. The 25-second OpenVINS accuracy result remains separate: good offline VIO geometry did not mean PX4 accepted VIO as its estimator source.

This read-back pinned the old evidence ZIP SHA-256 `30d968bbc295699f4a71f8b3b552e6eeaef829221f824a1795d666a22d2b7db6` and its ULog SHA-256 `24a5f46b1bb8213b138bdd62b787e91579e8c48fb588d740c10dd716aaef4d05`. It verified all 251 original RGB-member digests before aligning their manifest sample times to the saved ULog with the existing `audit_shadow_frames()` and `audit_state_sample_times()` rules. WSL `pyulog` 1.2.4 parsed the file; the audit implementation SHA-256 is `689af9da42e65b29e06a8416927f0e13faec7508c95b682ca903ff428a95d101`. A second script independently parsed the same pinned ULog and used a direct nonfuture timestamp join for `heading_good_for_control` and source flags. It found exactly one heading-good frame, 3.2 s, with GNSS on and external vision off. This independent check corroborates the decisive status and source identity; it does not separately reimplement every health rule.

| Existing shadow-audit result | v6 observation |
| --- | ---: |
| Original RGB frames | 251 |
| PX4 local-position samples / attitude samples | 3,059 / 5,727 |
| Frame sample-time usable, under unqualified shared-simulation-epoch assumption | 230 |
| Timely estimate under publication-age screen | 230 |
| Healthy estimate under all shadow fields | 1 |
| Invalid / missing under existing classifier | 229 / 21 |
| Frames with `heading_invalid` reason | 244 |
| Source flags over all frames | GNSS 219, none 29, unknown 3 |
| Healthy source flags | GNSS 1, external vision 0 |

The initial 21 frames are missing at least one required high-frequency topic; six have no local-position sample and 21 have no attitude sample. Reasons overlap, so their counts must not be added to obtain a frame total. A timely publication or a numerically good VIO trajectory is not a healthy, source-authenticated, calibrated camera pose. The independent direct read-back confirms that only one RGB frame had PX4 `heading_good_for_control=1`; it does not explain the underlying PX4 yaw-alignment dynamics in this v6 run. The earlier [heading-pair analysis](EKF2_SHADOW_REPORT.md) identified magnetic alignment as a plausible mechanism in a different capture, not a proved cause here.

The old ULog contains no qualifying external-vision estimate, while the fixed camera extrinsic and time calibration remain simulation-development assumptions and no EGO reference trajectory was acquired. The frame/ULog epoch equivalence is not independently calibrated, receipt-time identity is absent, and neither audit emits a production observation. The output explicitly retains `clock_epoch_qualified=false`, `calibration_verified=false`, `teacher_observed=false` and `eligible_for_student_capture=false`. No historical artifact or threshold was changed; no PX4, Gazebo, Docker, OpenVINS or training process was launched. Host free memory varied from about 0.39 GiB during read-back to 1.04 GiB at the later saved preflight; a single higher reading is not a sustained resource qualification for the separate physical trial.

The next physical prerequisite is to establish a prospective unarmed PX4 EKF2 source and yaw-health record with camera/extrinsic/clock evidence, then test VIO→EKF2 acceptance and faults before any student or EGO comparison capture. With current memory, continue low-load source and health-contract work. This v6 run cannot be promoted into a valid training sequence or a fair head-to-head result.

Raw per-frame statuses, the two scripts, independent direct ULog result and audit-source copy are sealed in `evidence/px4-v6-ekf2-capture-readback-dev-1701.zip`; the original v6 archive is referenced by hash, not copied or altered.
