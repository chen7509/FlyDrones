# Supported online VIO development study

Standing user authorization covers design and inline execution; no new approval is needed. This is an architectural integration study, not training or flight authorization.

## Question and selected approach
Run one prospectively frozen supported-ready-shadow-v1 capture, combining the existing ready-shadow-v1 source fan-out, original OpenVINS producer/config, and native fresh-reference probe. Compare public/internal estimates with matched fresh reference. Do not rebuild the estimator, adjust noise, repeat old captures, or expand process supervision.

Alternative whole-trajectory best-fit ATE can hide initial drift and adds alignment ambiguity on a nearly linear path. Select a fixed first-pose gauge and report it explicitly; do not call it best-fit ATE. Changing sensor sampling or noise would confound this study and is rejected.

## Invariants
25 s, 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGBD; unchanged body/gravity, 0.4 m two-second support lift, original 26 N 1.6-second lateral force. Actual journaled readiness selects an immutable 200 ms future anchor, within the existing 8 s bound. All existing force, source and geometric safety limits remain. Truth only feeds isolated abort and offline audit. No ODOMETRY, arming, EKF2, truth initialization or old-frame repetition.

Reuse PR36 archive 8aab46377da3016b9cdc4e595fbaf8316383a3b75cbe5e36505545e0434c30fa: exact online_probe and raw-model-zero-bias-diffusion-v1. Native reference SHA303b575e29d44bf50850ad03e3d3b865207a225e366418ec5733ed5292cc18ce. Freeze selected binaries, resolved dynamic dependencies, all directly consumed source/config/model files before/after. Validate actual installed Python bindings first.

## Offline comparison, fixed before capture
Use camera estimator state_time_s, rounded to integer ns only within 1 ns tolerance, exact-match fresh reference post_ns; never nearest-match a missing state. Preserve null/uninitialized and repeated-state rows as unavailable/stale, not fresh estimates. Require monotonic source samples and reject state regression. Select the last internal state strictly before the force anchor, no older than 200 ms, as gauge reference. If absent, report accuracy indeterminate rather than choosing a favorable later origin.

Native JPL q_GtoI corresponds numerically to Hamilton body-to-global rotation H(q). Truth quaternion is FLU-to-world; FRD-to-world is H(q_truth)*diag(1,-1,-1). Fix A=R_truth_FRD(reference)*H(q_native_reference).T; compare A*(p-p0)+p_truth0, A*v (native camera velocity is global), and A*H(q) to truth FRD. No scale fit, time shift or subsequent realignment. Report initial gravity-axis discrepancy; aligning full attitude is a diagnostic gauge, not a proof of gravity consistency.

Prospective development screens, NOT flight/EKF2 acceptance: maximum matched position error <=0.25 m, global velocity error <=0.25 m/s, relative attitude error <=10 deg, initial gravity-axis discrepancy <=5 deg. Public initialized must occur by anchor+3 s (before lateral excitation) and remain true through the final available camera; after first public row, unique matched state spacing <=200 ms and end coverage through 24.9 s. Retain full internal trajectory from initialization and assess maximum errors across it, including lift/startup. Report invariant displacement-norm difference alongside aligned errors. Missing/invalid coverage means indeterminate/failure, never success. No covariance consistency claim with uncalibrated noise or unknown reset/quality.

## Evidence and failures
Expected complete counts: 6251 IMU, 251 each RGB/info/depth, 250 native images, 6501 acknowledgements, 1250 fast targets, 25000 reference overwrite cycles, 50000 old-link rows. Heartbeat/ULog counts vary, but every observed state must be unarmed. Preserve last later_imu_missing and unavailable predictions. Capture source/consumer identities, actual receive/start/end/ack clocks, supervisor sibling journal, ULog and all failures. Native delay is not full fly-policy latency. A failed capture is retained; no blind repeat.

Existing PR47 failure/ordering and native protocol tests cover source duplication/loss/partial delivery/clock/path/processing timeout; run targeted regression before capture. Add analytic tests for gauge direction, velocity rotation, attitude error, non-unit/nonfinite/oversized values and invalid origins. Full regression and independent review precede publication. If this one run fails, document first failure and next hypothesis without tuning.
