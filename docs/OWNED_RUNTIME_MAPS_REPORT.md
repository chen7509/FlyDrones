# Owned Runtime Maps Report

## Outcome

The capture stack now has a prospective `capture-resource-binding-v3` contract for file-backed mappings in the worker, PX4, and OpenVINS processes. It pins each explicitly registered child by PID, process group, session, start ticks, and executable; reads `/proc/<pid>/maps` within a fixed size and observation budget; checks every file mapping against the declared pre-run snapshot; and records raw and structured evidence at named phases.

This implementation is verified by unit, regression, and a bounded Linux child-process harness. It has not yet been exercised in a new PX4/Gazebo/OpenVINS physical capture. Runtime closure, physics, VIO accuracy, and fusion eligibility remain false.

## Design and Source Basis

The design is recorded in `docs/superpowers/specs/2026-10-06-owned-runtime-maps.md`; the executed plan is `docs/superpowers/plans/2026-10-06-owned-runtime-maps.md`.

The implementation reuses the fixed upstream and installed-source evidence from the preceding runtime-binding stages:

- Gazebo Sim 8.15 / fixed source `446a443`, Apache-2.0. `TestFixture` and `Server` execute inside the worker; systems, rendering, and sensors may load libraries after finalization or on the first server step.
- gz-common 5.9 fixed source `442a7ab`, Apache-2.0.
- SDFormat 14.9 fixed source `97d9b0c`, Apache-2.0.
- PX4 fixed source `d6f12ad`, BSD-3-Clause.
- OpenVINS fixed source `6948812`, GPL-3.0. The prior maintenance observation remains uncertain; this stage did not infer a new maintenance status.
- Linux `/proc/<pid>/stat`, `/proc/<pid>/exe`, and `/proc/<pid>/maps` are used only for explicitly registered direct processes. The observer does not scan, signal, or clean up processes.

## Implementation

`tools/benchmark/owned_runtime_maps.py` implements the bounded identity-pinned reader. Registration refuses undeclared executables. Each observation reads identity before and after maps, rejects PID reuse, exec changes, disappearance, malformed or oversized maps, deleted paths, unknown files, and device/inode mismatches, then persists raw and structured evidence.

`tools/benchmark/runtime_resource_binding.py` adds strict v3 validation:

- exact ordered self phases;
- exact owned roles limited to `px4` and `openvins`;
- bounded map bytes no greater than 8 MiB;
- at most 16 owned observations;
- phase order and uniqueness;
- terminal `runtime_mapping_coverage_verified` only when every declared phase passed and declared files remained stable.

`runtime_closure_qualified` remains false. Older v1 and v2 declarations retain their behavior.

The capture integration records:

- worker `postimports` and `postfinalize`, plus `postfirststep` only after a successful `server.run` call;
- OpenVINS `ready` on its first validated native acknowledgement and `prestop` before its bounded shutdown;
- PX4 `ready` on the first accepted unarmed heartbeat after the registered process exists and `prestop` before shutdown.

Mapping failures enter the existing error path. Native and PX4 cleanup still executes. The implementation does not change physics, sensors, motion, timeouts, OpenVINS configuration, public initialization, ODOMETRY publication, arming, or EKF2 fusion.

## Verification

The implementation commit is `d1c3313`.

- Focused owned-map, audit, binding, and resource-graph checks: 77 passed.
- Capture/shadow/fan-out/readiness focused checks: 123 passed.
- Full Python regression: 1,173 passed, 2 skipped, 2 existing warnings.
- Ruff on every changed Python file: passed.
- Whole-repository Ruff: 53 findings in 34 files, the same count and file set as base `d873794`; this stage does not claim whole-repository lint passes.
- `git diff --check`: passed, apart from Git line-ending notices.

The independent Linux harness used `/usr/bin/sleep` and its prospectively enumerated direct dynamic dependencies under `LC_ALL=C` and `LANG=C`. The successful v3 run observed the same PID, process group, session, start ticks, and executable at `ready` and `prestop`; every mapped file matched the declared device/inode snapshot; the post snapshot was unchanged. A separately spawned child was terminated after registration, and the subsequent observation correctly retained a `FileNotFoundError` refusal.

The first harness attempt is retained as a failure. It used the ambient UTF-8 locale, which mapped locale and gconv data files absent from the prospective `ldd` declaration. The observer rejected 13 unknown mappings. The second and final harness explicitly froze the C locale before spawning. No missing file was added after seeing a running child.

No independent reviewer was available under the current single-agent constraint. Self-review covered PID reuse, pre/post identity changes, process disappearance, exec changes, unknown/deleted/malformed/oversized maps, device/inode mismatch, duplicate and out-of-order phases, observation budgets, evidence write failures, post-snapshot drift, and cleanup-scope separation.

## Evidence Limits

The bounded harness qualifies only the mapping mechanism and refusal behavior. It does not qualify:

- the actual PX4/Gazebo/OpenVINS runtime mapping set;
- lazy renderer or sensor mappings under the full 25-second workload;
- files opened without memory mapping;
- kernel, driver, GPU, OS, hardware, anonymous mapping, or escaped-descendant closure;
- VIO initialization, accuracy, source health, quality, reset, covariance, ODOMETRY, EKF2, or flight safety;
- any fruit-fly learning, inference, assignment, or baseline comparison result.

The earlier failures remain unchanged: PR48 stopped at 6.417 seconds on readiness loss and had indeterminate accuracy; PR37 retained a 29.5355 m displacement-error lower bound; PR39 retained the old contact/undersampling diagnosis; PR40 retained the startup failure; the five-aircraft camera baseline remains 0.873 RTF below the 0.95 gate.

## Next Gate

The next runtime step is a separately named, prospectively frozen full-load mapping capture using v3. Its declaration must include every selected resource, the actual PX4/OpenVINS executables and dependencies, and the required lifecycle phases before any process starts. Unknown or missing mappings must fail without dynamically expanding the declaration.

After that mapping capture, the trajectory/gauge contract must be frozen before another online VIO accuracy attempt. Because the previous OpenVINS internal state appeared after lift began, the origin and comparison interval must be specified before the run; truth may be used only for external stopping and offline scoring, never to initialize or correct VIO.
