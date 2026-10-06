# Full-Load Runtime Mapping Report

## Outcome

The prospective full-load contract was implemented and its fourth dry build passed an independent preparation audit. It froze 394 unique existing files, 107 source-selected runtime roots, 245 bounded `ldd` dependencies, the exact PX4/OpenVINS/native binaries and configuration, the sealed scene, the 25-second load, and all required worker/PX4/OpenVINS mapping phases.

The one declared online study did **not** reach Gazebo physics, PX4, OpenVINS, or runtime-map observation. The worker rejected the launch before those components started because the frozen resource environment did not equal the inherited launch environment. The capture is therefore a retained failure. Runtime mapping coverage, runtime closure, VIO accuracy, estimator health, fusion eligibility, and flight readiness all remain false.

This is a launch-contract failure. It is not a fruit-fly learning failure, VIO accuracy result, PX4 dynamics result, WSL capacity result, or training result.

## Frozen design

The design is recorded in `docs/superpowers/specs/2026-10-06-full-load-runtime-mapping-design.md`; the executed plan is `docs/superpowers/plans/2026-10-06-full-load-runtime-mapping.md`.

The builder in `tools/benchmark/full_load_runtime_mapping.py`:

- selects the exact Python, PX4, OpenVINS, native-reference, Gazebo system, DART, Ogre2, and sensor runtime roots;
- records canonical identity and a source-based selection reason for every root;
- runs bounded `ldd` on trusted selected ELF files and refuses nonzero, timeout, missing, unsupported, or drifting inputs;
- accepts only the exact successful `statically linked` diagnostic as dependency-free and canonicalizes real dependency paths before strict identity recording;
- records dpkg ownership for system roots and unambiguous Python distribution metadata for site/dist-packages roots;
- merges the sealed v2 resource graph into `capture-resource-binding-v3` without changing its graph or lookup context;
- freezes worker phases `postimports`, `postfinalize`, `postfirststep`, owned PX4/OpenVINS phases `ready`, `prestop`, an 8 MiB maps limit, and 16 observations;
- keeps the original 300-second capture and supervisor limits and the 25 s / 1 ms / 250 Hz / 10 Hz 160×120 RGBD workload.

The auditor in `tools/benchmark/audit_full_load_runtime_mapping.py` qualifies mapping coverage only when capture status, duration, binding, ordered phases, every mapping record, pre/post file identity, supervisor cleanup, and ULog bytes all pass. It never promotes mapping evidence to runtime closure, VIO accuracy, health, fusion, or flight readiness.

## Dry-build evidence

All attempts are retained:

1. `dry-v1` refused lexical parent traversal in NumPy wheel `ldd` dependencies. Source inspection showed real existing dependency paths containing `..` and exact successful `statically linked` CPython extensions. The strict canonicalization fix was tested; no runtime process started.
2. `dry-v2` refused a `/usr/local` Python extension without a dpkg owner. The corrected rule uses unambiguous Python distribution metadata only below one site/dist-packages directory and preserves dpkg as mandatory for other `/usr` roots. No runtime process started.
3. `dry-v3` rejected an operator-transcribed expected hash containing an extra `e`. The first hash gate worked; no source change or runtime process was needed.
4. `dry-v4` passed the independent prepare audit.

The accepted dry build contains:

- study manifest SHA-256 `e2d5dc301b6e8a685e2dd4003ad1c485373fb6a81154e5f74bd42ff0e17feaee`;
- execution contract SHA-256 `9ee3a7f6fe2b7f0d183e63ff2fd0a202109b31caf5337ddcb8b8f639c27d914e`;
- runtime binding SHA-256 `8df86b6f75afecc2d1d6cd581f6a6991824b3beae8ca7abebd36b1085a2d1df2`;
- 394 unique declared paths, all present at the prepare audit;
- 107 runtime roots with ownership/version evidence;
- 245 direct dependency identities from bounded loader inspection;
- unchanged sealed v2 graph and environment;
- conservative false values for mapping coverage, closure, VIO, health, fusion, and flight readiness before execution.

## Online failure

Immediately before launch, the accepted manifest, execution contract, runtime binding, scene archive, and base declaration hashes were rechecked and no competing PX4, Gazebo, OpenVINS, capture, test, or training process was found. The exact declared argv was launched once through the existing bounded supervisor.

The worker generated the sealed scene copies, then `RuntimeBinding.start` rejected `resource lookup environment mismatch` before recording the pre snapshot. No self or owned mapping phase ran. PX4 and OpenVINS were never launched, Gazebo did not step, simulation duration remained unavailable, and the ULog manifest correctly contained zero logs.

