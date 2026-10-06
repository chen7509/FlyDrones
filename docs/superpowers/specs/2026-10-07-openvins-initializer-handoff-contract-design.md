# OpenVINS initializer-handoff acknowledgement contract

## Problem and fixed evidence

The immutable `study-v13/capture-v1` physical attempt stopped before its readiness anchor or any force at source sequence 649. Its last camera acknowledgement, native sequence 600 at 2.3 s, reported `internal_initialized=false`, `public_initialized=false`, `initializer_time_s=state_time_s=1.304`, no regular update and no IMU state. The current estimator-readiness validator rejects every uninitialized acknowledgement containing a non-sentinel timestamp.

Pinned OpenVINS `VioManager::try_to_initialize` explains this exact state. In synchronous mode the joined initializer worker can successfully set `state->_timestamp`, `startup_time` and `thread_init_success`, while the current call still returns `false`; `is_initialized_vio` consumes that success on the next image. The existing frozen state-diagnostics contract already calls this an `initializer_handoff_pending` state. Therefore the physical refusal is a FlyDrones acknowledgement-contract mismatch, not a VIO accuracy result, training failure or permission to use the pending state.

## Contract

An acknowledgement with `internal_initialized=false` remains unavailable for readiness, motion and fusion. It may have one of exactly two timestamp forms:

1. untouched initialization: `initializer_time_s=state_time_s=-1`; or
2. synchronous handoff pending: both timestamps are equal, finite, nonnegative and no later than the camera sample.

Both forms require `imu_state=null`, `last_regular_update_s=-1`, `public_initialized=false`, `zupt_flag_latched=false` and `has_moved_since_zupt=false`. A one-sided timestamp, mismatched or future timestamp, regular update, state vector, public claim, ZUPT claim or movement claim is rejected and latches the existing failure gate.

The handoff acknowledgement is retained only in the immutable native acknowledgement stream. It does not create an `estimator_internal_ready` journal record, does not set `first_internal` or `latest_internal`, and cannot satisfy `proof()`.

## Verification and boundary

Add a RED regression using the exact shape and 1.304 s timestamps from `study-v13`, followed by malformed inverse cases. Preserve all source ordering, acknowledgement freshness and failure-latching checks. Run focused tests and the existing state-diagnostics tests. This stage changes no OpenVINS binary, parameters, physics, workload, watchdog, PX4 path, force profile or fusion gate and performs no physical retry.
