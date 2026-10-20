# OpenVINS handoff-corrected retry preflight design

## Purpose

Create a new prepare-only package after the immutable `study-v13/capture-v1` refusal and the narrowly verified synchronous-initializer handoff correction. This stage may run one production startup preflight after committed-tree validation, but it may not create the future physical `capture-v1` target.

## Required authority

The builder accepts only:

- the exact `study-v13` package and its immutable `capture-v1` destination;
- the successful independent audit classified as `openvins-synchronous-initializer-handoff-contract-refusal`;
- the matching physical completion record with return code 2 and an empty resource scan;
- `evidence/openvins-initializer-handoff-contract-dev-1701.zip` with exact SHA-256 `7807e049a298de58c82e9073d73a8ded9fccdcaf35b5eba0527ded8f549dd5b9`, valid CRC, unique names, exact manifest membership and member hashes;
- byte identity between the external physical-attempt audit and its archived member; and
- the current handoff validator, builder, auditor, capture and fan-out sources in the runtime binding.

It rejects changed failure cause, acknowledgement, route, heartbeat reconciliation, ULog, motion, fusion, runtime coverage, cleanup completion, archive, audit, source package members, existing output/destination, competing resources or positive downstream claims.

## Frozen execution

Copy the existing contracts and generate a new handoff-correction authorization, runtime binding, execution contract and study manifest. Preserve 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGB-D, pinned vehicle/OpenVINS/native inputs, supported-motion and 26 N force profiles, 200 ms future anchor, 8 s initial readiness, 250 ms dependency stages, 2 s watchdogs, 300 s worker/supervisor bounds and all safety/fusion gates.

The output is prepare-only. Its audit must pass before and after the implementation commit. A production `--startup-preflight` may then populate only the separately named startup destination plus supervisor evidence. It must not start PX4/OpenVINS owned phases, physics, sensor capture, motion, force, ULog, arming, ODOMETRY or fusion. Startup success does not qualify a later physical run.
