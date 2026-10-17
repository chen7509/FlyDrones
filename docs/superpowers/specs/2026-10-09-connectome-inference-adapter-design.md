# Offline connectome inference adapter

## Intent and boundaries

Connect the existing topology-constrained learning core to a testable synchronous
inference boundary. This is the next gap after the externally timed Stage A
profiler. Preserve all neurons, signed topology, learned mappings and recurrent
state; never relabel PPO, the old LIF runtime, a tiny fixture, or an initialization
as a trained complete controller. User authorization covers offline implementation
and verification without per-step approval. No networking, simulation, training,
PX4 activation or expansion to more aircraft is part of this stage.

The chosen architecture loads the existing core and exposes a CPU-only stateful
adapter. Directly wrapping `ConnectomeCurriculumSession` would construct an
optimizer and evaluate datasets merely to infer. Reimplementing the core in
NumPy would introduce numerical/dynamics differences before there is a reference
path. Neither alternative is adopted. The original `Brain/LIFNetwork` and frozen
formal comparison stay unchanged.

## Research and resources

Installed PyTorch is `2.14.0+cpu`, git version
`08187d9e0fba026dc8217405802ab5381dc88d90`, with 14 CPU threads and no CUDA.
Use its existing BSD-style license, `Module.eval`, `inference_mode` and the
repository's restricted `load_checkpoint(weights_only=True, map_location=cpu)`.
Official references: [module evaluation](https://docs.pytorch.org/docs/2.14/generated/torch.nn.Module.html#torch.nn.Module.eval),
[inference context](https://docs.pytorch.org/docs/2.14/generated/torch.autograd.grad_mode.inference_mode.html),
[serialization](https://docs.pytorch.org/docs/2.14/notes/serialization.html),
[upstream license](https://github.com/pytorch/pytorch/blob/v2.14.0/LICENSE),
[upstream project](https://github.com/pytorch/pytorch).
The project exposes current development/release infrastructure; this does not
prove binary equivalence or a maintenance SLA. No dependency install is needed.
This is adapter engineering, not a new biological algorithm: the existing Stage B
rate-based sigmoid core is explicitly distinguished from stochastic spiking LIF.

Current host has 16,460,348 KiB physical memory, only 1,001,824 KiB available at
the initial check. Full construction duplicates several 25,582,837-edge sparse
arrays: two int64 COO coordinates alone need 409,325,392 bytes, excluding values,
sorting/coalescing temporaries and buffers. Do not force a full run under current
pressure, terminate unrelated applications, or call tiny results full results.
After tests, recheck capacity; if less than a conservative 4 GiB is available,
record full construction/timing as not attempted for resource reasons. This is
a preflight margin, not a measured peak-memory requirement or algorithm failure.

## Shared interfaces

Expose the existing `frame_features(SequenceFrame) -> np.ndarray` for both training
and inference with unchanged feature order/formulas. Promote the identical
mapping digest into `parameters.parameter_mapping_digest(ParameterSet) -> str`;
curriculum checkpoint identities must remain byte-identical. No teacher target is
needed for inference.

`load_inference_core(model_path, parameters_path, *, mode, checkpoint_path=None,
checkpoint_identity=None)` returns a loaded CPU core and provenance. Modes are
`full-male-cns` (default) and explicit `tiny-fixture` (at most 1,024 neurons, not
full-labeled). Validate source hash, parameter archive, full counts when relevant,
topology, exact FEATURE_NAMES and output names `(vx,vy,vz,yaw_rate)` before use.

`CheckpointIdentity` pins checkpoint SHA256, curriculum config digest and dataset
digest. All three must be lowercase SHA256 hex. Checkpoint path and identity are
both present or both absent. Derive model identity, topology and mapping hashes
from the loaded source; refuse incompatible metadata. Accept exactly the four
named trainable tensors, with exact shape/dtype, CPU strided storage and finite
values; reject fixed-buffer injection. Validate all before copying any. Do not
restore optimizer or global RNG. Record file hashes before/after ordinary loading
and refuse drift; this is not hostile-ABA protection. Set eval mode and disable
gradients. Initialization remains labeled `initialization-only`; loading an
identity-verified checkpoint does not itself prove training success.

## Stateful inference contract

`ConnectomeInferenceController(loaded, limits=InferenceLimits())` consumes only
`SequenceFrame` via `step`, with `reset(seed)` and `close`. CPU synchronous,
single-owner use only. Retain recurrent state across calls, reset to zeros only
on explicit reset, and return the existing `Decision`/ENU `Command` types.

Pin 50,000,000 ns simulation increments; first call advances one such interval.
Times must be integer (not bool), nonnegative int64-range. Frame time cannot be
future, regress, or be older than 100,000,000 ns. A repeated 10 Hz camera image
at a 20 Hz policy step is permitted and explicitly labeled reused; its RGB/depth
content must be unchanged at the same timestamp. This is not a new VIO estimate.
Require nonempty uint8 RGB with three channels and matching positive finite depth,
finite state/features, and finite `(1,4)` outputs/`(1,n)` next state.

Outputs already represent ENU m/s and CCW rad/s according to training labels;
do not reinterpret them as body coordinates. Retain raw output and separately
apply existing `shape_command` using defaults 0.8 m/s, 1.2 m/s2 and 0.6 rad/s,
with positive finite limit validation. This is offline intent shaping, not a
replacement for the safety supervisor or PX4. All decisions say
`flight_eligible=false`, `training_success_verified=false`, core kind and origin.

Only commit next state, prior command and times after successful validation.
Any step exception locks failure; later steps refuse until reset. Close is
terminal. Retain local session/call counts and failure reason; these are not VIO
quality/reset fields. External profiling remains authoritative; internal timing
is diagnostic. No arbitrary source-to-actuator latency claim.

## Verification and completion

Analytic/tiny tests cover exact feature parity, checkpoint identity/tamper,
immutable buffers, wrong keys/shapes/dtypes/nonfinite values, continuous/reset
state, ENU output/limits, image reuse/change, timestamps, fail latch and close.
Compare adapter raw outputs to direct calls of the existing core with the same
state/features; use explicit analytic zero-topology/readout cases as a separate
oracle. All fixtures retain tiny labels. No flight or trained complete-model pass
is inferred. Run affected and whole-repository tests, changed Ruff/diff, one
independent review, and retain evidence plus resource refusal/full-probe status.
