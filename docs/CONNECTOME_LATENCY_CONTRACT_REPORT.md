# Complete-connectome latency evidence correction

Date: 2026-10-09. Base: `ed39862aa268a714f5964998989b8de31aa77b57`.

## Scope and decision

This is a bounded correction to the existing Stage A CPU profiler. It does not
accelerate a neuron model, train weights, change the frozen formal comparison,
activate VIO networking, or qualify a flight system. Existing user approval to
continue offline work applies; no new simulation or training is needed.

The old CLI could set `passed_complete_fly_p95=true` for `--fake`: it compared
the fake's self-reported 1 ms with the 35 ms gate without checking eligibility.
For a real controller it also used the self-reported inner duration even though
an external call duration was measured. Aggregate-only reports discarded the
individual measurements. The default output could overwrite the old baseline.

The selected correction keeps the existing CPU implementation and NumPy
statistics, adds external per-call nanosecond timestamps, and uses external P95
for acceptance. A replacement benchmarking framework would add a dependency
without fixing identity or evidence preservation; changing the neural runtime
at the same time would confound measurement with optimization.

## Implemented behavior

- New reports are `flydrones-connectome-profile-v2`; historical v1 files stay
  unchanged. `total_s` and `neural_s` still mean controller-reported diagnostics.
  `outer_s` measures synchronous `step` entry to returned `Decision`, including
  return-object construction. Raw rows include both durations, start/end ticks
  and observation simulation time. Successful profiles retain every measured
  row without percentile trimming; invalid inputs refuse the profile.
- The gate requires the actual CLI full-model branch, 166,700 neurons,
  25,582,837 connections, a SHA-256-shaped model identity and at least the
  configured sample/warmup counts (currently 30/5). Fake results remain
  ineligible regardless of their speed. This metadata check is not independent
  attestation of an arbitrary supplied controller or a trained checkpoint.
- Negative, boolean, string and nonfinite timing values refuse. A neural
  component larger than its reported total refuses instead of clipping the
  residual to zero. A backward external clock refuses.
- Existing output paths refuse before controller construction; exclusive final
  file creation also prevents a competing output from being overwritten. This
  is not atomic publication or fsync durability. A partial write is preserved.
- The report explicitly identifies the synthetic black RGB/fixed-depth workload
  and CPU synchronous implementation, and keeps `trained_policy_verified=false`.
  Acquisition, warmup, flight transport and asynchronous device completion are
  outside this measurement. No GPU result can be inferred.

## Source selection

Installed versions observed: CPython 3.12.10, NumPy 2.3.4, SciPy 1.16.3 on Windows.
No packages were installed. This reuses the existing software stack.

| Component | Version / license | Interface and reason | Cost / limitation |
| --- | --- | --- | --- |
| CPython | v3.12.10 / PSF | `perf_counter_ns` externally brackets synchronous calls; includes scheduler/sleep delay | Two timer reads per call; it is elapsed host time, not sensor-to-actuator latency |
| NumPy | v2.3.4 / BSD-3-Clause | Explicit linear percentile method preserves the existing interpolation convention | O(samples) retained rows; no new runtime dependency |

