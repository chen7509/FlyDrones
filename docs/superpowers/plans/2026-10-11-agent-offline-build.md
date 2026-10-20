# Agent offline build plan

**Spec:** [Bounded offline XRCE Agent build](../specs/2026-10-11-agent-offline-build-design.md)

- [x] Recheck resources and preserve the previously sealed source/object stores.
- [x] Create an isolated local URL-rewrite policy and combined Fast-CDR object store; test exact positive and wrong-object rejection. Preserve the three failed preparations and the explicit build-only Micro-CDR tag alias.
- [x] Copy the fixed Agent source and record a minimal build-policy diff; generate top-level CMake graph without network.
- [x] Configure/build with one job and a wall deadline. Preserve all failures, logs, selected nested caches and artifacts.
- [x] Independently audit source commits, selected package paths, executable hash and runtime libraries; run bounded usage checks and a relocated bundle check.
- [x] Report verified/untested/failed boundaries, seal evidence, verify checks, commit/push only `personal`, and update PR65.
