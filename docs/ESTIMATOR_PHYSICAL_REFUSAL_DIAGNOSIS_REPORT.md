# Estimator Physical Refusal Diagnosis Report

## Outcome

The first estimator-aware physical study did not reach motion or VIO scoring. It failed closed at simulation time 10 ms after 26.700906317 s wall time. The vehicle remained unarmed, support and lateral force counts were zero, fusion remained false, and no ULog was produced. The owned PX4 process ultimately required SIGKILL even though the post-run resource scan was empty.

This result is a harness/runtime-evidence failure. It is not evidence that OpenVINS accuracy failed, and it is unrelated to fruit-fly training, weights, loss, decision quality, or swarm policy.

## Confirmed defects

The readiness failure was a contract mismatch. The source record contained `sample_ns=4000000`, `observed_sim_ns=3000000`, and `sim_age_at_callback_ns=-1000000`. The producer's established provenance contract permits this one-step lead, but estimator-aware readiness rejected every `source_sample > observed_sim`. New RED tests reproduced the physical record and two invalid cases. The implementation now requires an exact derived age, permits at most 1,000,000 ns lead, and still rejects future wall arrival and larger or inconsistent simulation leads. The focused file now has 23 passing tests; changed-file Ruff and `git diff --check` pass.

The runtime-binding failure is independent. Bootstrap, imports, finalize, and OpenVINS-ready mappings were covered. The first Gazebo renderer step introduced 24 mappings. Twenty-three are shared libraries owned by installed Ubuntu packages covering OGRE-Next, LLVM/Mesa, DRM, EGL/GL, XCB/X11, Wayland, sensors, edit, ELF, and PCI access. The remaining path, `~/.cache/mesa_shader_cache/index`, is mutable runtime data and must not be added to the immutable declared-file set.

## Isolated renderer diagnosis

Seven retained probe attempts narrowed the first-render-step contract without PX4, OpenVINS, force application, training, or flight. The first three attempts exposed evidence-order and path-shadowing defects. Attempt four showed two anonymous deleted SYSV mappings inherited from the ambient display environment. Attempt five removed those mappings with the exact declared child environment and `MESA_SHADER_CACHE_DISABLE=true`, but revealed 25 additional libraries that had already been frozen in the historical baseline and merely loaded at a different phase. Attempt six correctly rejected duplicate resolved identities assigned to multiple declared roles. Attempt seven accepted role aliases while still comparing exact resolved identities.

`renderer-probe-v7` completed exactly ten 1 ms simulation steps. The first render step took 3.046523781 s wall time and produced one RGB image, one depth image, one camera-info record, and three IMU records. It added the same 23 historical renderer libraries plus 25 exact files already present in the frozen baseline; the Mesa disk-cache path was absent. Package ownership, version, architecture, installation status, file hashes, and copyright-file hashes were retained for every added mapping. The owned process group exited without SIGKILL and was absent after reap. The independent audit has no failures.

This qualifies only the isolated renderer mapping closure under the prospectively declared environment. It does not qualify the complete capture runtime closure, physical execution, VIO accuracy or health, fusion, EKF2 injection, or flight. Disabling Mesa's mutable on-disk cache preserves rendering, physics, sensor rates, and image size; it is an evidence-stability setting rather than a capacity or RTF optimization.

## Corrected prepare-only package

The first prepare invocation failed before creating an output because the consumed `study-v2` directory also contained its two retained supervisor files. The validator now accepts exactly the original six source files plus those two known post-run files and still rejects every other file.

The generated `study-v3` package was rejected twice. The first rejection found that independently recomputed monotonic snapshot timestamps cannot be byte-equal to the original scan. After the auditor was corrected to compare all binding content while validating the recorded clock interval separately, the package correctly failed again because its frozen auditor hash and file snapshot predated that code change. `study-v3` and both failed audits remain retained.

The unchanged, stabilized code then generated `study-v4`. Its first audit observed a transient NTFS/WSL metadata mismatch; a second audit, without modifying any package member, passed with no failures. `study-v4` contains exactly seven files, has no `capture-v1` directory, and preserves the original 25 s duration, 1 ms physics step, 250 Hz raw IMU, 10 Hz 160×120 RGB-D stream, motion profiles, vehicle, force profile, watchdogs, OpenVINS inputs, and safety limits. The only launch-environment addition is `MESA_SHADER_CACHE_DISABLE=true`. The manifest hash is `182eb4df8c309601e24ee118a50e4af844f2f414472eb775638fb9e9c30108b7`; its runtime-binding hash is `490c9b05f1801b631fdc2da560bb7e031ec5cb06e529ba09651cbd70619f114f`.

The passing audit qualifies `study-v4` only as a prepare-only package. `physical_execution_qualified`, `runtime_mapping_coverage_verified`, `runtime_closure_qualified`, `vio_accuracy_qualified`, `estimator_health_qualified`, `fusion_eligible`, and `flight_ready` all remain false. No generated command was executed in this stage.

Verification completed with 87 focused tests passing and the full repository suite at 1,426 passed, 3 skipped, and 2 existing warnings. Changed-file Ruff, Python bytecode compilation, and `git diff --check` passed. The final active-resource scan was empty. The evidence archive contains 81 members, is 455,586 bytes, and has SHA-256 `d80ef0845908e3b8cac90a53e816a6657b44cc9de31e2f4aeb5e582e805fbe0b`. It includes all seven renderer attempts, retained prepare/audit failures, the passing package/audit, selected original physical-refusal records, source/tests, and verification outputs.

## Current qualification

- Timestamp false-positive: fixed in code and focused tests.
- Renderer first-step mapping closure: qualified only for the isolated ten-step probe under its exact declared environment.
- Corrected next-run package: `study-v4` prepare-only audit passed; physical execution has not started.
- Physical execution, runtime closure, VIO accuracy/health, quality/reset/covariance, fusion, EKF2 injection, flight, and fruit-fly learning: not qualified by this run.
- The failed `study-v2/capture-v1` remains immutable. A future attempt must use a new audited package and destination.

The next bounded task is at most one physical run at the new destination `study-v4/capture-v1`, followed by a complete independent audit of runtime maps, readiness, safety, estimator health, timing, ULog, and cleanup. The old failed capture and rejected prepare packages remain immutable.
