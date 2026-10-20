# Wire heartbeat and actual journaled fanout integration

The missing integration coverage noted in `OPENVINS_WIRE_HEARTBEAT_REPORT.md`
is now supplied by test-only commit `bd04203`. No production behavior changed.
The actual pinned codec, capture dispatch function, CaptureWriter, independent
heartbeat journal, base/estimator fanout and ShadowInput are composed in process.
The socket, ownership, wall/simulation clock and listener remain test doubles.
The native substitute raises if invoked; no native estimator runs.

## Results and scope

Nine new cases passed on their first run: this is added GREEN coverage, not a
discovered/fixed production bug or a RED-to-GREEN repair. After import cleanup,
the new nine plus the existing wire-heartbeat suite pass in WSL: **30 OK**.
Windows heartbeat-lane and estimator-readiness regression: **67 passed**.
Changed-file Ruff and diff whitespace checks pass. No fresh full-repository pass
is claimed. Logs are under `results/openvins-wire-fanout-dev-1701`.

Both fanout profiles route through actual `dispatch_heartbeat`. Two ordered
heartbeats preserve source hashes, sequence and original receive-return times
through observation, queue and reconciliation. Reconciliation of the older
heartbeat does not replace the newer observation. Stale synthetic native acks are
cleared by ShadowInput; heartbeat processing creates no native calls, causal
sensor input or estimator readiness. Sensor/native readiness is never preset.

Queue saturation and closed-writer cases retain the independent observation
already made before queue refusal. The journal-error case injects an exception
at `_heartbeat_emit`; it is not a real failing filesystem flush. Tampered queued
identity, preexisting shadow failure, armed heartbeat and pending-reconciliation
expiry refuse subsequent operations. Tests compose a pipeline health callback
into the fake descriptor guard; that guard is not a real socket identity proof.

The writer uses its actual worker thread but starts processing during `finish()`.
This verifies ordered adapter composition, not concurrent live capture operation,
durability/fsync, online latency, source throughput or capture-mode registration.

Independent read-only review of `bd04203` found no Critical, Important or Minor
findings and confirmed the previous Minor is covered. The reviewer inspected
assertions and whitespace, but did not rerun suites; the runs above are the
implementer's verification. The review's boundaries match those stated here.

Three cases were separately declared before export: normal estimator fanout,
queue saturation, and reconciliation tamper. Their actual local component JSONL
journals, refusal/partial-delivery state and wire evidence are retained. Selected
source hashes were unchanged before/after export. These are synthetic transport
experiments, not new physical/estimator replays. The normal and failure assertions
all pass; failures within the modeled pipeline remain visible in their evidence.

## Status

- **Verified in process:** journal/queue/reconciliation, original identities and
  times, heartbeat/native-ack separation, failure retention and refusal paths.
- **Implemented previously:** optional heartbeat callback in the observed wire
  session; the legacy capture receiver remains unchanged.
- **Not implemented/verified live:** sole-reader capture lifecycle, continuous
  reception after bootstrap, actual callback/descriptor binding, stream interval
  apply/ACK/readback/restore and real PX4 convergence.
- **Unchanged failures/limits:** five-camera 0.873 RTF < 0.95; earlier physical
  failures retained; no hardware calibration, HITL or flight qualification.

No network socket, PX4/Gazebo/OpenVINS run, training, ODOMETRY, EKF2 injection,
arming or multi-aircraft run was started. Fusion remains false. This prerequisite
supports the sensor/safety part of the full fruit-fly objective; it does not prove
learning, division of work, fair-baseline superiority or swarm readiness.

Evidence: `evidence/openvins-wire-fanout-dev-1701.zip` with external member/SHA
manifest `evidence/openvins-wire-fanout-seal.json`. Historical archives are intact.
Next work is specified in `superpowers/specs/2026-10-08-capture-wire-lifecycle-design.md`.
