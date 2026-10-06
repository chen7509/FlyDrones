# Selected resource graph implementation plan
> Use superpowers:executing-plans inline; one independent whole-branch review.

Spec: docs/superpowers/specs/2026-10-06-selected-resource-graph.md
Goal: extract original asset references and expose installed native selection without physics or inferred runtime coverage.
Architecture: strict XML scanner plus standalone read-only C++ resolver, with native subprocess tests and an evidence runner. No capture behavior changes.
Tech stack: Python standard library, installed C++17 Gazebo/SDFormat.
Review focus: unknown URI locations cannot disappear; COLLADA internal symbols must not be paths; native ambiguity cannot masquerade as one choice; nonzero/malformed native result cannot qualify; original files remain unmodified.

### Task 1: original reference extraction
- [x] Write tests for exact original positions/repeated edges, includes/meshes/PBR/scripts/plugins, namespaced COLLADA image vs internal effect, unknown URI, empty fields and DTD refusal. Observe missing-feature failure.
- [x] Implement tools/benchmark/selected_resource_graph.py: references(data: bytes, format: str) -> list[dict], no filesystem/network lookup. Unknown URI produces kind unsupported, not success.
- [x] Run tests/benchmark/test_selected_resource_graph.py and commit.

### Task 2: installed native resolver
- [x] Add tests/native/run_resource_resolver_checks.py exercising executable modes and real temporary plugin/model files, including ambiguity and missing inputs. Run before source exists; retain failure.
- [x] Implement tools/benchmark/native/resource_resolver.cc and compile with pkg-config gz-sim8 gz-common5 sdformat14, recording args/hash/ldd. Run normal/fault checks without loading plugin instances or Server.
- [x] Record original fixed-world/model references, selected plugin/model results, classic media path/package provenance and explicit remaining URI/loaded graph gaps.
- [x] Run targeted/full regression, one independent review, report, seal evidence, draft PR and update heartbeat. Preserve all failed attempts.
