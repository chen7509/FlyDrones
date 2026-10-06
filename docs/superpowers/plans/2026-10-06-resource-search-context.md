# Resource Search Context Implementation Plan

> Required execution skill: superpowers:executing-plans. Standing autonomous approval; implement inline, one independent whole-branch review.

Goal: remove hidden plugin candidates and expose actual SDK search context for the next graph binding.
Architecture: retain SDK selection authority, add fixed-upstream candidate diagnostics and a read-only context operation.
Tech: C++17, installed Gazebo/SDFormat, Python native test runner.
Spec: docs/superpowers/specs/2026-10-06-resource-search-context.md

## Global constraints
No simulator/estimator/physics. No parent environment mutation. Query 10s bound. No graph or runtime qualification. Preserve old evidence. Existing RuntimeBinding v1 unchanged.

## Review focus
Same-directory aliases, deprecated roots, relative escape, nonregular candidate, same-target symlink identity. Each covered by native synthetic runner.

## Task 1: native search diagnostics
- [ ] Write tests/native/run_search_context_checks.py exercising those cases and context fields; run on old binary and preserve assertion failures.
- [ ] Modify tools/benchmark/native/resource_resolver.cc: expose context and enumerate all plugin spellings with source attribution; retain actual SDK winner and reject distinct identities.
- [ ] Compile with installed pkg-config flags, save compiler/source/binary/dependency identities; run new checks plus both existing native runners.
- [ ] Commit implementation and test evidence references.

## Task 2: review and publication
- [ ] Independent whole-branch code/evidence review; necessary fixes RED→GREEN.
- [ ] Changed-file lint, relevant Python regression (native-only changes do not justify pretending Python verifies C++).
- [ ] Report remaining graph/VIO gaps, seal unique ZIP with member hashes/CRC, create stacked draft PR and update heartbeat.
