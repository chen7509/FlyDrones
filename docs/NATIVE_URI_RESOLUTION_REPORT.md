# Native URI resolution under explicit source context

The read-only resource executable now queries installed include, texture, mesh-path and COLLADA image lookup semantics. It does not start a Server, TestFixture, renderer, estimator or physical simulation, and does not change capture behavior. Complete resource graph, candidate ambiguity, runtime closure and VIO fusion remain **unqualified**.

## What was verified

- 25 retained PR52 reference edges were queried under an explicitly recorded current research environment and cwd: 4 includes, 7 textures, 13 mesh references and 1 COLLADA image. All 25 SDK selections matched the prior candidates; input/source/binary/dependency hashes before and after these queries matched.
- Include queries use installed `sdf::findFile` and `getModelFilePath`, retaining the selected model.config dependency. Textures use `asFullPath(uri, originalSource)` and `common::findFile`. Mesh queries reproduce filename lookup before MeshManager decoding; they do not prove the mesh can be rendered.
- COLLADA image queries use installed `Material::SetTextureImage`, matching ColladaLoader's source-directory, common-finder and `../materials/textures` fallback behavior. They do not decode images. The forced-Assimp path is refused when the SDK's exact enabling value, `"true"`, is set.
- Results record parsed URI, lexical source path, transformed path, native selected path, canonical file, cwd, before/after named lookup environment and explicit nonqualification flags. `addResourcePaths()` changes only the subprocess environment. Remote/unsupported URI schemes, missing files, invalid source paths and SDK failures produce refusal results.

The experiment uses PR52 ZIP SHA `af3308d916dcbf0f79d5667eb43e27b80c52ee92f767fd5d17f33e61357462e1` and its fixed reference/member hashes. It is **not** a reconstruction of PR48's historical process environment. The supplied SDF_PATH and GZ_FILE_PATH were explicitly empty before the installed API appended model roots. No original XML was rescanned or substituted, and no estimator or physical capture was repeated. Producer was `fc866d3`; later guard changes were verified with synthetic native tests, not by claiming a repeated 25-edge study.

## Tests and failures

The first native test ran against the prior executable and failed a behavioral assertion because URI mode was absent. Initial implementation passed 13 URI cases and 12 existing native cases. Independent review identified one Important and one Minor:

1. A URI such as `http:example.invalid` lacks `//` but still has a scheme. With a same-named local file, include and COLLADA lookup incorrectly returned success. No network activity was observed or implied. Scheme validation now rejects it before lookup.
2. The Assimp guard originally refused every nonempty environment value; the pinned SDK enables that path only for exact `"true"`. The guard and tests now follow that behavior, including acceptance of `"false"`.

The isolated four-case counterexample harness initially had 3 failures and 1 already-correct refusal; after fixes all 4 passed. Final native verification: **17 URI cases plus 12 existing cases passed**. No Critical, unresolved Important or Minor remains. Python regression: **1120 passed, 2 existing Windows symlink-permission skips, 2 existing warnings in 303.76 seconds**. That Python run overlapped review; the changed native binary was separately rebuilt and retested after the guard fixes. No Python production behavior changed. Changed Python Ruff passes; whole-tree Ruff still has 52 findings in 33 files unchanged from base `dcd1640`.

## Research and reuse

Installed Sim 8.15.0, Common/graphics 5.9.0 and SDFormat 14.9.0 remain selected, without installing dependencies. Fixed upstream Apache-2.0 commits: Sim `446a44335a45b704b4d36dabcc5508ee34eeb3d8`, Common `442a7ab4f213e435c3ca93947004216f26ec728d`, SDFormat `97d9b0cea4a84003022d27d8d97b1def10b778ef`. Newly retained ColladaLoader, Material and MeshManager source shows why a generic Python path join would be insufficient. Previously observed repository maintenance metadata is retained and dated; installation patch equivalence is not asserted.

The [Gazebo utility API](https://gazebosim.org/api/sim/8/namespacegz_1_1sim.html) and [SDFormat API](https://gazebosim.org/api/sdformat/14/namespacesdf.html) support the installed calls. Reusing these methods avoids reimplementing lookup ordering. Query subprocesses have a 10-second harness timeout; compiler invocation has a 90-second limit. Compiler identity is recorded before build, along with flags, source, binary and linked-library hashes. This is a resource lookup study, not a capacity optimization or an inference benchmark. Existing OpenVINS learning/estimation choices and uncalibrated noise assumptions are untouched.

## Remaining gates

Path selection alone does not establish absence of alternative candidates. `ambiguity_qualified=false` remains explicit; these successful results cannot authorize capture. Next, define a declared candidate/search-context contract and bind graph results to the actual generated world and runtime declaration, retaining unsupported/missing/ambiguous cases. Preserve lexical source context and model.config dependencies; do not replace them with canonical paths before the SDK call.

Lazy rendering/sensor loading, owned PX4/native mappings and a prospective trajectory/gauge rule still require bounded designs before a new 25-second physical trial. PR48's 6.417-second rejection and indeterminate accuracy, PR37's 29.5355-meter drift lower bound and the five-camera 0.873 RTF below 0.95 remain unchanged. No ODOMETRY, arming or EKF2 injection occurred here.

## Publication

Draft PR https://github.com/chen7509/FlyDrones/pull/53 is stacked on PR52. Evidence `evidence/native-uri-resolution-dev-1701.zip`:61members,308531bytes,SHA256`71b0838a312a8666972c187e8157844c35edaa95a392f92e8eeddda492174a46`; all member hashes and CRC verified. Archive producer1374538, seal commitcdc74ea. Final process scan was empty.
