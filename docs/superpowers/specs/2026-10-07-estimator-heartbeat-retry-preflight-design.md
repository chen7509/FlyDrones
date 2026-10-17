# Estimator-heartbeat retry prepare-only design

## Purpose

Create and independently audit one new prepare-only package after the fixed-input estimator/heartbeat routing correction. The first generated `study-v12` passed its initial audit, then was deliberately disqualified when Ruff normalized a declared builder import block and its baseline no longer matched. It remains retained evidence and is never refreshed in place. `study-v13` is the fresh authoritative candidate generated after that code stabilized. This stage may run one production `--startup-preflight` at a separate destination, but it must not create or run either physical `capture-v1`, construct TestFixture physics, start PX4/OpenVINS, apply force, train a policy, publish ODOMETRY, arm, or open the fusion gate.

## Required immutable inputs

The source is the complete `study-v11` package. Its post-startup audit must be `causal-pair-physical-retry-audit-v1`, have no failures, qualify only preparation, and retain all physical/runtime/VIO/fusion/flight claims false. The source package must contain the exact base declarations plus its known startup and capture directories and supervisor sidecars; no unknown member is accepted.

The failed capture must remain `capture_failed` at simulation time 1.520 s with source profile `ready-shadow-heartbeat-estimator-v1`, source sequence 426 refused after shadow and before readiness with `invalid source sample`, one independently observed but unreconciled heartbeat, no motion/force/anchor, closed VIO/fusion gates, PX4 exit zero, and one valid nonempty ULog. The independent audit must be `estimator-heartbeat-routing-audit-v1`, have no failures, classify `estimator-ack-routing-heartbeat-without-sample-refusal`, keep fruit-fly/training/VIO/fusion claims false, and match the same capture. The physical completion must identify the same destination, report return code 2 and no remaining resource.

The correction archive is exactly `evidence/estimator-heartbeat-routing-dev-1701.zip`, SHA-256 `e3a339d93bf7864919bd2733a890669ff85288d05941e6eb56ea2b3b50320017`. Its ZIP CRC, unique names, stage/schema, manifest member count, every member size/hash and the archived independent audit bytes must verify. A similarly named archive, an audit copied from elsewhere, or a positive downstream claim is rejected.

## Output and verification

Copy every earlier immutable authorization contract, including the pair correction. Add one heartbeat-routing authorization recording source manifest/audit, failed result, completion, correction audit and archive by resolved identity and hash. Extend the runtime inventory with the current builder, auditor, routing code, authorization and evidence; recompute the complete baseline. Recompute the command from the source execution contract and require all workload/profile/input/hash fields to remain unchanged. The only permitted changes are output-local declaration paths and the new never-used `study-v13/capture-v1` destination.

TDD rejects wrong failure shape, motion/fusion drift, missing ULog, wrong completion, renamed/modified archive, manifest/member/audit drift, positive claims, active resources, workload drift and an existing destination. After the prepare-only audit passes, commit and re-audit the committed tree. A production startup preflight may then run exactly once at `study-v13/startup-preflight-v1`; its audit must retain the absence of PX4, OpenVINS, physics, ULog, motion and fusion. This stage does not authorize a physical retry.
