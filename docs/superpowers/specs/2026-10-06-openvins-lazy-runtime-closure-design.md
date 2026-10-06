# OpenVINS Lazy Runtime Mapping Closure Design

## Question

How can the next OpenVINS physical study prospectively declare a library that is absent from the executable's `DT_NEEDED` closure and appears only after the first estimator input, without converting one historical `/proc/maps` observation into an unchecked whitelist?

This stage is an isolated dependency and protocol study. It starts the frozen OpenVINS probe with the frozen estimator configuration and sends one synthetic IMU record. It does not start PX4, Gazebo, training, ODOMETRY, arming, EKF2, or a physical-motion study, and it makes no VIO accuracy or health claim.

## Root-cause evidence

The retained `dry-v5` failure contains exactly one unknown OpenVINS mapping at its first acknowledgement: `/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2.11`. The executable identity is stable and the ordinary declared mappings have no identity mismatch.

The installed `libtbb.so.12.11` belongs to Ubuntu package `libtbb12` version `2021.11.0-2ubuntu2`; that package has an exact-version dependency on `libtbbmalloc2`. The allocator file belongs to `libtbbmalloc2` of the same version. Its canonical SHA-256 is `5af2073ee206b88a82360bb692413cd24d9ab22107b4110442c560d4a2ac4b7c`.

The fixed upstream oneTBB tag `v2021.11.0`, commit `8b829acc65569019edb896c5150d427f288e8aba`, is Apache-2.0. Its `src/tbb/allocator.cpp` defines the Linux allocator name as `libtbbmalloc.so.2` and calls the dynamic-link path on first cache-aligned allocation. The general oneTBB library can therefore map the allocator after ordinary ELF dependency inspection has completed. The official oneTBB allocator documentation likewise treats the general and scalable-allocator libraries as separate dynamic libraries.

An isolated research probe using the exact OpenVINS binary and configuration found stable pre-input mappings, acknowledged one synthetic IMU packet, then found exactly one added file mapping: the same canonical `libtbbmalloc.so.2.11`. The probe exited normally after one accepted packet. This establishes the local trigger and mapping identity; it does not establish the completeness of later camera, initialization, rendering, PX4, or whole-runtime mappings.

## Decision

Create `openvins-lazy-runtime-closure-v1`, a prospective declaration produced from three independent evidence layers:

1. **Static root evidence:** exact OpenVINS executable/config identities, stable ordinary `ldd` closure, and the canonical `libtbb.so.12` identity.
2. **Package and source evidence:** exact package owners and versions, exact-version dependency from `libtbb12` to `libtbbmalloc2`, canonical allocator file identity and SONAME, frozen upstream commit/source/license identities, and the expected `libtbbmalloc.so.2` dynamic-load name.
3. **Active trigger evidence:** before/after owned-process identity and `/proc/maps` snapshots around exactly one bounded synthetic IMU acknowledgement. The trigger is qualified only when the pre-map set is stable, the process identity is unchanged, the input is acknowledged once, the added mapping set contains exactly the predicted canonical allocator, and shutdown is clean.

The declaration lists the allocator as a prospective addition to the next study's runtime inventory. The next study must revalidate its file identity before launch and still perform its normal owned-process runtime-map checks. The active probe predicts this one lazy mapping; it does not exempt any other unknown mapping and does not set `runtime_closure_qualified=true`.

## Bounded active probe

The probe uses the production `NativeClient` and the exact frozen `online_probe` and configuration. It waits for the owned process mapping set to remain identical for two consecutive observations within a fixed startup deadline, records the process identity and stable pre-input map set, sends one IMU record at simulation sample 1 ms with finite stationary values, records the validated acknowledgement, waits for another stable mapping set, and then closes the client.

All clocks are monotonic and all deadlines are finite. The before and after process PID, process group, session, start ticks, and executable must match. The input is a protocol trigger only. It is neither a sensor calibration sample nor VIO performance data. No image is sent, so initialization and public readiness are outside scope.

## Fail-closed rules

Reject any of the following:

- historical evidence with a changed executable identity, a mismatch, more than one unknown mapping, or a path/identity different from the prospective allocator;
- absent, ambiguous, symlink-escaped, non-regular, changed, or hash-mismatched executable, configuration, source, license, library, or package archive;
- missing or ambiguous package ownership, unequal `libtbb12`/`libtbbmalloc2` versions, or a dependency that is not exact-version;
- missing `libtbb.so.12` from the ordinary closure, or `libtbbmalloc` already present there;
- upstream source that does not contain both the fixed allocator name and first-use dynamic-link call;
- malformed, oversized, deleted, relative, or changing process mappings;
- startup-map instability, process identity drift, timeout, nonzero/duplicate acknowledgement, unexpected added or removed mapping, client failure, nonzero exit, or evidence-write failure.

Failure evidence is retained. No failure may be repaired by adding its observed path after the fact and rerunning the same physical study.

## Boundaries and next gate

Passing this stage permits a new prepare-only study to merge the single proven allocator file into a new runtime binding. It does not authorize reuse of `dry-v5`, a physical rerun, VIO-to-EKF2 injection, ODOMETRY publication, arming, or flight.

Before any future physical attempt, that new prepare-only study must bind this declaration and every referenced file, pass an independent audit, retain the existing workload and watchdogs, and confirm no competing process. The physical run must continue to reject every undeclared mapping. Later-stage lazy mappings remain possible and must be retained if encountered.
