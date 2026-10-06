# SDK search context and plugin alternatives report

## Result
The native lookup adapter now checks all fixed-upstream plugin filename spellings in each SDK search root. Previously, another file in the same directory could be silently hidden by the first SDK winner. The installed SDK still selects the actual winner; the added candidate check refuses distinct canonical files and nonregular/dangling candidates. Same-target symlink aliases are allowed.

This completes a necessary search-context correction before graph binding. **Actual generated-world resource graph binding, runtime coverage, VIO accuracy and fusion remain unqualified. No physics, estimator, training, ODOMETRY, arming or EKF2 injection ran.**

## Implementation and research
Base7e57bd1; initial003ac2d. `context` reports cwd, named environment before/after installed addResourcePaths, Common file/plugin roots, public SDFormat getSharePath/version, global URI mappings and SDFormat callback presence. Common callback presence is explicitly null because the SDK exposes no inspection API. Search-context qualification and runtime-closure flags remain false.

The actual installed SDFormat public header is `/usr/include/gz/sdformat14/sdf/InstallationDirectories.hh`; the earlier header search used an incorrect directory. `getSharePath()` returns `/usr/share`. No guessed install path is needed. One synthetic context showed Common FilePaths `["/", "<temporary-root>/"]` after addResourcePaths; preserve the returned `/` when building future coverage. Do not assume the empty delimiter means cwd.

`IGN_PLUGIN_PATH` participates in installed plugin lookup and is now recorded, alongside other GZ/IGN search/log inputs. This is diagnostic output only; RuntimeBinding v1's old schema was not silently widened. Actual startup context must still be bound prospectively.

Candidate spelling expansion is adapted with attribution from Apache-2 Common442a7ab SystemPaths.cc. It includes `.so`, `.dll`, `.dylib`, uppercase variants and Release/Debug paths even on Linux; this is not a Python guess of lookup order. Absolute existing filenames follow SDK short circuit; relative slash/traversal requests are outside this narrow profile. Missing examined paths and regular canonical candidates are retained. Candidate conflicts/nonregular candidates produce structured diagnostics before nonzero refusal; earlier failures such as absent SDK winner still produce stderr/nonzero and must be retained by the future client.

Installed Sim8.15/Common5.9/SDFormat14.9 were reused without installation. Fixed Sim446a443 and SDFormat97d9b0 sources, license copies and prior metadata hashes are retained in the evidence. PR52 maintenance observations (nonarchived, Common/SDFormat last pushes2026-09-29/30) are reused, not new observations. Installed patch equality is not established. The public [SystemPaths API](https://gazebosim.org/api/common/5/classgz_1_1common_1_1SystemPaths.html) was consulted. OpenVINS algorithm/paper/config unchanged.

The adapter does not construct Server/TestFixture, load a plugin instance or decode meshes. SDK SystemPaths construction **can create its configured/default log directory**; “lookup only” does not mean zero filesystem side effects. Child environment changes do not alter the parent.

## Verification and failures retained
- Old binary:13 checks,7 failures demonstrating five same-directory alternatives, a nonregular alternative, and missing context operation. Remaining6 already passed.
- Initial new compile:17 existing URI and12 existing native checks passed. New checks12/13 because the test expected an unnormalized FilePaths entry; SDK returns a trailing slash. The test assertion was corrected, without changing production code;13/13 passed. Original failed output retained.
- Independent review: no Critical/Important selection errors; three Minor evidence/documentation gaps (unknown Common callbacks, discarded rejected candidates, SDK log-directory side effect). Standing all-gap authorization applied; all addressed. Two diagnostic fixes first produced7 missing-JSON/key failures then13/13; this was not a new selection-safety regression. No deferred minors or second review.
- Final rebuilt binary:13 new checks +17 URI +12 existing native checks passed. Compiler identity/flags/source copy/binary/93 selected source-and-linked-file hashes are recorded. Pre-query and post-query hashes match for both builds; test harness changed between builds and is not represented as unchanged.
-43 related Python tests passed after final fix. No new full Python-suite run claimed: production change is C++, and Python tests cannot validate the native binary.
- Changed Python Ruff passed. Whole repository Ruff still has52 findings in33 unchanged files, disjoint from this branch's changed files. No whole-lint pass claim.

## Status and next work
| Status | Evidence |
|---|---|
| Verified | Native candidate refusal, explicit SDK context, parent isolation; synthetic native files only |
| Implemented | Structured candidate-error output and unknown callback fields |
| Unfinished | Actual generated-world graph binding, complete URI candidate search coverage, startup environment and selected-resource freezing |
| Unverified | Lazy rendering/sensor mappings; owned PX4/native mappings; trajectory gauge contract; online heartbeat channel; VIO precision/quality/reset/covariance |
| Historical failures retained | PR48 rejected6.417s/accuracy indeterminate, PR37 drift lower bound29.5355m, old ground aliasing/startup failures;5-camera0.873RTF below0.95 |

Next: use the installed context plus strict bounded resolver client to bind original generated source references and all selected files into RuntimeBinding preflight. Account explicitly for `/`, `/usr/share` and versioned SDF roots, named legacy env and unavailable callbacks; unknown coverage must not authorize capture. Reuse existing resolver and snapshots; do not repeat old25URI/46edge studies. Then close bounded runtime mapping and prospective trajectory gauge before any new online physical study. All original load, safety and 2s watchdog limits remain.

## Publication
Draft PR54: https://github.com/chen7509/FlyDrones/pull/54 (stacked on PR53). Evidence ZIP resource-search-context-dev-1701:59members/248558bytes, SHA688e43a3f24fc5aff38416e3442ab524b9cdc8ad8f35964c420079d03917645c. Archive producer85d23ef, initial003ac2d, final native fix4b70981, sealdd033a3. Archived report predates this publication note. First publication-note update failed before writing due to Windows default cp1252; retried with explicit UTF-8.
