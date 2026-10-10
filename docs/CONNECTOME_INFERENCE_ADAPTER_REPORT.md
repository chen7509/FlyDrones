# Offline connectome inference adapter

Date: 2026-10-09. Scope base: `6ae9979`; artifact loader: `fef438d`;
causal controller: `1e0988a`.

## Outcome and boundaries

The existing `ConnectomeConstrainedCore` now has an offline CPU inference path
that loads identity-bound parameters/checkpoints and preserves recurrent state.
It produces bounded ENU velocity and yaw-rate intent through the existing
`Command`/`Decision` interface. It does not publish flight messages, create an
optimizer, run a curriculum, or qualify a learned policy for flight.

This core retains the existing topology-constrained **rate-based** learning
implementation. It is not the old `Brain/LIFNetwork` spiking implementation.
Neither is relabeled as the other. A full-topology initialization is not a trained
policy; a checkpoint's valid identity is not proof of training success.

| Requirement | Evidence / status |
| --- | --- |
| Same training/inference features and mapping identity | Shared public functions; analytic feature oracle and existing curriculum regressions |
| Preserve fixed topology when loading learned weights | Only four named trainable tensors accepted; exact keys, shape, dtype, finite values and metadata checked; fixed-buffer injection refused |
| Causal recurrent inference | Direct-core sequence parity, reset, camera timestamp/content checks and failure latch on explicit tiny fixtures |
| High-level ENU output limits | Existing pure `shape_command`; separate raw output retained; not the flight safety supervisor |
| Full 166,700-neuron / 25,582,837-edge execution | Not measured in this stage; requires resource preflight and separate bounded full probe |
| Trained-policy performance / learning speed | Not verified; no actual full-model training or performance claim |
| Flight, division, fair baseline or 5/20-aircraft qualification | Not tested by this adapter; existing gates remain |

## Implementation and evidence semantics

`load_inference_core` validates source/parameter/checkpoint hashes, exact feature
and output order, model/topology/mapping metadata, and CPU tensors. All checkpoint
tensors are checked before any copy. It does not apply optimizer or RNG state.
Before/after file hashes detect ordinary drift, not hostile concurrent ABA.
Returned Python model/provenance objects remain caller-owned, not a security
boundary against in-process mutation.

`ConnectomeInferenceController` uses 50 ms steps and permits at most 100 ms camera
age. Repeated camera timestamps require unchanged RGB/depth bytes and are marked
as reuse, not new VIO output. State/time/previous-command advance only after a
valid decision. A step exception latches refusal until explicit reset; close is
terminal. Seed/session counters describe this deterministic offline controller,
not VIO reset or quality fields. Input arrays alone do not prove sensor origin.

Default intent limits are 0.8 m/s, 1.2 m/s2 and 0.6 rad/s. All returned evidence
retains `training_success_verified=false` and `flight_eligible=false`. Internal
core timing is diagnostic; the external profiler remains the timing authority.
No tiny timing is extrapolated to the complete model or sensor-to-actuator delay.

## Verification record

Task 1's initial RED was a missing public feature import; Task 2's was a missing
inference module. These were API-presence failures, not demonstrated behavioral
counterexamples. The subsequent tests exercise real tiny NPZ/parameter/checkpoint
artifacts and real recurrent core calls. Task 1 related tests: 33 passed. Task 2
controller tests: 25 passed. First combined connectome suite: 171 passed in
92.81 seconds, with one warning from the intentionally invalid sparse checkpoint
fixture and PyTorch's restricted-load invariant scan.

The task completion check repeated the combined suite after the frozen-default
lint correction: 171 passed in 96.89 seconds. The independent read-only review
found no Critical/Important issue and two Minor coverage suggestions. Both were
adopted in `742be24`: nonzero yaw in the analytic ENU oracle and explicit retained
voltage/previous-command assertions after refusal. The resulting 26 controller
tests passed. These are added GREEN coverage, not behavioral RED fixes or a
second review of changed production code.

Final repository regression: **3,869 passed, 33 skipped, 3 warnings in 593.85
seconds**. The warnings are the existing duplicate-ZIP and empty-neuron-group
fixtures plus the intentional sparse-checkpoint restricted-load warning above.
Skipped tests are not validation of absent capabilities. Changed-file Ruff and
`git diff --check` passed; no whole-repository lint pass is claimed. Regression
includes existing tiny synthetic curriculum tests; no full training job was
started. Final production source was already committed before this full suite.

The original Stage A baseline file SHA256 remains
`40b9765ba77ad9efd6d87e926831824e969ab876b4ffe9dc02f2c407169a6534`.
No old formal comparison, model or evidence archive was replaced.

## Resource and next dependency

The design recorded 1,001,824 KiB free physical RAM at its initial check and
requires a conservative 4 GiB free before full-core construction. That margin
is not a measured peak requirement. This host has approximately 15.7 GiB usable
physical memory; no unrelated application is terminated to force a result.

After the suite exited, the 2026-10-09 04:39:51 +08:00 host check reported
**1,544,440 KiB free (about 1.47 GiB)**, below 4,194,304 KiB. Full construction and
timing were therefore **not attempted**, not reported as an algorithm failure.
The Windows relevant-process scan was empty and WSL listed no running
distribution. This is an instantaneous resource observation, not a permanent
hardware infeasibility claim or measured model peak.

After this interface verification, the next full-model step is an independently
declared inference-only resource/timing probe with explicit initialization or
checkpoint provenance and external wall timing. The Stage A old-LIF 35 ms gate
and historical failing timing remain unchanged. The learned core needs its own
measurement; the old CLI still selects the old runtime.

Trustworthy training corpus/teacher integration and full learned division remain
separate missing evidence. Existing WSL2 five-camera 0.873 RTF remains below
0.95; no native Linux installation, HITL or real flight is claimed. Previously
retained remote upload failures remain a publication limitation; this stage
does not retry a large push, rewrite history or bypass TLS.

## Sealed evidence

`evidence/connectome-inference-adapter-dev-1701.zip` contains 41 members,
94,862 bytes, SHA256
`f245d88a9b7b273b4ddd1bc8cfd06a5bb626a5504fb4adf13e12910e68d98c5d`.
Every member's bytes/hash and ZIP CRC were checked. It includes API-presence
RED logs, targeted and whole-suite results, independent review disposition,
post-test resource refusal, historical baseline identity, source copies and
next-dependency notes. Source/document copies are post-verification snapshots,
not runtime pre/post evidence. The bundled report precedes this seal paragraph;
its ledger still labels sealing as pending, superseded by this verified archive
record. Source and archive remain local pending the existing publication issue.
This completes the bounded adapter plan, not the overall FlyDrones objective.
