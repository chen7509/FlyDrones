# Ordered COLLADA texture candidates

## Result

The generated original-source resource graph now passes for the sealed real scene without rewriting its DAE or deleting either `CF.png`. Fixed upstream `Material::SetTextureImage` uses an ordered short-circuit chain: the mesh-directory image wins; Common search and `../materials/textures` are consulted only if earlier steps fail. The native adapter now records that actual winner and all later existing paths separately.

This result qualifies the prospective local-file graph only. It does not qualify Gazebo renderer/sensor lazy loads, owned PX4/OpenVINS process maps, physical simulation, VIO accuracy, fusion, training, ODOMETRY, arming or EKF2 injection.

## Root cause and contract

Offline v2 correctly refused because the previous unique-canonical profile treated every existing fallback path as a competing winner. Fixed Apache-2 Common `Material.cc` SHA `13d35b5e18e329b2b99012f0acc70141d57cbb0b9f40084a28292d7bb2cbdede` shows the direct path is tested first, then Common lookup, then the material fallback. `ColladaLoader.cc` SHA `d6ce6690fdb16bc5d51f9d274ae3eba7a8e2abdb69049213c2681046e3a1a1ff` calls that overload with the mesh parent. `SystemPaths.cc` SHA `a74fcb6b5f963efc56283112b820ca3730f6aa05da97b875f3b053e091793b82` supplies the fixed Common ordering. These are previously sealed fixed-source copies; no new maintenance claim or installed-patch equivalence claim is made.

Only `collada-image` receives `material-ordered-fallback-v1`. The first existing canonical path must equal the installed SDK winner. Later distinct existing canonical paths are recorded in order as `shadowed_candidates`; same-canonical aliases are deduplicated. All other URI kinds retain `unique-canonical-v1`. Every winner and shadowed file must be declared before the helper runs and is included in pre/post identity and content snapshots. Adding, removing or changing a declared file causes refusal; identical bytes alone never authorize selection. Callback clearing remains helper-local and is not actual Server callback coverage.

## TDD and verification

The changed native test first failed against the prior sealed binary because the old adapter rejected two different canonical paths. The new test uses deliberately different bytes, so it proves precedence rather than content equality. A graph test first failed because the shadowed file was undeclared, then passes only when both winner and shadowed file are in the baseline.

The rebuilt frozen helper passes 10 bound-URI checks, 17 existing URI checks, 12 earlier native checks and 13 search-context checks: 52 total. Compiler, flags, source, header, binary and linked-file hashes are retained. Related Python tests: 78 passed. Full Python regression: 1155 passed, 2 existing Windows symlink permission skips and 2 existing warnings in 291.63 seconds. Changed-file Ruff passes. Whole-repository Ruff still reports 53 findings in 34 files; all diagnostic files are unchanged from base `1c469c5`, so no whole-lint pass is claimed.

## Real offline integration

`offline-generated-world-v3`, producer `fd447bc`, used the sealed PR48 generated world and PR52 source-discovery inputs, the rebuilt helper, and a fresh explicitly named prospective environment. The known material fallback was declared before any helper query.

- 8 original XML documents and 46 resource edges were retained.
- 40 bounded helper queries completed.
- 150 declared files matched before and after graph construction.
- The selected image is `x500_base/meshes/CF.png`.
- The declared shadowed image is `x500_base/materials/textures/CF.png`.
- Graph errors are empty; `local_file_graph_verified=true`.
- `runtime_closure_qualified=false`, `physical_run=false`, `estimator_run=false`, `fusion=false`.
- Active FlyDrones resources were empty before and after.

The earlier v1 8 MiB refusal and v2 distinct-canonical refusal remain preserved. v3 is a new prospective study and does not rewrite either failure.

## Self-review and remaining work

Fresh subagent review was not used because current coordination instructions prohibit spawning agents without an explicit user request. The author reviewed the branch against the fixed upstream source and contract. No Critical or Important issue was found. This is weaker than an independent review and is stated explicitly.

Next, bind lazy Gazebo rendering/sensor mappings and owned PX4/OpenVINS process mappings with bounded lifecycle evidence. Then freeze a prospective trajectory/gauge contract. PR48's first internal state at 2.4 seconds occurred after its 1.622-second lift anchor, so no favorable origin may be selected retrospectively and simulator truth may not initialize or correct VIO. Only after those two gates should another online supported-motion VIO run occur.

Historical PR48 rejection at 6.417 seconds and indeterminate accuracy, PR37 drift lower bound 29.5355 m, ground aliasing/startup failures, and the five-camera 0.873 RTF failure remain. None is reclassified as a fruit-fly learning failure.
