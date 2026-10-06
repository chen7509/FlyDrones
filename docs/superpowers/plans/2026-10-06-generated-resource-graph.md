# Generated Resource Graph Implementation Plan
> Execution: superpowers:executing-plans, inline and one independent whole-branch review under standing authorization.
Goal: enforce explicit original-source dependencies before capture initializes native clients.
Architecture: native bounded local lookup, strict query client, original XML graph, RuntimeBinding v2.
Tech: C++17 installed SDK, Python3.12, existing snapshot and XML scanner.
Spec: docs/superpowers/specs/2026-10-06-generated-resource-graph.md

## Global constraints
No physics/estimator. Query10s/graph60s/512queries/256documents/4096edges/source8MiB. No discovery whitelist growth. Preserve errors and all historical evidence. Runtime coverage remains false.

## Review focus
Semantic mismatch between SDK selection and candidate enumeration; untrusted structured output; source changed after baseline; cycles/unsupported edges omitted; preflight failure skips post. Each owned by corresponding tests below.

## Tasks
- [ ] Native bound-uri: write real temp-input refusal and selection tests, witness old binary RED; implement constrained native candidates using pinned source plus installed APIs; compile/test and freeze.
- [ ] Strict client + graph: tests first for malformed/duplicate/nonzero/timeout/changed files/recursive cycle/repeats/missing config/unsupported; implement query journaling and declared-only walk.
- [ ] RuntimeBinding v2: tests for v1 legacy status, v2 graph-before-pre ordering, post after graph failure, merged baseline drift. Integrate and run targeted regression.
- [ ] One offline named generated-world binding with current frozen resolver and original sealed inputs. Preserve failure and actual context; no old normal physics rerun.
- [ ] Independent whole-branch review and single necessary fix pass, full relevant tests, report/evidence/draftPR/heartbeat.
