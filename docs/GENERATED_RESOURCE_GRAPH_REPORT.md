# Generated resource graph binding

## Scope
This stage binds original generated-world SDF/COLLADA references to an explicit prospective file baseline. It does not run a simulator, estimator, training, ODOMETRY, arming or EKF2. Runtime closure, online VIO accuracy, quality/reset/covariance and the five-camera capacity gate remain unqualified.

## Implementation and research
Base1c8c4aa; initial implementation0e5a028; review fixacdff92. The installed SDK remains the path selector. Native bound-uri adds a narrow fixed-local-files-v1 candidate profile using fixed Apache-2 Common442a7ab, Sim446a443 and SDFormat97d9b0 source semantics, installed paths/URI/filesystem helpers and actual winner agreement. Distinct canonical alternatives, dangling/nonregular candidates, unsupported schemes and lexical forms refuse. Same-canonical symlink aliases are accepted. Include model.config dependencies are explicit. Callback clearing occurs only inside isolated helpers, not the actual Server.

Python strict schema and byte journals preserve query command/environment, output prefix, return/error and timing before decode/validation. Combined real helper output is capped at1MiB. Query deadline10s and graph60s are separate from bounded helper cleanup. Overall deadline is checked between reads/parses/queries and binding snapshots; it cannot preempt blocking filesystem or XML calls. Queries512/documents256/edges4096/depth32 are bounded. Original XML bytes and lexical source paths remain distinct from canonical identity.

RuntimeBinding v2 requires declared resolver/source/dependencies and actual cwd/environment/context agreement. Only explicit baseline/generated files can authorize graph targets; bootstrap process mappings cannot. The graph and all selected/config/material dependencies precede successful pre-close. Missing/unsupported references and drift refuse; failures retain partial graph and post evidence. An early baseline failure records a declared-only post attempt, never successful complete generated-input verification. v1 stays legacy with graph qualification false. Real Server callbacks, lazy rendering/sensors and owned native/PX4 mappings remain separate unknowns.

Reuse installed Sim8.15/Common5.9/SDFormat14.9 without installing dependencies. [SDFormat installation API](https://gazebosim.org/api/sdformat/14/InstallationDirectories_8hh.html) and [Common URI API](https://gazebosim.org/api/common/5/classgz_1_1common_1_1URI.html) were consulted. PR52 maintenance observations are reused, not new observations; installed patch equivalence is unproven. SDK helpers can create their default log directory. Resource hashing/XML parsing adds preflight CPU/memory/disk cost, not capacity optimization. OpenVINS algorithm and configuration are unchanged. Python search-order recreation, silent whitelist growth and Server construction merely for lookup were rejected.

## Retained failures and review
Initial native compile used a string where Split requires a char; build-v1 failure remains. Corrected study build passed10 new bound checks,17 URI,12 existing native and13 context checks (52 total); compiler/source/header/binary/linked dependency provenance is retained. Earlier missing-feature checks are not mislabeled as behavioral regression failures.

Offline-generated-world-v1 refused a22,399,616-byte original DAE at the new arbitrary8MiB tooling limit. It never started physics. The prospective v2 amendment raises that per-document limit to32MiB; all physical load/safety/VIO gates remain unchanged. XML memory can exceed source bytes. Old failure is retained.

Independent review found four Important issues (bootstrap authorization, omitted projector texture, unbounded/undecodable output, query-only deadline) and one Minor (early missing post attempt). Six assertions failed before the fixes, then passed. Additional real helper overflow/invalid-byte/timeout and source-size coverage were GREEN additions, not claimed RED fixes. No second review or deferred Minor.

## Remaining gates
Actual lazy/owned process mapping coverage and a prospective trajectory gauge are still required before another online supported-motion VIO study. Keep startup unavailability visible: PR48 first internal state2.4s followed lift anchor1.622s; do not choose a favorable origin afterwards or feed truth to the estimator. PR49 independent heartbeat lane has not passed an online run. Keep2s native/source/unreconciled limits,32pending and failure gate.

Historical PR48 rejection6.417s/indeterminate accuracy and historical freeze/prospective gaps, PR37 drift lower bound29.5355m, ground aliasing/startup failures remain. Five-camera0.873RTF<0.95 remains failed. No fruit-fly training failure is inferred from these platform/sensor investigations. No native Linux installation required.

## Final verification and fixed integration result
Full Python regression:1154 passed,2 existing Windows symlink permission skips,2 existing warnings,275.23s. That run overlapped the final addition of two post-snapshot/map budget checkpoints; therefore the final affected suite was rerun:77 passed in3.20s. Do not claim the full run alone validates those final checkpoints. Changed-file Ruff passes. Whole Ruff53 findings/34 files, all diagnostic files unchanged from base1c8c4aa; prior52/33 count is not reused as current.

Offline-generated-world-v2 producer06c0772 passed the22.4MB source cap but refused query18: CF.png has two different canonical candidates, meshes/CF.png and materials/textures/CF.png. Installed SDK selected the meshes copy. Both current files hash3a56ec48eeaaf7774e8d3e8e5e88f6973bfa5652c610974c3eb2dbec6ec85944; this does not satisfy the frozen unique-canonical-path contract. No automatic same-content exception or file deletion was applied. Partial graph, full bounded query bytes, pre/post declaration snapshots and failure remain. No successful pre manifest; graph/fusion/runtime qualification false. These are two new offline attempts, not replays of physical/estimator runs.

| State | Result |
|---|---|
| Verified |52 native checks;1154 Python regression plus77 final affected tests; bounded helper faults; failure evidence and candidate refusal |
| Implemented |RuntimeBinding v2 graph integration, explicit declared inputs, strict byte client, original recursive graph |
| Failed |Offline v1 arbitrary source cap; offline v2 distinct canonical texture alternatives |
| Untested |Successful actual-scene binding, real runtime lazy/owned maps, online heartbeat, prospective gauge, online VIO repeat |

Next: inspect the retained query18 and fixed Material/ColladaLoader precedence. Design a narrowly explicit deterministic-alternative policy only if supported by upstream behavior: record/freeze every candidate, winner and source context, reject changing candidates, and never relabel multiple paths as unique. Identical bytes are diagnostic evidence, not permission to silently weaken the current profile. Do not repeat inventory/normal physics or rewrite historical evidence. Once actual resource binding is qualified, bounded runtime mapping and prospective gauge remain before online VIO.

## Publication
Draft PR55: https://github.com/chen7509/FlyDrones/pull/55 stacked on PR54. ZIP135members/1085001bytes, SHA256 bbf2a2b19a035f4bb49e3c448579b88343c5b833befc054a13849d1675e8dfa6. Report/archive producer c45e59c, seal709878e; archived report predates this publication note. Source copies in archive are publication-time copies, not claimed runtime snapshots.
