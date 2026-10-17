# OpenVINS receiver preflight: parameter rollback correction

Date: 2026-10-08

## Finding and scope

Read-only review of Task 4 found a gap in its claimed rollback coverage. The
old implementation added a parameter to its restoration list only after a
successful acknowledgement. A remote write followed by a lost acknowledgement
could therefore remain applied. Validation inside the mutation loop also
allowed a malformed later value to strand an earlier write. No real PX4
parameter was touched: the failures were reproduced with a stateful synthetic
transport whose receiver state changes before the reply is lost.

This is bounded correction of the existing Task 4 contract, not Task 5
authorization or live transport implementation. Prior archives and all physical
failures remain intact. The old implementation-bound preflight is superseded
for future use; none of its historical fields are rewritten.

## Source evidence and choice

The fixed PX4 commit `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`
(`BSD-3-Clause`) invokes `param_set` before `send_param` in
`src/modules/mavlink/mavlink_parameters.cpp`. Snapshot SHA-256:
`1f3c0d1cc1195564ad5b8ec0f1d742b47496273ca848cfee855c8a66dc07eb53`.
The [official parameter protocol](https://mavlink.io/en/services/parameter.html)
likewise treats the response as a report after a set request. Consequently,
missing a response cannot demonstrate absence of a state change.

Reuse the already selected PX4/pymavlink path and correct local transaction
bookkeeping; no dependency or runtime process is added. Upstream maintenance
metadata and pymavlink 2.4.49 LGPL package provenance are inherited from the
sealed Task 4 research, not newly claimed observations. Neither this correction
nor a different MAVLink library can make a dropped response proof of a failed
write. Installing a bridge or repeating a physical VIO run would not resolve
this local state-management bug.

## Corrected behavior

- Validate a copied, complete desired profile before any transport access.
- Mark writes as attempted before calling the transport and restore every
  attempt in reverse order, even if its response is missing or raises.
- Treat only boolean `True` as acknowledgement; keep the first apply failure.
- Attempt restore readback even when its acknowledgement fails. Preserve both
  outcomes and continue restoration of the remaining parameters.
- Verify the complete final baseline. Detect unrelated drift without silently
  overwriting it or reporting a successful rollback.
- Protect the entire apply phase, including cancellation between transport
  calls. Attempt remaining restoration, preserve the audit in `last_result`,
  then re-raise the interruption.

This helper has no network/process surface. A future live transport must impose
its own bounded calls, validate MAVLink source identity and parameter encoding,
and retain `last_result` if interrupted. Process death, SIGKILL, further
instruction-level interruptions during cleanup and unreachable PX4 cannot be guaranteed to
restore by this synchronous helper. It reports ordinary failure; it is not an
atomic distributed transaction. The bounded study callback is still outside
this pure synthetic apply/restore helper and needs Task 5 integration.

## Verification

Evidence directory: `results/openvins-parameter-rollback-dev-1701`.

The initial test run produced 11 assertion failures against the original
implementation (`red.txt`). After correction, 32 targeted tests passed
(`green-v1.txt`), including the 21 existing preflight/extractor checks.
Independent review found one further Important cancellation window between a
write returning and its verification. A deterministic trace-hook test reproduced
the stranded mutation (`review-red.txt`: one assertion failure). Protecting the
whole apply phase resolved it; `review-green.txt` records 33 targeted passes.
The pre-review full suite passed 1,978 tests, with three existing skips and two
existing warnings; this does not substitute for the final-code regression.
Final-code regression passed **1,979 tests, three skipped, two existing
warnings in 218.78 seconds** (`full-tests-final.txt`). Changed-file Ruff and
`git diff --check` passed. The reviewer confirmed its finding resolved and
reported no remaining blocking finding in this bounded diff.

Correction implementation commit: `bc8ab60d65c9516184c2dd1d6854586ff1915050`.
The one-shot preparation tool generated a new `preflight.json` in this evidence
directory, bound to that commit and the actual implementation/spec/test files.
It consumes two byte-identical members from the original Task 4 archive;
`retained-input-members.json` preserves member paths, lengths and hashes.
Endpoint, retained baseline, model/resources, clock rules and ULog requirements
are unchanged. `terminal-audit.json` verifies those identities, old-archive and
old-preflight preservation, four explicit synthetic transaction traces, and
the test logs. It reports no failures, synthetic rollback qualification true,
and all physical/network/live-parameter/fusion/arming/Task-5 flags false.

| State | Scope |
| --- | --- |
| Verified | The 12 synthetic regressions above; existing preflight/extractor tests. |
| Implemented | Corrected transport-neutral parameter restoration bookkeeping. |
| Verified | Independent review resolution, final regression, implementation-bound replacement preflight. |
| Not tested | Live MAVLink parameter read/write/restore, receiver parity, EKF2 fusion. |
| False | Network ODOMETRY, physical study, live PX4 access, arming, Task 5 authorization. |

## Sealed correction evidence

`evidence/openvins-parameter-rollback-dev-1701.zip`: 207,125 bytes, 31 members
including the embedded manifest. SHA-256:
`299b64cc757b490711a04cf2fd91ad3295e46fd227372cfbfc4ee3c634c3bc79`.
CRC and all member hashes passed. The archive contains both red runs, both
full-suite runs, targeted greens, review result, source snapshots, explicit
synthetic transaction events, exact retained input copies, replacement
preflight, terminal audit, implementation/tests/spec/plan and the report before
this sealing paragraph. No historical archive was changed or replaced.
