# Supported Heartbeat Gauge Preflight Design

## Question

How can the next supported-motion OpenVINS study bind its trajectory scoring rules before launch when the immutable motion anchor is selected only after a real unarmed PX4 heartbeat and source readiness?

This stage builds and audits a prospective study package. It does not start PX4, Gazebo, OpenVINS, training, ODOMETRY, arming, or EKF2.

## Decision

Separate the prospective **gauge policy** from the run-specific trajectory contract. The policy fixes every scoring choice that may be known before launch: first internal state origin, yaw-plus-translation alignment, unit scale, zero time shift, exact time matching, the lateral-start offset, duration, coverage requirements, error screens, truth scope, and false fusion/flight eligibility. It names the anchor source as the immutable readiness anchor and contains no numeric anchor.

After a run, the offline auditor may instantiate the existing `trajectory-gauge-contract-v1` with the numeric anchor recorded by the readiness subsystem. That operation may not change any policy field or use truth, error, public initialization, or later trajectory quality to choose the anchor or origin.

## Prospective execution binding

An execution contract that names a gauge policy uses `capture-execution-v3`. It retains the exact v2 launch environment and all existing workload, profile, path, timeout, and hash fields. It adds one `trajectory_gauge_policy` record containing the absolute requested path, canonical resolved path, byte length, SHA-256, and schema.

The policy file must be a regular file, strict duplicate-free finite JSON, and must equal the canonical policy document exactly by value and type. Unsupported keys, booleans in integer fields, path aliases that change identity, and file changes during validation are refused. Existing v1 and v2 contracts remain byte-for-byte unchanged when no policy is supplied.

The parent and worker independently validate the same declaration before inspecting active resources or constructing NativeClient, TestFixture, PX4, or OpenVINS. The worker records the declared policy identity before runtime initialization. The policy is included in the runtime binding inventory so pre/post snapshots detect ordinary drift. These checks are ordinary file-stability evidence, not hostile-ABA protection or fsync durability.

## Preflight study package

Create a new prepare-only `supported-ready-shadow-heartbeat-gauge-v1` study package by extending the frozen full-load runtime-mapping inputs. It must retain:

- 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160x120 RGBD;
- `supported-ready-v1`, `substep-ready-v1`, and `ready-shadow-heartbeat-v1`;
- 300 s parent and supervisor budgets and existing 2 s source/native/heartbeat watchdogs;
- the frozen OpenVINS binary/config, native reference module, PX4 inputs, selected resource graph, exact launch environment, and runtime maps;
- original support/lateral force, readiness anchor, unarmed state, abort limits, and failure retention.

The prepared command must include the policy path, execution contract, and runtime binding. A dry preflight auditor verifies the package hashes, exact command/declaration agreement, policy semantics, inventory inclusion, launch environment, profile/workload invariants, false qualification claims, and absence of an existing capture destination. Any unknown or mismatch refuses physical launch.

## Boundaries

The policy does not make PR48 complete, does not repair its historical runtime freeze, and does not turn its partial trajectory diagnostic into a pass. It does not calibrate IMU noise, covariance, quality, or reset evidence. It never exposes Gazebo truth to VIO or online control.

The physical run remains a separate next step. It may start only after this prepare-only package and dry audit pass, no competing resource is active, and all referenced inputs are unchanged. A future physical failure is retained and is not retried blindly.

## Failure handling

Reject malformed/duplicate/nonfinite JSON, unsupported policy values, dynamic numeric anchors in the prospective policy, missing or changed files, declaration/policy/path mismatch, duplicate inventory roles, command omissions, lowered workload or timeouts, incompatible profiles, incomplete resource binding, reused output, and any claim that accuracy, health, fusion, flight, runtime closure, or physical execution already passed.
