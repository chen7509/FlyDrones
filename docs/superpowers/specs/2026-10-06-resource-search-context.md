# Resource search context and complete plugin candidate diagnostics

The next graph binding requires a trustworthy account of lookup inputs. Source review revealed a concrete hole: PR52/53 only queried one plugin winner per directory, and lookupEnvironment omitted the supported IGN_PLUGIN_PATH. This phase closes those holes without claiming capture qualification.

## Design and choice
Reuse installed SDK SystemPaths, SystemLoader, and SDFormat InstallationDirectories rather than guessing installation roots or changing the world. Add a read-only `context` operation reporting before/after named environment, cwd, SDK common file/plugin roots, SDFormat share/version, and global URI mappings/callback presence. No Server, plugin instance, estimator or physics. Unknown callback presence remains explicit.

Plugin queries retain actual installed FindSharedLibrary as authority. For candidate coverage, port the fixed Apache-2 Common GenerateLibraryPaths spelling expansion, enumerate every spelling for every SDK root, and compare all existing regular candidates' canonical identities with the actual winner. Preserve missing paths and lexical aliases. Different files in one root refuse; aliases of the same canonical file may pass. Absolute existing library requests use the documented SDK short circuit. Relative path traversal is outside this narrow profile and refused. This is fixed-source candidate coverage, not proof installed patches are identical or runtime closure.

Add GZ/IGN search and log environment inputs to diagnostic output; do not mutate the parent's environment. RuntimeBinding v1 is unchanged: no unqualified graph is silently promoted. The eventual graph bridge must consume this context and close URI candidate and lazy/owned-process mapping boundaries before a new physical study.

## Validation
Real native synthetic files: same-root alternate suffix/prefix/case/subdirectory spellings, symlink same identity, deprecated plugin root, nonregular candidate, path traversal, malformed operation, SDK context and parent environment isolation. Original 17 URI and 12 resolver checks remain. Freeze compiler/source/binary/linked dependency identities. Do not repeat 25 old URI queries, 46-edge scan or physics.

## Research
Fixed Common 442a7ab4f213e435c3ca93947004216f26ec728d SystemPaths.cc (Apache-2) exposes FindSharedLibrary's private GenerateLibraryPaths, including cross-platform spellings even on Linux. SystemPaths public API documents root access and callback behavior: https://gazebosim.org/api/common/5/classgz_1_1common_1_1SystemPaths.html (checked this stage). Fixed SDFormat 97d9b0cea4a84003022d27d8d97b1def10b778ef SDF.cc calls public sdf::getSharePath; the prior search looked in the wrong include directory. Installed header is /usr/include/gz/sdformat14/sdf/InstallationDirectories.hh. Sim 446a44335a45b704b4d36dabcc5508ee34eeb3d8 addResourcePaths mutates SDF_PATH and common file paths. Installed Sim8.15/Common5.9/SDFormat14.9; no installation. PR52 maintenance observations reused, not newly observed (Common/SDFormat nonarchived, last pushes 2026-09-29/30). No algorithm change; OpenVINS paper and frozen GPL-3 implementation remain unchanged. Cost: one tiny SDK-linked query process, 10s cap, candidate stat calls; not inference or capacity performance.

## Boundaries
All prior failures remain. No ODOMETRY/arming/EKF2. No graph/runtime/VIO qualification. Follow-on graph integration and trajectory gauge remain outstanding; preserve full safety/load thresholds.
