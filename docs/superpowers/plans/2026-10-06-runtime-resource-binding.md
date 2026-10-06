# Runtime resource binding plan
> Use superpowers:executing-plans inline with existing authorization.
Spec: docs/superpowers/specs/2026-10-06-runtime-resource-binding.md
Goal: persist declared baseline/generated/env evidence at actual capture setup and separate phase mappings from fullclosure.
Review focus: no nativeclient before preclose; cleanup captures startup failure; arbitrary schema/env omissions cannot pass; actual selected paths must be covered; mapping false positives/unknowns retain evidence.
- [x] RED tests for RuntimeBinding schema/copies/env/baseline and mapping refusal, then minimal GREEN implementation.
- [x] RED capture flag/integration lifecycle tests, wire before imports and cleanup after shutdown, preserve existing modes.
- [x] Fixed offline binding of prior captured files plus real selfmaps without initializing simulation; regression/review/report/evidence/draft PR, retain remaining closure and gauge gates.
