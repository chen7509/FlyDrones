# Capture Startup Preflight Design

## Purpose

Catch execution-entry drift before another PX4/Gazebo/OpenVINS attempt. The preflight must run the real capture CLI and worker through environment transport, scene extraction, generated-file verification, resource lookup, and `RuntimeBinding.start`, then stop before importing `TestFixture` or starting PX4, OpenVINS, force, motion, or ULog collection.

## Contract

- `--startup-preflight` is an opt-in hidden capture flag and requires the runtime binding, execution declaration, and trajectory policy.
- The parent uses the existing owned-process-group supervisor and exact declared child environment.
- The worker executes the ordinary pinned-input and active-resource checks, copies the frozen scene, creates the isolated runtime inputs, and calls the production runtime binding and resource graph code.
- Success records `startup_preflight_only=true`, stable declared files, a verified local graph, only `postgraph` and `bootstrap` phases, empty owned PX4/OpenVINS phases, and all downstream qualifications false.
- Full mapping coverage, runtime closure, physical execution, estimator health, fusion, and flight remain false.
- Any missing, extra, conflicting, drifting, unreadable, or malformed input fails closed. The output directory is never reused.

## Evidence boundary

The preflight proves that the current declared package can cross the exact startup boundary that rejected `study-v5`. It does not create physics evidence and cannot authorize a physical run by itself. A later physical target requires a new immutable package and a separate decision after this evidence is sealed.
