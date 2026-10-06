# Estimator Physical Refusal Diagnosis Report

## Outcome

The first estimator-aware physical study did not reach motion or VIO scoring. It failed closed at simulation time 10 ms after 26.700906317 s wall time. The vehicle remained unarmed, support and lateral force counts were zero, fusion remained false, and no ULog was produced. The owned PX4 process ultimately required SIGKILL even though the post-run resource scan was empty.

This result is a harness/runtime-evidence failure. It is not evidence that OpenVINS accuracy failed, and it is unrelated to fruit-fly training, weights, loss, decision quality, or swarm policy.

## Confirmed defects

The readiness failure was a contract mismatch. The source record contained `sample_ns=4000000`, `observed_sim_ns=3000000`, and `sim_age_at_callback_ns=-1000000`. The producer's established provenance contract permits this one-step lead, but estimator-aware readiness rejected every `source_sample > observed_sim`. New RED tests reproduced the physical record and two invalid cases. The implementation now requires an exact derived age, permits at most 1,000,000 ns lead, and still rejects future wall arrival and larger or inconsistent simulation leads. The focused file now has 23 passing tests; changed-file Ruff and `git diff --check` pass.

The runtime-binding failure is independent. Bootstrap, imports, finalize, and OpenVINS-ready mappings were covered. The first Gazebo renderer step introduced 24 mappings. Twenty-three are shared libraries owned by installed Ubuntu packages covering OGRE-Next, LLVM/Mesa, DRM, EGL/GL, XCB/X11, Wayland, sensors, edit, ELF, and PCI access. The remaining path, `~/.cache/mesa_shader_cache/index`, is mutable runtime data and must not be added to the immutable declared-file set.

## Current qualification

- Timestamp false-positive: fixed in code and focused tests.
- Renderer first-step mapping closure: diagnosed, not yet qualified.
- Physical execution, runtime closure, VIO accuracy/health, quality/reset/covariance, fusion, EKF2 injection, flight, and fruit-fly learning: not qualified by this run.
- The failed `study-v2/capture-v1` remains immutable. A future attempt must use a new audited package and destination.

The next bounded task is an isolated first-render-step mapping probe with the official Mesa disk-cache disable switch declared before launch. It preserves rendering and sensor workload and is not a performance optimization or acceptance-threshold change.
