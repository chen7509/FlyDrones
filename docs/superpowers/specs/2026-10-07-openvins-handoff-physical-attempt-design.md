# OpenVINS handoff-corrected physical attempt design

## Purpose and authorization

The user has authorized continuous execution of the verified FlyDrones roadmap. `study-v15` is the first package that binds the OpenVINS synchronous-initializer-handoff correction and has passed an initial audit, a committed-tree audit, one production startup preflight, and a post-startup package audit. This stage may therefore create exactly one new immutable physical development target at `study-v15/capture-v1`.

This is an evidence-producing development attempt. It does not authorize arming, ODOMETRY publication, EKF2 injection, hardware, flight, or multi-vehicle expansion. Any pre-dispatch failure stops without creating the target. Once the target, dispatch, completion, or partial output exists, the attempt is never overwritten or automatically retried.

## Frozen execution contract

Run the command recorded in `study-v15/study-manifest.json` without changing its workload or inputs: 25 s simulation, 1 ms physics, 250 Hz raw IMU, 10 Hz 160×120 RGB-D, the same vehicle, gravity, textures, supported-motion and 26 N lateral-force profiles, 200 ms future anchor, 8 s initial-readiness limit, 250 ms dependency stages, 2 s source/native/fan-out watchdogs, and 300 s worker/supervisor limits. Use the pinned OpenVINS binary and configuration, the pinned native-reference module, the declared runtime binding and trajectory gauge, and `MESA_SHADER_CACHE_DISABLE=true`.

Before dispatch, require a committed execution-boundary head, the exact 127-member correction/preflight archive with SHA-256 `7f8bbaacf577a073b8c0452a18151bb8aa5c2bb244b8517d74490bf86984c647`, passing post-startup package and startup audits, matching manifest destination and command output, absent target and attempt evidence files, and an empty active-resource scan. Re-run the package audit from the committed boundary. Do not tune noise, force, estimator settings or deadlines; lower load; repeat frames; relax public-initialization or safety gates; feed truth to VIO; or substitute another command.

## Result handling

Preserve every output whether the attempt completes or refuses: dispatch and completion, parent output, supervisor environment and journal, runtime mappings, ULog, source/fan-out/native/readiness/reference/physics/motion records, hashes and resource scans. Cleanup statements apply only to the original owned process group unless separate evidence proves more.

Audit the first supported terminal cause. Distinguish initializer-handoff-pending from the next-image public transition, internal/public readiness, ZUPT and regular updates, motion anchoring, source or wall-time refusals, VIO accuracy, and estimator health. Completing 25 s or seeing `public_initialized=true` cannot alone qualify VIO. Accuracy requires the frozen trajectory gauge and complete comparable interval; health also requires causal continuity and explicit quality/reset/covariance evidence. No failure in this attempt is evidence about fruit-fly training, weights, loss, swarm learning or the open-source comparison unless the corresponding policy actually ran and the audit proves that scope.

After the one attempt, do not rerun. Add result-specific RED/GREEN audit coverage, independently audit the immutable target, run justified regressions, update the report and PR, and seal evidence. If the attempt reaches a new downstream gate, the next stage must get its own design and immutable target.
