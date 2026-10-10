# EKF2 state sample-time diagnostic

Bounded extension of the existing read-only ULog shadow auditor. The user has
authorized automatic execution of plans within the existing offline scope.
No live activation, model construction, training or simulation is part of this
work. The purpose is to determine what an actual student observation producer
must carry, before assigning qualified provenance to archived or live state.

## Question and frozen method

Can publication-time-only alignment hide old state in the retained development
run 27201? Inspect only that development run; do not inspect or tune against the
three held-out covariance runs. Use the original RGB manifest and verify each
image hash. Bind the ULog to the existing health-contract ZIP and ULog manifest.
Record the current input hashes before analysis, and recheck afterward. These
are diagnostic input snapshots, not historical capture pre/post evidence.

Add `audit_state_sample_times(frame_ns, topics)` alongside the unchanged v1
auditor. Consume only `vehicle_local_position` and `vehicle_attitude`, each with
integer `timestamp` and `timestamp_sample` arrays in microseconds. For every
original frame choose the last message published at or before that frame. Do
not select a message published in the future merely because its sample is old.
Keep publication age, sample age and publication-minus-sample separately. Use
the existing 100 ms estimate-age boundary for both ages; a sample newer than its
publication, a zero sample, or nonincreasing sample history is not qualified.
Report position/attitude sample skew using the existing 50 ms camera-pose
alignment boundary as a diagnostic selector, not a new flight requirement.
Malformed shape/type/range or nonincreasing publication time refuses the input;
empty topics and per-message timing faults retain every frame with reasons.
Never fall back from a missing sample timestamp to the publication timestamp.

Both time domains are still the uncalibrated Gazebo/PX4 simulated-epoch
assumption. Publication time is not host receipt time. The diagnostic cannot
certify EKF2 health, source, calibration, coherent resets, teacher identity,
camera pose, real-time latency, or live capture. All eligibility flags stay
false. The v1 health audit may be run on the same retained development data to
identify independent blockers; it is not made stronger by the timing audit.

## Implementation and verification

1. Test fresh publication/stale sample, exact age boundary, future publication
   with old sample, future/zero/duplicate/regressing samples, missing fields,
   integer overflow/bool/float timestamps, empty topic and excessive skew.
2. Implement the pure companion function in `ekf2_shadow.py`, preserving v1.
3. Run focused tests and ordinary full regression; no estimator/physics jobs.
4. Parse the one development ULog with official pyulog 0.9.0, imported from a
   hash-verified wheel in the results directory, without installing globally
   or starting WSL. Reuse installed NumPy. Record parser/wheel/source identities.
5. Save every aligned frame and unavailable reason, original health findings,
   source research, input hashes, tests and review. Update the producer's next
   requirements from evidence; do not synthesize training sequences or teacher
   commands from this diagnostic.

## Primary sources and selection

Fixed PX4 d6f12ad1c4f70ad3230afd7d86e971421e02fef4, BSD-3-Clause:
[VehicleLocalPosition](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleLocalPosition.msg),
[VehicleAttitude](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/msg/versioned/VehicleAttitude.msg),
[EKF2](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/ekf2/EKF2.cpp),
[selector](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/ekf2/EKF2Selector.cpp).
EKF2 publishes predicted attitude/local position with the sample time; the
selector preserves it while replacing publication time. Delayed filter status
has different timestamp semantics and is not substituted for output state.

[Official pyulog](https://github.com/PX4/pyulog), BSD-3-Clause, is the existing
project's parser choice. Version 0.9.0 wheel SHA256
`777ed691cb00bc9d8229e3de21d198507d595af96611cf975c55daef36912869`
is pinned via PyPI metadata, uses NumPy, and avoids writing a new ULog parser.
One roughly 7.6 MB ULog is parsed with a topic filter; no resident flight stack
or GPU is needed. Actual runtime cost will be reported, not assumed.
GitHub metadata observed in this research: neither repository archived; PX4
last push 2026-10-08, pyulog 2026-08-06. This does not prove support guarantees
or equivalence of all installed PX4 patches to upstream. Source snapshots and
URLs are retained in `results/ekf2-sample-time-dev-1701/sources`.

Rejected alternatives: changing timeout/health gates, constructing a guessed
live producer from MAVLink telemetry, parsing ULog manually, starting WSL solely
to obtain a parser, or repurposing held-out data. No new estimation algorithm is
introduced; the question is defined by the pinned publisher/message API, so an
unrelated estimator paper would not supply the missing timing evidence.
