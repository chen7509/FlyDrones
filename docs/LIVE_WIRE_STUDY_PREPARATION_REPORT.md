# Live wire study preparation status

## Current outcome

The next unarmed communication study has a committed specification and offline
implementation plan. The prospective validator, raw-chain auditor and actual
prepared dispatch package are **not implemented by this documentation stage**.
No new physical, network or estimator run occurred. Fusion remains false.

The immediately preceding installed startup preflight is now sealed in
`evidence/installed-wire-startup-dev-1701.zip`, SHA256
`b9c25ae47336904033c9d557b04e66bf9b57dae70e6eb837ce4c85af8b0092de`:
93 members, all member lengths/hashes and CRC verified. This closes file/startup
evidence retention, not actual packet delivery or clock convergence.

## Design decision

Reuse the existing production capture lifecycle, with its one reader, native
estimator, full sensor/physics workload and fail-closed gates. Do not introduce
ROS, a replacement clock filter, reduced-load simulator or second receiver.

The proposed companion epoch 0/0 explicitly means simulation time in nanoseconds.
It is a chosen epoch, not a measurement of PX4 HRT or host wall time. Only actual
committed PostUpdate samples could substantiate its runtime use. The later auditor
must correlate each outgoing response with the actual owned PX4 status chain;
local filter success and socket return counts alone cannot qualify delivery.

The 10000 us candidate interval has nominal first-to-500th spacing of 4.99 s in
simulation time. Startup remains bounded by 8 s wall time, including actual setup;
rate scaling, scheduling and rejected exchanges can prevent success. No passing
rate is predicted from this calculation and no timeout is increased.

## Evidence and limitations

- Fixed upstream source and previous maintenance observations are referenced by
  SHA256 in `results/live-wire-study-design-dev-1701/research-references.json`.
  Existing PX4 clock/stream/filter sources, current official TIMESYNC documentation
  and PX4 simulation documentation informed the design. No new estimator or
  paper-derived algorithm is claimed.
- `design-check-v1.json` verifies referenced file hashes, both new design document
  identities and the installed startup archive. This is a document/evidence
  check, not a unit test or simulation result.
- Prior regression results remain prior evidence. No production code changed and
  no regression suite was rerun for this documentation-only stage.
- Independent read-only review of `3fd409b..cc7db35` found no Critical/Important
  issue and two Minor plan ambiguities. Both were clarified in prose: required
  exact boundary replays remain non-counting valid records, and filesystem-aware
  validators belong only in the file adapter. Guards forbid subprocess/network
  effects, not harmless standard-library imports. No production fix or RED/GREEN
  test claim is made for these documentation edits; no second review is claimed.
- Actual live activation is a separate gate; this stage does not authorize
  ODOMETRY, EKF2 changes, arming, training or multi-aircraft expansion.
- PR65 body was updated and read back with the local startup result. Verified
  remote head remains `e4312ed`, while later local commits and archives are still
  pending upload. The prior large-object timeout is not repaired by a body update.
  No repeated large upload was attempted in this stage.

## Next work

Execute Task 1 of `docs/superpowers/plans/2026-10-08-live-wire-study.md`: a pure
prospective validator and read-only file adapter, with negative tests for
startup-only substitution, omitted native load, clock scope and declaration drift.
Then build the raw-chain auditor and freeze a complete reviewable package before
considering any live activation. All three implementation tasks are still open.

The broader goal remains open: actual VIO-to-EKF2 fusion, complete fruit-fly
learning/division in that closed loop, fair upstream comparison, 5/20-aircraft
qualification and external hardware/flight evidence. The five-camera 0.873 RTF
result still fails its 0.95 threshold.