The mismatch is reproducible from the frozen declaration and current launch context:

- the sealed lookup context expects empty strings for `GZ_SIM_SYSTEM_PLUGIN_PATH`, `SDF_PATH`, and `GZ_FILE_PATH`, while the launch context inherited them as absent;
- the wrapper used for the exact argv inherited `PYTHONPATH=src:.`, while the frozen declaration expected it absent.

This shows that the study froze argv and files but did not make the required environment part of the executable launch contract. The run was not repeated after observing the failure. No environment value, path, timeout, load, sensor rate, safety threshold, or declaration was changed to seek a pass.

The terminal audit correctly failed with missing duration, ULog, pre/post snapshot, self phases, owned phases, and mapping records. Its final audit used the actual `capture-v1/supervisor.json`; the earlier audit made with a sibling supervisor path is also retained as an operator/audit-path failure.

Supervisor evidence remains useful for cleanup only: worker exit 2, capture status `capture_failed`, no supervisor errors, no executing members, original process group absent after reap, no SIGKILL. A fresh resource scan was empty. These facts do not qualify the capture.

## Verification

Implementation commits before publication are:

- `890eb30` design and plan;
- `3e47e74`, `c5e481d`, and `57eff7c` strict inventory and contracts;
- `5ec27b2` terminal auditor;
- `264f9b2` real loader-path/static-output correction;
- `bdbb27e` Python distribution ownership correction.

Verification results:

- focused builder/auditor/binding/owned-map/contract checks: 73 passed, 1 Windows symlink skip;
- full Python regression with the current worktree `src` explicitly selected: 1,200 passed, 3 skipped, 2 existing warnings;
- the first full-regression command inherited another worktree on `PYTHONPATH` and produced 55 collection errors; that failed log is retained and was not reported as a code failure;
- Ruff on every changed Python file: passed;
- whole-repository Ruff: 53 findings in 34 files, the same count as base `3304fb1`; whole-repository lint is not claimed as passing;
- `git diff --check`: passed.

The sealed evidence archive is `evidence/full-load-runtime-mapping-dev-1701.zip`: 37 members, 433,859 bytes, SHA-256 `e3217d0acc1dc649d06665c87fa74da78c8d8ef7b37d2017eee9ceb92ba68395`. The internal manifest records every payload member's byte length and SHA-256; ZIP CRC verification passed. Its producer commit is `34f66184ef85af40c9728f5e749ee9ff96c82e2c`. This publication paragraph postdates the archive and does not alter the sealed payload.

Review is published as draft [PR 58](https://github.com/chen7509/FlyDrones/pull/58), stacked on the owned-runtime-maps work in PR 57. The final report-link commit also postdates the immutable evidence payload.

No independent reviewer was available under the current single-agent constraint. Self-review covered source-derived selection, duplicate and ambiguous roots, loader failures, canonical dependency identity, package ownership, declaration overlap, exact load and lifecycle contracts, terminal phase ordering, incomplete/unsafe evidence, cleanup uncertainty, retry bias, and overclaiming.

## Evidence boundaries

Verified or implemented:

- strict prospective file/ELF inventory and v3 lifecycle contract;
- conservative terminal auditor and refusal behavior;
- a qualified dry build;
- bounded cleanup after the rejected online attempt.

Failed:

- the first declared online full-load study, before physics, because launch environment values were not executable contract inputs;
- runtime mapping coverage and runtime closure;
- physical VIO, health, fusion, and flight qualification.

Unchanged prior failures and blockers:

- PR48 stopped at 6.417 s on readiness loss and had indeterminate VIO accuracy;
- PR37 retained a 29.5355 m displacement-error lower bound;
- PR39 retained the old contact/undersampling diagnosis;
- PR40 retained its startup failure;
- the five-aircraft camera baseline remains 0.873 RTF below the 0.95 gate;
- `raw-model-zero-bias-diffusion-v1` remains an uncalibrated development assumption;
- native Linux, HITL, hardware, and real-flight evidence remain external requirements.

## Next gate

Before another physical study, the exact launch environment must become part of the prospective execution contract. The command must start from a clean, declared environment or carry an explicit environment map whose absent-versus-empty semantics are preserved and verified by both supervisor and worker. That work must use a newly named study and may not rewrite or relabel this failure.

After the environment gate passes, the trajectory/gauge contract remains the next VIO gate. OpenVINS previously became internally available after lift began, so origin, frame alignment, startup-unavailable classification, and scoring interval must be frozen before the run. Truth may be used only for external stopping and offline scoring, never to initialize or correct VIO.
