# Offline PX4 receiver field-parity preparation

Date: 2026-10-08

## Purpose and boundaries

This supplies the field-comparison component required by Task 5 of the existing
OpenVINS/EKF2 plan. It runs on retained packet bytes and ULog only. It cannot
publish ODOMETRY, alter PX4 parameters or launch a simulation. Task 5 itself is
still unexecuted and separately gated.

The comparator never turns a field match into complete receiver qualification.
Its output always keeps `receiver_stage_qualified`,
`timesync_convergence_qualified` and `ekf2_fusion_qualified` false. Actual send
provenance, runtime identity, disarmed state, no-fusion flags, clock convergence,
upstream health/fault identities, parameter rollback, rate and complete-run
coverage remain required alongside this component before Task 5 can pass.

## Research and selection

The authoritative receiver is PX4 commit
`d6f12ad1c4f70ad3230afd7d86e971421e02fef4`, BSD-3-Clause. Its receiver,
Timesync and TimesyncStatus sources are copied with hashes from the existing
Task 4 snapshots. `msg/versioned/VehicleOdometry.msg` was fetched at the same
commit; the initial non-versioned path returned HTTP 404, retained as a failed
source lookup. Current online documentation is guidance, not a substitute for
the pinned source:
[VehicleOdometry](https://docs.px4.io/main/en/msg_docs/VehicleOdometry),
[MAVLink ODOMETRY](https://mavlink.io/en/messages/common.html#ODOMETRY).

Reuse installed WSL pymavlink 2.4.49 (LGPL package provenance retained in Task 4)
to decode CRC-checked common-v2 bytes, and pyulog 1.2.4 (BSD-3-Clause) to read
ULog. The installed pyulog source, metadata and license are copied and hashed.
Its upstream was non-archived, with last observed push 2026-08-06, when queried
for this stage. PX4/pymavlink maintenance observations remain those of the
earlier pinned research. Installed parser provenance is distinguished from
upstream maintenance metadata.

This path adds no package or daemon and operates in memory on a bounded study's
retained records. A custom ULog decoder is rejected in favor of PX4's maintained
parser; a live listener would cross the pending network gate. The small local
adapter maps decoded records to the fixed receiver layout. Its cost is linear
in stream size; it is not a performance benchmark or capacity optimization.

Review found that pyulog's recovery behavior is unsuitable as the sole evidence
completeness gate: its data loop can silently stop on a short tail or an internal
`struct.error`, and repeated subscription IDs overwrite buffered rows. The
installed source (`_read_file_data`, `_MessageInfo`, `MessageLogging`) and the
[official ULog format](https://docs.px4.io/main/en/dev_log/ulog_file_format)
support a narrow validation wrapper, while retaining pyulog for actual decoding.
The format reference was saved with SHA-256
`7a102404013c75a37e217494e0275e849aa8ce82e7283890d5f9ba49e7a2d077`.
It is a retrieved current reference, not a pinned PX4 historical document.

## Exact comparison contract

The journal is a list of `{id, packet_hex}` objects. Only unsigned MAVLink 2
ODOMETRY with the frozen prospective sender 254/191 is accepted. The legacy
offline encoder's 1/191 identity does not silently qualify the future sender;
its packets must fail this profile. No source identity is read from a caller's
separate claims instead of the packet header.

| Wire field | Pinned receiver field |
| --- | --- |
| frame 20, child frame 12 | pose frame 2, velocity frame 3 |
| x/y/z, q, vx/vy/vz | position, exact signed Hamilton quaternion, velocity |
| pose covariance indices 0/6/11 | position variance |
| pose covariance indices 15/18/20 | body orientation variance |
| velocity covariance indices 0/6/11 | velocity variance |
| unavailable angular rates | three unavailable angular-velocity values |
| reset counter, quality | exact copied counter, quality 1 |

The comparator checks decoded float32 values exactly and never normalizes or
sign-flips quaternions to hide a mismatch. It only verifies covariance entries
that PX4 actually consumes; upstream PSD and health qualification remain in
the authoritative health/composer layer. It does not recreate or replace it.

The clock input is a separate JSON object with schema
`px4-receiver-parity-clock-v1` and signed integer `px4_minus_remote_us`.
Expected receiver sample time is wire time plus that offset, with a fixed
1 microsecond tolerance. Arrival minus sample must exceed that tolerance and
be no more than 100,000 microseconds. Near-equal timestamps are inconclusive
about arrival fallback and fail this component conservatively. The tool cannot
prove that the supplied clock offset was prospectively frozen; the future
study's runtime binding must prove it. No data-driven offset fitting occurs.
Pinned TimesyncStatus has no explicit convergence flag, so its presence alone
cannot authorize publication or qualify convergence.

All records are compared in existing order. Empty, missing, extra, duplicate
and regressed samples fail. Reported ULog corruption, recorded dropouts, missing
columns, unequal column lengths or ambiguous visual-odometry instances are refused.
There is no sorting, interpolation, subsampling or failed-window removal.
Hashes of packet journal, clock declaration and ULog are retained. Output uses
exclusive creation and refuses overwrite. These are ordinary file-change
checks, not a guarantee against hostile concurrent rewrites.

The raw-file wrapper accepts a narrow unappended ULog v1 profile. It requires
complete record boundaries, initial flags, unique subscription IDs/topics and
format definitions, subscriptions before data, and equal raw/decoded receiver
record counts. Appended files, unknown record types, unsubscription and dropouts
are refused, even where a general recovery parser might salvage data. Framing
and decoding use the same in-memory bytes. These checks are not a checksum or a
claim that arbitrary bit corruption can be detected.

The pinned parser normally terminates by reading a three-byte message header at
the exact EOF. A small `BytesIO` wrapper retains that final read even after the
parser closes its input. The audit refuses termination without this observation,
including an internal `struct.error` swallowed after a fully framed message.
This is deliberately tied to pyulog 1.2.4, not a claim about arbitrary parser
versions. Escaping parser exceptions are normalized at the decoder boundary;
input evidence and the refusal remain in the CLI output.

## Verification so far

Evidence directory: `results/openvins-receiver-parity-dev-1701`.

- Core tests first failed 41 times because the module did not yet exist, then
  passed. Those are missing-module failures, not behavioral bug reproductions.
- CLI had been drafted before its tests; it was removed from the production
  import path for the five missing-module checks, then restored and tested.
  This is recorded as a workflow deviation, not claimed as a behavioral RED.
- Combined targeted suite: 46 passed. Changed-file Ruff passed.
- Real WSL pymavlink 2.4.49: three synthetic packet roundtrips and three
  refusals (CRC, trailing bytes, duplicate packet bytes), with socket creation
  forbidden. Their matched receiver rows are analytic synthetic fixtures.
- pyulog 1.2.4 read the real retained Task 3 ULog with SHA-256
  `bb84abacfecb838c1a21cec6c0dc9116a2a4a2216882ff519fb7799e87299c2c`.
  The CLI refused this no-ODOMETRY negative control, as expected. This is not a
  positive receiver integration run.

Initial full regression passed 2,025 tests with 3 skips and 2 existing warnings.
It predated the review corrections and does not qualify them. The first review
found two Important completeness gaps and one Important refusal-artifact gap.
Actual WSL codec tests reproduced three false passes (short header, short
payload, repeated subscription) and two exceptions without a report. The first
correction passed the same six-case harness, including its normal control, and
69 focused tests. The 23 new unit tests initially failed for missing boundary
APIs; the five actual codec counterexamples are the behavioral RED evidence.

Follow-up review found an additional path within the same completeness issue:
an empty logging message after matching receiver rows is structurally complete
but can cause pyulog to stop silently. Seven actual parser variants reproduced
false passes before the EOF observation check and were refused afterward; a
focused unit assertion also went RED to GREEN. The 13-case actual-codec harness
(one normal, twelve faults) and 70 targeted tests then passed. The retained
7,484,079-byte physical ULog passed raw framing across 68,668 records and was
correctly refused as receiver evidence because it has zero visual-odometry
samples. Source/input hashes were identical before and after that read-only
check. No new physical capture was made.

A further review found that recursive format expansion could throw an escaping
`RecursionError`. One actual-codec case and one unit assertion reproduced the
missing report; the decoder boundary now normalizes this exception. Final
targeted validation passed 71 tests. The final actual WSL harness passed all
14 cases (one normal synthetic log and thirteen refusal cases). Independent
read-only review confirmed every reported issue resolved, with no remaining
blocking finding. Final full regression passed **2,050 tests, with 3 skips and
2 existing warnings, in 348.71 seconds**. Changed-file Ruff and both working-tree
and staged `git diff --check` passed. Earlier full runs are retained as
intermediate validation, not evidence for this last correction. The warnings
are the existing duplicate-ZIP-member fixture and unmatched malecns neuron
groups; no repository-wide Ruff success is claimed.

The native harness can be rerun only into a new output directory, for example
`python3 results/openvins-receiver-parity-dev-1701/check_ulog_boundary.py NEW_LABEL`
from the WSL environment with the pinned dependencies. It consumes the sealed
analytic fixtures and packet/clock files and refuses an existing directory.
Synthetic ULog rows are not claimed to originate from PX4. Final actual-codec
results are under `ulog-boundary-recursion-green`; all earlier RED/GREEN outputs
are preserved separately.

Earlier development RED/GREEN runs were made against the changing uncommitted
worktree; they do not have an independently frozen project-source snapshot for
each intermediate revision. Their input files, outcomes and harness are retained,
but they are not physical-study provenance. The final archive binds the submitted
implementation, tests and reports; the final review source hashes must still
match. The retained-real-log check separately records its own before/after input
and source hashes. No absent historical source freeze is reconstructed.

## Stage classification

- Verified: synthetic wire-to-field mapping, source identities, framing and
  corruption counterexamples, and a retained real ULog negative control.
- Implemented: offline comparison CLI and strict raw/decoded accounting.
- Not tested: actual PX4 receiver delivery, TIMESYNC convergence, live parameter
  rollback, receiver-only injection, and EKF2 fusion.
- Failed and retained: source lookup 404, initial missing-module tests, actual
  parser false passes/escaped exceptions, and intermediate review failures.

No learning weights, flight controller state, sensor stream, or physical
workload was changed. This stage cannot demonstrate complete fruit-fly learning,
task allocation, baseline superiority, five-/twenty-aircraft readiness, or real
flight. The next integration gate remains Task 5 in the existing plan.
