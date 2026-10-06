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

## Execution-entry refusal and single capture attempt

The first dispatch wrapper stopped before writing a dispatch record because WSL could not resolve the Windows worktree Git pointer. A second `study-v4` dispatch reached the capture CLI but was rejected before creating its destination: adding `MESA_SHADER_CACHE_DISABLE` to the binding made the old exact environment-schema validator reject the package. Neither event started PX4, Gazebo, OpenVINS, or a physical capture.

The binding validator was changed to accept only the optional value `MESA_SHADER_CACHE_DISABLE=true`, while retaining compatibility with old declarations and rejecting arbitrary renderer variables. The prepare builder and its independent auditor now invoke the real `validate_binding` execution entry. `study-v5` passed two audits, including one after committing the fix.

The single allowed actual attempt then created `study-v5/capture-v1` and failed closed during `RuntimeBinding.start`: the runtime comparison projected only the legacy environment keys and omitted the now-declared Mesa key. The capture audit has no failures. No TestFixture, PX4 process, OpenVINS worker, force, motion, ULog, VIO input, or fusion was produced. The worker exited 2; the original owned process group was reaped without SIGKILL, with no executing members and no remaining resources. This is another startup harness-contract failure and says nothing about VIO accuracy or fruit-fly learning.

A RED test reproduced the optional-key mismatch. `RuntimeBinding.start` now compares exactly the keys in the validated binding declaration; 26 binding tests pass. The failed capture is immutable and will not be rerun under this stage. A future physical attempt requires a separately named, newly frozen package and plan; the current verified fix alone is not evidence of physical execution.

Post-attempt verification has 113 focused tests passing and changed-file Ruff passing. The second immutable evidence archive contains 43 members, is 778,777 bytes, and has SHA-256 `93e4bfd4c4d87bfdfa74b9453d749c7cd49c65595b90b494352bee65ebe159f7`. It includes the first evidence ZIP, both pre-dispatch refusals, the full `study-v5` package and failed capture, supervisor journal, cleanup and ULog evidence, independent capture audit, the RED/GREEN fix, and post-attempt tests.

The final full repository regression after the runtime comparison fix reports 1,428 passed, 3 skipped, and the same 2 existing warnings. A five-member verification archive containing the attempt archive, full test output, final fix and test has SHA-256 `cfbede041e5bcc75aac68e1e6f1dd9ab77d5a0f26da43ce3135f1a4fd3eff02a` and size 778,538 bytes.

## Real capture-CLI startup preflight

The next gate now uses the production capture parent and worker instead of reimplementing their validation. An opt-in `--startup-preflight` flag requires the execution contract, runtime binding, and trajectory policy; the parent forwards it through the existing owned-group supervisor. The worker performs the ordinary pinned binary/archive checks, active-resource check, scene extraction, runtime input creation, environment recording, generated-file validation, SDK resource queries, local graph construction, and `RuntimeBinding.start`. It returns before importing `TestFixture` or starting PX4, OpenVINS, ULog collection, force, or motion.

`study-v6/startup-preflight-v1` returned zero. Its binding pre-record was written, declared files remained stable, and the local resource graph verified. Only `postgraph` and `bootstrap` self phases ran; PX4 and OpenVINS owned phases are empty and full runtime mapping coverage remains false. The supervisor exited zero, used no SIGKILL, reaped the original group, and the final resource scan was empty. The independent audit has no failures and explicitly keeps physical execution, runtime closure, VIO accuracy/health, fusion, and flight false.

After adding the final CLI guard that refuses startup preflight without all three declarations, commit `84327d7` generated `study-v7`. Its prepare-only audit passed, and the current committed capture CLI repeated the non-physical startup preflight at the new `study-v7/startup-preflight-v1` destination. The second independent audit also has no failures, confirms no PX4/OpenVINS/physics files, and leaves all downstream qualifications false. `study-v7` is the authoritative current-code startup package; no physical target was started from it.

Final verification for this gate has 140 focused tests passing and the full repository suite at 1,430 passed, 3 skipped, and the same 2 existing warnings. The 86-member evidence archive is 1,411,658 bytes with SHA-256 `98d41ab3736eea00c423606e928682005932e9a8e5e0ab0ad9b0838c1dc4a68b`; it contains the prior attempt evidence, current package, complete preflight output and supervisor journal, independent audit, source/tests/spec/plan, and final test logs.
