# Offline OpenVINS → pinned PX4 odometry contract

Scope: geometry, covariance and in-memory MAVLink2 serialization only. No estimator rerun, network, PX4 injection, flight permission or relaxation of public initialized. Consume PR32's sealed native predictions and preserve unavailable rows. User standing approval covers implementation and a stacked draft PR.

## Research decision

OpenVINS 69488123ed9362dd44b6f28e7f4680abbff1442b returns JPL xyzw q_GtoI, p_IinG, v_IinI, w_IinI, covariance [theta_I,p_G,v_I,omega_I]. Its left JPL update gives R_GtoI'=Exp(-dtheta_I)R_GtoI. The actual input uses PX4 sensor_combined FRD with identity IMU/body transform; no lever arm or general mounting is supported here. Let S=diag(1,-1,-1). Then position_LOCAL_FRD=S p_G; Hamilton body-to-local R=S R_GtoI^T; body velocity and angular rate stay unchanged. This local heading is arbitrary, not true North.

Pinned PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4 VehicleOdometry.msg explicitly defines orientation_variance in body coordinates. Its mavlink receiver copies covariance indices 15,18,20 directly. Therefore the supported wire profile is explicitly `px4-d6f12ad-body-tangent`: covariance order [p_LOCAL_FRD,theta_BODY_FRD,v_BODY_FRD,omega_BODY_FRD], Jacobian blocks J[p,p]=S, J[theta,theta]=I, J[v,v]=I, J[omega,omega]=I. Preserve all full-matrix cross terms in evidence; ODOMETRY carries only the two 6x6 diagonal blocks, and pinned PX4 further drops off-diagonal terms. This is not advertised as a generic Euler-angle covariance implementation: MAVLink's roll/pitch/yaw wording is ambiguous against this consumer. Test tilted attitude against finite differences of body tangent errors, and demonstrate why Euler variances differ. Future consumer/version changes need separate validation. Upstream fast covariance remains approximate and uncalibrated.

## Contract

- Strict finite state13/covariance12, quaternion norm within 1e-5, symmetric PSD covariance tolerance 1e-8, float32 representability. Normalize only within tolerance. Reject other consumer pins and mounting profiles.
- Geometry is independent of health. A successful prediction is not permission to fuse. Offline output always includes eligible_for_px4_fusion=false, even after public initialization.
- Serializer uses installed pymavlink 2.4.49 common v2, LOCAL_FRD/BODY_FRD, VIO estimator, wxyz and upper triangular covariance. No sockets. Explicit session id, clock id, fixed sample-to-wire offset, observed sample-domain time, reset event total and quality required; no defaults that invent evidence. Quality 0 is unknown, -1 is failed, 1..100 remains caller evidence rather than calibrated confidence.
- Timestamp is sample time, never arrival time. Require positive uint64 microseconds, strictly increasing at wire resolution, observed time at/after sample and within explicit age budget. Clock/session changes reject and require a newly constructed recorder. Reset total is monotonic and increments at most one per sample, wire counter wraps modulo 256. This checks supplied evidence, does not manufacture reset detection or timesync.
- Failed propagation cannot be serialized. Public false or unknown/failed quality may be encoded for disarmed file-only diagnostics but must list rejection reasons. Never claim transport/fusion eligibility. Online arrival, clock synchronization, reset producer and calibrated health remain separate dependencies.

## Acceptance

Analytic identity/yaw/roll/tilt and sign equivalence; finite-difference Jacobian including position and attitude; SPD cross-covariance and wire field roundtrip; bad inputs, stale/duplicate/regressed clocks, session changes, reset rollback/jump/wrap and unknown quality. Transform all 2030 successful fixed predictions, retain 106 unavailable entries; no invented real packet metadata. Regressions, independent review, sealed evidence/report and draft PR. No change to camera/physics, existing collision, fullfly latency or five-machine RTF failures.
