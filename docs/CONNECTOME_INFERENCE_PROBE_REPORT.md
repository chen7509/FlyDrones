# Bounded learned-core CPU inference measurement

Date: 2026-10-09. Base c518cee; design c73466b; streaming profiler8bbeff5;
actual parent/worker a2e80de. Scope is offline instrumentation, not flight.

## Actual outcome

The real full-model command was invoked once against the existing initialization
artifact. Parent memory observation returned **1,325,146,112 available bytes**
versus the fixed **4,294,967,296-byte** preflight. It wrote request/result evidence,
returned exit2/resource_refused and **did not start a worker or load the model**.
Its request deliberately has input_hashes=null because no files were qualified
for dispatch. This is a capacity refusal, not a model failure, latency measurement,
checkpoint validation or permanent hardware infeasibility conclusion.

A separate persistent synthetic tiny fixture exercised the real CLI, worker,
loader and controller: 16 neurons/2 signed connections, initialization-only,
1 CPU thread, five warmup plus30 measured calls. Worker62092 exited0 and was
reaped; no termination signal was sent. Parent child wall time4.1337564s, load
time.0112023s, peak process working set247,631,872 bytes. Raw timestamps/logs retain
all35 calls and10Hz images reused by the20Hz policy. Outer P95.0007182s is **only
tiny synthetic-input timing** and cannot be compared as improvement over the
historical complete LIF runtime. Gate eligible=false/passed=false with
not_complete_model. Training/flight eligibility remain false.

| Item | Status |
| --- | --- |
| Stream samples after external end timestamp; defensive copy; writer failure refusal | Implemented and targeted tests passed |
| Parent and worker capacity gates; declared artifact/request hashes; new outputs only | Implemented and tests passed |
| Real child timeout, kill/wait, retained stdout/stderr | Tested on a short-lived synthetic child, not a full model timeout |
| Actual tiny inference command and retained35 rows | Completed; no full/training/flight pass |
| Actual complete rate-core latency/peak memory | Not measured: parent refused before spawn |
| Initialization-only full probe versus trained checkpoint | Loader supports both; this study did not run a trained checkpoint |
| PX4/VIO network, training jobs, division and5/20-aircraft validation | Not executed by this stage; overall goal remains open |

## Design choices and limits

The parent uses only standard-library imports. It hashes the selected input and
implementation files before allowed dispatch; the child checks the request hash,
files and available memory again, including after imports and immediately before
constructing the core. Ordinary file drift is detected, not hostile ABA or full
runtime dependency closure. The declared source set is a selected subset.

The existing loader, recurrent controller, external timing profiler and numeric
gate are reused. No topology, feature formula, checkpoint tensor set or old LIF
runtime was replaced. The optional profiler callback occurs after timing and
gets a defensive copy; its I/O contributes to whole-worker duration, not step
latency. Warmup/measured phases share recurrent state. Static black RGB/8m depth
and fixed state/goal are labeled synthetic, not sensor or navigation evidence.

Default total worker timeout180s, maximum300s. Model-load60s and step5s limits
are checked after return; the parent total timeout handles stalled native calls.
OS process creation/scheduling/termination do not provide hard real-time
guarantees. Cleanup is limited to the owned direct worker, whose implementation
does not launch descendants; hypothetical escaped descendants are not certified.
Memory availability is an observation, not a reservation or measured peak margin.
The available-memory API is currently Windows-only; unsupported platforms refuse.

Official API/source/research, versions, licenses and adoption reasons are in
`docs/superpowers/specs/2026-10-09-connectome-inference-probe-design.md`.
No package installation or native Linux setup was needed.

## Verification

Task1 RED: two failures for the absent on_sample keyword; after implementation27
related tests passed. Task2 initial24 failures were missing-module assertions,
not24 demonstrated behavior bugs. The first24 tests then passed. An added process
creation failure counterexample showed worker_started=true incorrectly; it
failed1/passed2, then the record was moved to the actual PID callback. The final
affected suite passed91 tests (12.17s task completion check), with the known
sparse-checkpoint warning. The other two added boundary cases were already GREEN.

Independent read-only review of c518cee..a2e80de found no Critical/Important/Minor
change request. Optional further coverage of interrupted parents and post-import
memory loss was suggested, not reported as a discovered defect. The reviewer did
not execute tests or models.

Full regression finished with **1 failed, 3897 passed, 33 skipped, 3 warnings in
610.37 seconds**. The failure was the unchanged
`test_preflight_main_has_no_network_or_runtime_side_effects[False]`:
`record_worker_environment` rejected differing before/after file stat results.
Neither that production file nor its test changed in this stage. A separate
focused rerun passed all 9 tests in 8.62 seconds. A 200-file stat/read/stat
experiment observed zero mismatches. These checks do not identify which original
stat field changed or establish the root cause; no guard was weakened or fix
claimed. The initial failed suite remains authoritative evidence of an unresolved
intermittent regression. **Full regression is not qualified as passing.**

Changed-file Ruff and diff checks passed. The three warnings concern an intentional
duplicate ZIP member, sparse checkpoint validation, and missing neuron groups.
Skips are not validated execution. Implementation review remains clear, but stage
validation is incomplete until the existing preflight failure is diagnosed.

## Remaining work

Full learned-core measurement still needs an allowed resource state. Do not retry
the same refused attempt, lower the RAM floor, terminate unrelated applications,
or promote the tiny measurement. The current4GiB threshold is a conservative
preflight, not a claim that4GiB is enough for every full-model artifact.

Independent work can continue on connecting identity-bound learned inference to
the benchmark observation/control interface while preserving the historical
formal comparison and explicit policy kind. Trustworthy nontruth teacher/corpus
integration, full learning/division and held-out baseline evidence remain missing.
The prior0.873 five-camera RTF remains below0.95. Hardware calibration, HITL and
real flight remain external evidence requirements. Existing remote publication
failure is separate; this stage preserves local work and does not retry large
uploads, merge, rewrite history or bypass TLS.


## Next dependency inspection

Read-only inspection confirms `tools/benchmark/run_episode.py` still instantiates
`FullFlyController`; it does not consume the new recurrent inference adapter.
Its `Observation` interface explicitly labels current odometry/camera pose as
model-truth-derived. An independent offline bridge therefore remains necessary,
with an explicit policy identity and input provenance. No physical benchmark,
ODOMETRY, training job or new controller activation was started during this check.
