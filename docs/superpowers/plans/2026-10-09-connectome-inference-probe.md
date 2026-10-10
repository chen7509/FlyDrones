# Bounded CPU inference probe implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. TDD tasks,
> preserve ledger, one final independent review. Existing automatic approval applies.

**Goal:** A bounded, identity-bound CPU measurement command for the real offline core.
**Architecture:** Stdlib parent/preflight, one direct worker, reuse loader/controller/
profiler/gate; streaming rows preserve failures. No flight/network/training jobs.
**Tech Stack:** Python3.12, existing PyTorch/NumPy and Windows memory API.
**Spec:** docs/superpowers/specs/2026-10-09-connectome-inference-probe-design.md

## Global constraints

Full RAM4GiB, CPU14 default threads, warmup5/samples30, P95 .035s; no reductions
of eligibility gates. Total timeout180s max300; load60s and step5s checked on return.
50ms steps/100ms camera,120x160 synthetic RGBD. Output exclusive, all failures kept.
No Linux installation, model edits, topology/algorithm substitution or old evidence overwrite.

## Task 1: Streaming external timing

Files: src/flydrones/connectome_training/profiling.py;
tests/connectome_training/test_profiling.py.
Produces `profile_controller(controller, observations, *, on_sample=None)`.

- [x] RED callback is after measured finish; receives raw timestamps and defensive
  copy; exception aborts after preserving earlier rows. Existing stats unchanged.
- [x] Implement optional callback, no change to default behavior or timing boundary.
- [x] Run `python -m pytest tests/connectome_training/test_profiling.py
  tests/connectome_training/test_profile_baseline.py -q`; commit.

## Task 2: Parent and actual worker

Files: tools/connectome_training/profile_inference.py;
tests/connectome_training/test_inference_probe.py.
Consumes Task1 hook and previous real loader/controller. Produces `ProbeSpec`,
`available_memory_bytes()`, `run_probe(spec, output)`, private worker entry and CLI.

- [x] RED strict fields/checkpoint pairing, low/unknown RAM refuses before spawn,
  exclusive directory, request/input drift, retained errors, actual tiny worker
  lifecycle and camera reuse, timeout cleanup/partial logs, no false full gate.
- [x] Implement fixed worker command, stdlib preflight, request digest, direct-child
  bounded ownership, worker recheck, profiler journaling and reports per spec.
- [x] Run `python -m pytest tests/connectome_training/test_inference_probe.py
  tests/connectome_training/test_profiling.py tests/connectome_training/test_inference.py
  tests/connectome_training/test_inference_artifact.py -q`; commit.

## Task 3: Actual CLI evidence and review

Files: docs/CONNECTOME_INFERENCE_PROBE_REPORT.md;
results/connectome-inference-probe-dev-1701 and corresponding evidence ZIP.

- [x] After idle check and source commit, once call actual full CLI against existing
  full initialization; preserve resource refusal if <4GiB, never force allocation.
  Run separate tiny fixture invocation; never label it full or trained performance.
- [x] Full pytest, changed Ruff/diff, one independent review. Important findings
  get behavioral RED/GREEN; minor coverage honestly labeled.
- [x] Record source/config/version/input hashes, report actual outcomes/limits,
  seal member hashes/CRC, commit locally; retain remote publication constraint.

## Review focus

No spawned model when memory unavailable; no successful result after timeout;
no callback I/O inside measured step; no camera timestamp fabrication on reuse;
no tiny/initialization evidence promoted into trained full or flight performance.

Validation note: full suite 1 failed/3897 passed/33 skipped; focused existing preflight file 9 passed. Original stat-change failure root cause unresolved. Task 3 validation remains open; evidence is sealed with this failure retained, not declared fully passing.

Follow-up: implementation/review/evidence tasks are complete with the later cfd3e8e full regression3920passed33skipped and final coverage13passed. The initial failed suite remains sealed; its original changed stat field remains unproven. Full inference was resource-refused and not qualified. Bounded instrumentation plan completion is not goal completion.
