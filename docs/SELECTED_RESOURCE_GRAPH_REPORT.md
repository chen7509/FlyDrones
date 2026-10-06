# Original asset discovery and native selection

This stage adds original SDF/COLLADA reference extraction and a small installed-SDK query executable. It does not change capture behavior, start physical simulation, run OpenVINS, or qualify a complete resource graph. `resource_graph_qualified=false`, `runtime_closure_qualified=false`, `fusion=false` remain required.

## Results and limits

- **Verified offline:** 8 original XML documents yielded 46 reference edges. There were 13 plugin uses selecting 10 distinct plugin names through installed `SystemLoader::PluginPaths` / `SystemPaths::FindSharedLibrary`, and 4 model directory selections through `sdf::getModelFilePath`.
- **Verified installation query:** `getMediaInstallDir()` returned `/usr/share/gz/gz-sim8/media`; `gazebo.material` belongs to `libgz-sim8:amd64`, and the plugin directory belongs to `libgz-sim8-plugins:amd64`. Original classic-material URIs and model files were retained. This proves the installed query/package path, not a rendered material.
- **Candidate discovery only:** 25 edges have unique local file candidates; 4 are material names and 4 refer to the classic material sentinel. The script deliberately labels all edges `resolution_qualified=false`. Candidate existence is not proof of SDFormat source-context or renderer lookup semantics.
- **Failure retained:** the first scanner harness copied the frozen world without its three colocated PNGs, leaving four unresolved texture references. A separately named `fixed-v2` copies those exact PNG members from the same PR48 archive and records member hashes. This was an offline harness packaging omission, not a missing historical capture asset or a VIO failure.
- **Not tested:** capture pre/post use, actual plugin instantiation, lazy rendering/sensor loading, owned PX4/estimator maps, physical sensor output and VIO accuracy. Two snapshots after discovery were stable; they are not historical or future capture pre/post freeze evidence.

The fixed input is PR48 ZIP SHA `07a2a247b87ff43304ec4c0fe787640264772ad12c272b354d5a5116cdecaeb2`. Discovery producer was `0775e22`; the final external-reference guard is later and was tested with synthetic/regression cases, without repeating discovery or any estimator.

## Validation and independent review

Initial scanner prerequisite failure was a missing module, and initial native prerequisite failure was a missing executable; neither is represented as a behavioral assertion counterexample. The initial scanner suite passed 13 tests. The actual WSL C++ executable passed 12 normal/error cases, including model.config-selected filename, missing resources, malformed arguments, distinct plugin candidates across roots, and files that are deliberately not ELF to demonstrate lookup without loading them.

Independent review found one Important: external COLLADA `url` / `source` / `href` and material `target` references could disappear. Four assertion failures reproduced it, then passed after unsupported markers were added. Local `#fragment` references remain internal. One Minor was resolved by clarifying that `text` is the XML-parsed value; the retained original bytes provide lexical spelling. No Critical or unresolved Important/Minor remains.

Native ambiguity scope is explicitly **one native winner per search root**, not exhaustive enumeration of every alias filename in one root. Upstream priority among same-root aliases is retained. Do not use this result to claim complete alias uniqueness.

Targeted final tests: 56 passed. Initial full regression: 1114 passed, 2 existing Windows symlink-permission skips, 2 existing warnings. Final full regression: **1120 passed, 2 existing skips, 2 existing warnings in 287.29 seconds**. Changed Python files pass Ruff; whole-tree Ruff still has 52 findings in 33 files unchanged from base `1c9a8d0`. An earlier 131/36 lint run included this stage's unignored scratch research scripts; adding the stage result directory to the existing ignore convention restores the comparable scope, and both outputs are retained.

## Research and reuse

Installed versions: Gazebo Sim 8.15.0, Common 5.9.0, SDFormat 14.9.0. Fixed upstream commits are gz-sim `446a44335a45b704b4d36dabcc5508ee34eeb3d8`, gz-common `442a7ab4f213e435c3ca93947004216f26ec728d`, sdformat `97d9b0cea4a84003022d27d8d97b1def10b778ef`, all Apache-2.0. New GitHub metadata records Common/SDFormat as non-archived with last pushes September 29/30, 2026; installed patch equivalence is not asserted. Compiler version, flags, source/binary hashes and linked-library hashes are retained. No dependency was installed.

The selected approach reuses [SystemLoader](https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1SystemLoader.html) and [SystemPaths](https://gazebosim.org/api/common/5/classgz_1_1common_1_1SystemPaths.html) instead of implementing filename/version selection in Python. Each query is bounded to 10 seconds by the harness; no simulation resources are consumed. A full Server solely for inventory was rejected because construction itself loads entities/transport and still misses lazy paths. Existing [OpenVINS research](https://docs.openvins.com/) remains unchanged; asset lookup is not an estimation algorithm or evidence of learning performance.

## Next dependency

Use installed `gz::sim::addResourcePaths`, SDFormat file resolution and renderer `asFullPath`/`common::findFile` semantics with original source-file context; establish exact include/mesh/texture selection and reject missing/remote/ambiguous results. Bind that graph to the existing execution/resource declaration. Then specify bounded lazy/owned-process mapping observations and the prospective trajectory/gauge rule before any new physical trial. Do not repeat old inventory, SDK capability tests, physics runs or lifecycle studies without a new hypothesis.

PR48's rejected 6.417-second run and indeterminate accuracy, PR37's 29.5355-meter drift lower bound, and the five-camera 0.873 RTF below 0.95 remain failures. No training, ODOMETRY, arming or EKF2 injection occurred here. During post-discovery input retention, the corrected scanner source no longer matched the discovery snapshot; that refusal is retained. Twenty unchanged source/config/asset inputs were copied and checked, and the old scanner was separately exported from producer Git with a matching SHA, explicitly labeled post-hoc retrieval.

## Publication

Draft PR: https://github.com/chen7509/FlyDrones/pull/52 (stacked on PR51). Evidence `evidence/selected-resource-graph-dev-1701.zip`:112members,15161857bytes,SHA256`af3308d916dcbf0f79d5667eb43e27b80c52ee92f767fd5d17f33e61357462e1`; every member hash and CRC verified. Archive producer104e9f7, seal commit7b38ebd. Final process check empty. Initial PR create returned GraphQL EOF; an empty head-PR listing preceded a successful normal retry, no TLS bypass.