Sources read: [Python timer documentation](https://docs.python.org/3.12/library/time.html#time.perf_counter_ns),
[fixed CPython implementation](https://github.com/python/cpython/blob/v3.12.10/Modules/timemodule.c),
[Python license](https://docs.python.org/3.12/license.html),
[NumPy percentile API](https://numpy.org/doc/stable/reference/generated/numpy.percentile.html),
[fixed NumPy implementation](https://github.com/numpy/numpy/blob/v2.3.4/numpy/lib/_function_base_impl.py),
[NumPy license](https://numpy.org/doc/2.3/license.html).
The live documentation may describe newer releases; fixed tags identify the
examined source versions. Accessible upstream repositories/documentation do not
prove installed-binary equivalence or a particular maintenance SLA. No new
learning algorithm or biological claim is introduced, so the existing Stage A/B
design's literature remains the algorithm reference, not evidence of this fix.

## Current learning / decision / division evidence

| Requirement | Evidence inspected | Status and remaining gap |
| --- | --- | --- |
| Complete LIF controller latency | `results/connectome-training/stage-a/baseline_profile.json` | Historical failure: external P95 1.798234715 s vs 0.035 s; not remeasured here |
| Full topology initialization | `stage-b/full-initialization/manifest.json` | Records full counts and topology hash; initialization alone is not training |
| Learning implementation | `ConnectomeConstrainedCore`, `ConnectomeCurriculumSession` | Topology-bound training implementation exists; requires partitioned sequence directories and matching parameter artifact |
| Learning speed / loss | `stage-b/smoke_report.json` | Historical synthetic smoke: 31 trainable parameters, validation loss 0.117479 to 0.002836; cannot establish full-model training speed or flight success |
| Trained controller inference | `benchmark/fly.py` vs `connectome_training/model.py` | Current profiler runs `Brain/LIFNetwork`; it does not load the learned core/checkpoint. Trained inference adapter and its latency evidence remain missing |
| Division integration | `mission_agent.py`, `task_consensus.py`, `hybrid_agent.py` | Task-ledger and policy components exist; these reads do not prove a complete trained-connectome/assignment/safety flight chain |
| Real training corpus | `CONNECTOME_CORPUS_FOUNDATION_REPORT.md`, `_full_components` | Corpus declarations/input validators exist; trustworthy nontruth capture plus actual teacher sequences still require integration evidence |

The old latency JSON SHA-256 before this change is
`40b9765ba77ad9efd6d87e926831824e969ab876b4ffe9dc02f2c407169a6534`.
The full initialization records model hash
`b6be8b3dd901e2e0893303c04058a110d6e0fb9922a69022b26514efcf06100c`
and topology hash
`ac7e555e8889285d819fe540027ed5460804feaf924a79e4431a945c63699746`.
These are inspected manifest values, not a fresh full-model execution or artifact
reload validation. Checkpoint pickle data were not loaded for this audit.

## Verification

Initial targeted run: 18 failed / 7 passed. Behavioral failures demonstrate fake
qualification, overwrite, invalid durations, component clipping and missing
external raw measurements. Six failures were missing gate-helper API, not
behavioral gate failures. After implementation: 25 passed in 7.58 s.
The real fake CLI is exercised, with controlled-clock unit cases for externally
slow/self-reported-fast calls; those clocks are test inputs, not performance data.

A read-only independent review found no actionable Critical/Important/Minor
issues in the four changed code/test files; the reviewer did not run tests.
Repository regression completed: **3,823 passed, 33 skipped, 2 warnings in
609.46 s**. Skips are not validation of the absent capabilities. The warnings
are the existing duplicate ZIP member rejection fixture and empty MaleCNS neuron
groups loader fixture. Changed-file Ruff and `git diff --check` pass. The initial
Ruff invocation corrected five import/modernization issues before the full suite.
Logs are retained in `results/connectome-latency-contract-dev-1701`.

After source commit `51a35d7`, one explicit fake CLI check retained 30 raw samples
and reported `eligible=false`, `passed=false`, reason `not_complete_model`. It is
an instrumentation check, not a new full-model benchmark.

Evidence archive: `evidence/connectome-latency-contract-dev-1701.zip`, 20 members,
SHA-256 `45f08b7b381d1725e147404e4e6b385f3aa08e40d0aeabc8ba71745f1cd12f10`.
All member hashes, lengths and ZIP CRC were verified. It includes historical
baseline/initialization/smoke JSON copies, current source snapshots, RED/GREEN/full
regression logs, the review note and next-inference research. Copies are explicitly
post-verification snapshots; the report inside precedes this seal paragraph. The
original baseline SHA-256 is unchanged. Code and evidence are local pending the
previously retained remote publication problem; no push retry is claimed here.

## Next dependency

Before claiming full learned fruit-fly performance, design an inference-only
adapter for the exact topology-bound learned core and parameter/checkpoint
identity, with causal recurrent state, deployable observations and bounded
velocity/yaw outputs. First verify analytic/tiny fixtures and checkpoint/mapping
refusals. A full initialization-only probe must remain labeled untrained; no
training, physics or flight activation is implied. Fair-baseline improvement,
division, 5/20-aircraft evidence, hardware calibration and real flight remain
unproven. Five-aircraft 0.873 RTF remains below the 0.95 gate.
