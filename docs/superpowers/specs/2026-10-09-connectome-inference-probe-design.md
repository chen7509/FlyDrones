# Bounded CPU connectome inference probe

The user has preapproved continued plans/implementation. This adds a real command
for measuring the completed offline rate-core adapter; it does not train, publish
flight messages, activate PX4/Gazebo, or change historical formal evidence.
Previous stage c518cee is complete. Current free RAM is only 1,509,004 KiB, so a
full run remains disallowed under the existing 4 GiB conservative preflight.

## Approach and research

Adopt an isolated direct Python worker under a standard-library parent. Running
inside the parent cannot bound a blocked native call. Reusing the historical
LIF CLI as if it selected learned inference would mislabel the model. Reuse the
new loader/controller, existing external profiler and existing numeric gate.
No optimizer, topology rewrite, pruning, retraining or new dependency.

* CPython installed 3.12.10, PSF license; fixed
  [subprocess source](https://github.com/python/cpython/blob/v3.12.10/Lib/subprocess.py)
  and [official API](https://docs.python.org/3.12/library/subprocess.html).
  Upstream has maintained release/development infrastructure; versioned docs now
  render 3.12.15 and do not prove installed patch equivalence. Timeout kills and
  waits for the direct child; creation/OS scheduling are not hard real-time.
* Existing PyTorch 2.14.0 CPU, BSD-style license. Fix intra-op threads before
  computation using [official set_num_threads](https://docs.pytorch.org/docs/2.14/generated/torch.set_num_threads.html).
  [Original implementation paper](https://papers.neurips.cc/paper/9015-pytorch-an-imperative-style-high-performance-deep-learning-library)
  supplies background, not a performance guarantee for this connectome.
* Windows installed system API
  [GlobalMemoryStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)
  supplies instantaneous available physical bytes. It is an OS API, not a newly
  vendored open-source dependency. Reuse repository process-peak measurement
  backed by [PROCESS_MEMORY_COUNTERS](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters).
  Peak includes interpreter/import/model work, not just neuron tensors.

Adaptation cost: one small CLI/worker and a post-sample hook in the profiler.
Memory checks are preflights, not reservations or a proof of feasible peak usage.
Only Windows available-memory observation is supported initially; other platforms
refuse clearly instead of inventing capacity. No native Linux installation.

## Inputs and execution

CLI `tools/connectome_training/profile_inference.py` accepts required model,
parameter directory and NEW output directory. Mode defaults full-male-cns;
tiny-fixture is explicit and never full-qualified. Optional checkpoint directory
requires checkpoint/config/dataset SHA256 identities as an all-or-none group.
Default threads14 (range1..64), warmup5 (0..100), samples30 (1..1000), seed20260922
(nonnegative int), total timeout180s (0<value<=300). No flag reduces full RAM
minimum 4*1024**3, P95 limit .035s or eligibility requirements warmup5/samples30.

Create output exclusively; request JSON persists arguments, exact input paths and
SHA256 before dispatch. Missing/bad inputs leave a structured failed result and
no model. Full parent and worker independently check available memory before
constructing a model; resource refusal retains measured bytes and no performance
pass. Parent itself uses only standard-library imports. Worker uses the existing
package, sets CPU threads before core construction and validates parent-pinned
input hashes before/after all inference. Same request hash is passed on command
line; a changed request fails. No global host process termination or new workers
from the child. One child is killed/waited on timeout or parent interruption.
Record actual owned PID, return code, timeout/kill outcome and wall duration.
Do not claim coverage of hypothetical escaped descendants.

Use synthetic fixed 120x160 uint8 black RGB, float32 8m depth, position(0,0,1),
zero velocity/yaw/yaw-rate, goal(8,0,1). SequenceFrames advance50ms; images advance
100ms starting at50ms, retaining identical content on reuse. Label these inputs
synthetic and never sensor/accuracy evidence. Warmup and measured calls share
one continuous state and are separately journaled. Initialization time, complete
child wall time and externally timed step latency remain separate.

Profiler gains optional keyword-only on_sample(row), called after the external
end timestamp with a defensive copy. Log and flush each warmup/measured sample
immediately; I/O is outside step latency but inside whole-worker wall time.
Callback errors abort, preserving prior rows. Total parent timeout bounds stalled
native calls. Returning load duration>60s or step duration>5s is additionally
rejected after return, not advertised as immediate cancellation at those limits.
All partial samples and errors remain. Reports use exclusive writes; no retry in
an existing output directory.

Completed worker result includes loaded provenance, raw samples/statistics,
torch version/git version/threads, peak process working set, synthetic input
profile and timing eligibility. Reuse existing evaluate_latency_gate using loader
identity/count/hash plus actual outer P95, and reject insufficient warmup.
Timing pass is only CPU synthetic-input inference, never training success,
biological fidelity, sensor-to-actuator latency or flight eligibility. Tiny runs
always ineligible. Parent retains worker report hash and distinguishes completed,
resource_refused, failed and timed_out; partial worker output cannot be success.

## Validation and completion

Tests: strict arguments/checkpoint pairing, byte-count boundary, unknown memory,
full refusal before spawn/construction, hash drift/request mutation, exclusive
outputs, real tiny CLI lifecycle and camera reuse, invalid source/model results,
child timeout/kill/wait and stderr retention, post-clock callback with defensive
copy/exception, gate eligibility and retained partial samples.
One new actual full CLI invocation is allowed only after source commit and idle
resource check; current resources predict refusal, not permission to force load.
Use one separately labeled real tiny fixture execution to prove the CLI path.
Run targeted/regression checks and independent review, preserve all failures and
sealed artifacts. Whole FlyDrones goal remains open; original baseline unchanged.
