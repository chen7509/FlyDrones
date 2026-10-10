# Explicit one-attempt live-wire entry

Date: 2026-10-09. Base 36b4f67; implementation 438f9f8.

## Scope and result

The existing executor now exposes an explicit `execute_live_wire` entry and
`--live-wire-study` CLI route. This is implementation and offline verification,
not execution of the study. The earlier user restriction to preparation/design
remains in force. No network, estimator, simulator, ODOMETRY, EKF2 mutation,
arming or training is authorized by this change.

The caller must select the exact validated manifest with its lowercase SHA256.
This digest is not proof of human consent. The entry writes an exclusive
`activation-request.json`, marked as request rather than dispatch, with the
manifest/executor identities, request time and fusion false. The prepared
manifest is unchanged and still does not grant live authority.

Existing inputs and output aliases refuse. Competing resources are checked
before the request and again in the inherited executor. That executor rechecks
all frozen identities and the complete declaration, then owns the existing
exclusive dispatch/completion/log behavior. Its execution body is unchanged.
After a request is retained, even a pre-dispatch failure consumes that study's
attempt; an operator must preserve it rather than relabel it as a completed run
or overwrite it. File checks are ordinary drift detection, not atomic snapshots,
hostile-race protection or cryptographic consent.

The old health route remains health-only. Wire selection requires its own CLI
option and digest and rejects the health development-gate option. Ordinary
capture/supervisor limits remain 300 seconds. No new supervisor or protocol was
introduced. Research and dependency decisions reuse the fixed upstream/API
sources in the live-wire design; this wrapper introduces no new dependency.

## Verification ledger

- New API-absence RED: 27 assertions failed in 30.00 s before implementation.
  These are missing-entry tests, not 27 independently reproduced production bugs.
- GREEN: 46 new and inherited executor tests passed in 107.86 s. New tests forbid
  process creation and sockets, and pass explicit fake runners. Synthetic
  dispatch/completion records exercise the production envelope; they are not
  physical evidence, regardless of fields populated by the inherited executor.
- Changed-file Ruff and diff checks passed.
- Independent read-only source review found no Critical, Important or Minor
  findings. Fresh reviewer creation hit the tool's thread limit, so an existing
  independent completed reviewer was resumed with a bounded new request. It ran
  no tests or processes and did not review actual physical/network behavior.
- Full repository regression: first invocation failed during collection with
  73 import errors and 22 skips in 6.72 s. With PYTHONPATH unset, the installed
  package resolved to the old curriculum-training worktree. An import check
  confirmed that process-local PYTHONPATH selecting this worktree's src fixes
  the source selection. The corrected full run completed with **3,977 passed,
  33 skipped and 3 existing warnings in 674.62 s**, exit 0, on production 438f9f8.
  Both logs are kept. Skips are not validated; warnings are the deliberate
  duplicate ZIP member, sparse checkpoint invariant scan and existing missing
  neuron-group warning. No production code changed after this run.
- Installed preparation v5 completed once with exit 0: 610 declared files,
  82 static sources, 8 XML documents, 46 reference edges and 40 read-only native
  resource queries. Five mutations (seed, command, auditor hash, clock scope,
  missing lazy source) were refused. All 568 tracked Python source hashes were
  unchanged. WSL selected-resource scan after preparation returned empty.
- v5 independent package review matched 91 accessible file hashes/sizes,
  including the 82 sources, generator, manifest and executor. It checked exact
  command/workload/profile identity and absence of every execution output. This
  was Windows-accessible byte verification, not a second Linux installed-identity
  or runtime-closure audit. v4 remains preserved and freezes the older executor.

The v5 manifest is
`results/live-wire-study-dev-1701/study-v5/study-manifest.json`, SHA256
`419950ff5e5c3a59422acfd473f04cfb171c35a5660969b071a61bcf0f0e9395`.
Its executor SHA256 is
`057991923309a0524799080d15de17c23e9633c2ade8f468864fc4be8b32da58`.
`results/live-wire-explicit-entry-dev-1701/proposed-action.json` contains the
exact prospective command and an explicit false activation flag; it was not
executed. Saved preparation flags remain false for physical/network/estimator
execution, live qualification, fusion and complete runtime coverage. An SDK
resource-query subprocess may create its default log directory; this is not a
physics run. Existing WSL localhost-proxy warning bytes are retained in the log.

## Remaining action

After final preparation and regression, the proposed separately authorized action
is one unarmed development seed27601 study: 25 s, 1 ms physics, 250 Hz raw IMU,
10 Hz 160x120 RGB-D, original vehicle, gravity, support/force and safety limits.
It uses the existing native OpenVINS worker. Outgoing messages are limited to
TIMESYNC and the reviewed message-interval query/apply/restore operation.
No ODOMETRY, EKF2 parameter changes, arming, setpoints, training or swarm expansion
are part of that action. Success would establish communication evidence only;
receiver injection, fusion and closed-loop flight remain separate gates.

Full fruit-fly learning/division, full-model latency, fair upstream comparison,
multi-aircraft capacity, hardware and flight remain incomplete. This stage does
not resolve the memory requirement or the five-camera 0.873 versus 0.95 RTF gap.

## Sealed evidence

`evidence/live-wire-explicit-entry-dev-1701.zip` contains 149 members, 1,058,824
bytes, SHA256 `024de8ba20fc1cfee296b366e7c4d892ef62376a51230697b85f2d4a408b1899`.
Every member's bytes/hash and ZIP CRC were checked. The source/report copies
are post-verification copies at 1c12e96; this seal paragraph was added afterward.
The archive retains v4 and v5, their generators/committed source inventories,
tests including the first collection failure, reviews, prospective action and
final offline verification. No historical failure or older evidence was replaced.
Final host process filtering and WSL selected-resource scan found no matching
test/PX4/Gazebo/OpenVINS job. This is an observation, not a global process proof.
Commits and the sealed artifact are local; this report makes no new remote
publication claim.
