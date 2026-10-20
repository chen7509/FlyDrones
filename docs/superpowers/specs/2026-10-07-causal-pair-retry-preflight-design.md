# Causal pair retry prepare-only design

## Purpose

Create and independently audit one new prepare-only study after the fixed-input exact-stamp RGB/CameraInfo stage correction. The stage must bind the immutable `study-v9/capture-v1` refusal, its independent audit and completion record, and the exact sealed pair-stage evidence archive. It must not start TestFixture, Gazebo, PX4, OpenVINS, physics, training, force, motion, ODOMETRY, or fusion.

## Required evidence

The source is the existing `study-v9` package. Its historical prepare audit must have no failures and `prepare_qualified=true`; its manifest must identify `capture-v1` as the original future destination. The current package must contain that immutable capture plus only the known capture and startup supervisor sidecars. The failed capture must remain at simulation time 10 ms with zero active/support steps and zero impulse, no ULog, closed VIO/fusion gates, and the exact pending-wall-wait refusal.

The attempt audit must be `causal-deadline-physical-attempt-audit-v2`, have no failures, classify `causal-input-same-stamp-pair-source-arrival-deadline-refusal`, qualify only the failure classification, retain the exact 250,000,000 ns limit, 258,765,752 ns pair gap and 8,765,752 ns excess, and keep every physical/runtime/VIO/fusion/flight claim false. The completion must identify the same capture, report physical execution attempted, return code 2, and show an empty post-run resource list.

The correction input is exactly `evidence/causal-pair-stage-dev-1701.zip` with SHA-256 `e6cc10331d4a466365d6508440c008700d070d2f6f9d7c9982098364dbcf8d14`. Its ZIP CRC, manifest member count and every member size/hash must verify. The provided fixed replay audit must be byte-identical to its archived member, have no failures, set `fixed_replay_qualified=true`, and keep all downstream qualifications false. A nonempty or similarly named archive is insufficient.

## Output invariants

The new package copies all prior trajectory, lazy-runtime, estimator-readiness, startup-authorization, deadline-correction and physical-refusal contracts. It adds a pair-correction authorization that records every required input by resolved identity and hash. The runtime binding adds the current builder/auditor/code and all new evidence, recomputes its complete baseline, and is independently validated.

The execution contract must retain the source values for wall and supervisor budgets, 25 s simulation duration, 1 ms physics step, 250 Hz IMU, 10 Hz 160×120 RGB-D, estimator run, source/motion/reference profiles, pinned OpenVINS inputs, native-reference hash, launch environment, trajectory policy, vehicle, force and safety arguments. Only output-local declaration paths and the never-used `capture-v1` destination may change. Every downstream qualification stays false, the destination must not exist, and no active competing resource is allowed.

## Verification and next gate

TDD first rejects the wrong attempt classification, timing drift, a modified/renamed/invalid archive, audit bytes absent from the archive, positive downstream claims, workload drift, an existing destination, and active resources. A fixed prepare-only build then receives an independent recomputation audit. The package is committed and audited again from the committed tree. Only after that may the production capture CLI run once with `--startup-preflight` at a separate destination; that preflight must stop before TestFixture/PX4/OpenVINS and cannot qualify physical execution or VIO. No physical `capture-v1` run is authorized in this stage.
