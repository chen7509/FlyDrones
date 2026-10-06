# Native URI resolution plan
> Use superpowers:executing-plans inline with one independent whole-branch review.

Spec: docs/superpowers/specs/2026-10-06-native-uri-resolution.md
Goal: obtain installed source-context-aware lookup results without simulation.
Architecture: extend the existing C++ executable, add a standalone native test harness, then evaluate frozen reference edges in an isolated process.
Tech stack: C++17 installed gz-common5-graphics/gz-sim8/sdformat14, Python standard library harness.
Review focus: relative source vs cwd; config dependency; URI rejection before potential callbacks; forced Assimp mismatch; successful output never implying full graph/ambiguity/runtime qualification.

- [ ] Write tests/native/run_uri_resolver_checks.py using real temp files and old executable; observe unknown-mode behavioral failure.
- [ ] Extend tools/benchmark/native/resource_resolver.cc with include/texture/mesh-path/collada-image and strict error/context output. Compile with recorded flags and source/binary/dependency hashes; actual native tests must pass.
- [ ] Evaluate only25 previously retained resource edges, retaining original source/member hashes and supplied environment; log refusal/mismatch and immutable inputs. No physics or estimator.
- [ ] Run existing native regressions and Python full suite, independent review, targeted fixes if necessary, report and seal evidence, publish draft PR, update heartbeat to next binding dependency.
