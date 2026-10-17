# Connectome corpus v2 index integrity stage

The declared curriculum contains six stages and exactly 54 jobs: three world
seeds per stage, three rollout seeds per world. This stage adds an offline
consumer for a complete corpus index. It checks exact job order and identity,
canonical generated worlds, depth-mask-v3 sequence contents, per-run receipts,
file hashes and path confinement. It does **not** authenticate who produced
those files. The returned audit always has `source_authenticated=false`,
`training_eligible=false` and `eligible_for_fair_comparison=false`, and it does
not expose training samples to the learning pipeline.

`CorpusConfig` now retains the declared SHA-256 identities of its benchmark
configuration and vehicle model. The index consumer rechecks both before
inspection, so a later file change cannot be silently accepted under the
earlier configuration digest. It binds the parsed manifest and receipt to
their checked bytes, checks sequence bytes around the existing loader, and
uses file identities to reject hard-linked evidence reused under new names.
These checks detect ordinary read-time drift; they are not an atomic
filesystem snapshot or a defence against hostile ABA changes. In particular,
the existing `load_sequence` reopens its inputs, so an adversary able to swap
both inputs and swap them back during that call can defeat the before/after
hashes. No training eligibility follows from this audit.

The synthetic 54-job fixture exercises correct order and refusal of missing,
extra, duplicate, relabelled or failed jobs; changed world, sequence and
receipt hashes; path escape or missing files; repeated payloads; hard-linked
evidence reuse; forged EGO
teacher/source labels; post-load source drift; and changes between hash and
parse. The reviewer found the double-read drift gap before the fix. Both new
drift tests and a hard-link reuse test failed on the earlier code and passed
after the fixes. The fixture
contains text placeholders for ULog/source/teacher/calibration evidence; it
is deliberately not a PX4 capture. The symlink creation test is skipped on
this Windows host because link creation is unavailable; the path rejection
branch remains unverified here.

Verification: the final adjacent connectome suite reported **538 passed, 2
skipped, 2 existing warnings** in 331.96 seconds. One skip is the Windows
symlink test; the other is an existing optional test. Changed-file Ruff and
`git diff --check` passed. An initial targeted invocation without `PYTHONPATH` failed at test
collection (`ModuleNotFoundError`), and a first adjacent-suite run with only
`src` on the subprocess search path failed two inference-worker tests (`No
module named 'tools'`), with 533 other tests passing and 2 skipped. Both
failed invocations remain recorded; the corrected root-plus-src invocation
is the one used for the final checks. No physical simulation, Docker EGO,
OpenVINS, PX4, Gazebo or MaleCNS training was launched for this stage. Host
free memory was about 1.9 GiB during verification, below the unchanged 4 GiB
full-model probe gate. The older first PX4 TIMESYNC failure and five-camera
WSL2 0.873 RTF result against the 0.95 gate remain unchanged.

| Status | Result |
| --- | --- |
| Verified | Structural integrity of a synthetic 54-job corpus index and the stated refusal cases. |
| Implemented only | An integrity-only consumer and persistent source-hash fields on `CorpusConfig`. |
| Not tested | A genuine non-truth PX4 EKF2 plus calibrated-camera producer, checked EGO teacher capture, full MaleCNS training, physical fairness comparison, 5/20-drone performance, HITL and flight. |
| Failed or blocked | Missing real qualified corpus and memory below the 4 GiB training/physical probe gate; the historical PX4/WSL2 failures remain. |

Next is a distinct producer and eligibility gate that verifies actual source
and teacher process provenance, ULog, calibration, sensor/reset health and
the complete failure ledger. Self-declared receipt labels or hashes from this
stage must never be promoted to that gate by themselves.
