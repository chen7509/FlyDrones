# Live wire study preparation status

## Current outcome

The next unarmed communication study has a committed specification and offline
implementation plan. The prospective validator and several raw-chain consistency
checks are implemented and tested. The full study auditor and actual prepared
dispatch package remain unfinished. No new physical, network or estimator run
occurred in this preparation work. Fusion remains false.

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

Task 1 of `docs/superpowers/plans/2026-10-08-live-wire-study.md` is implemented:
`live_wire_study.py` validates the exact prospective schema and production command,
then separately verifies real file identities, the full declared dependency
snapshot and all four frozen estimator configuration files. Pure validation
performs no file/process/network I/O. The file adapter is preparation-only,
rejects existing/colliding outputs and never starts the runtime. Producer commit
is declared, not independently attested by these APIs. All live/fusion results
remain false even after preparation succeeds.

The 41 new tests include strict types/profiles/load/clock/session, missing or
changed inputs, omitted calibration/freeze declarations, forbidden runtime effects
and output collisions. Initial RED was a missing-API assertion, not an existing
behavior regression. A separate deterministic boundary test reproduced acceptance
of an output created during the final dependency read; the final output recheck
fixed it. Four other boundary tests already passed and are not claimed as fixes.
This remains ordinary drift observation, not an atomic output reservation or a
guarantee against changes after return.

The related six-file regression suite passed **172 tests, 2 skipped** in 20.50 s;
changed-file Ruff passed. Earlier run `regression-green-v2.txt` actually contains
**1 failed, 171 passed, 2 skipped**: an existing preflight test rejected a change
in `stat()` values while reading its execution declaration. Its isolated rerun
passed, then the identical six-file suite passed. Both outcomes are retained in
`results/live-wire-study-contract-dev-1701`; the transient cause is unproven,
and no capture/worker code was changed or repair of that issue claimed. The two
skips are the existing Windows symlink permission cases. No full repository or
physical test result is claimed for this stage.

Tasks 2–3 remain open: build the raw-chain auditor, then freeze and independently
review a complete package before considering any live activation. The validator
tests use explicitly synthetic files and do not qualify installed resources.

Task 2 has begun with a segmented evidence reader and producer-field map in
`LIVE_WIRE_RAW_EVIDENCE_MAP.md`. Its 19 new cases and related storage/contract
tests passed (72 total), including 8192+8 records and refusal of numeric overflow.
The next implementation adds raw packet/status/clock consistency joins, replaying
the existing cold/maintenance filter classes and fixed pymavlink codec. The
positive synthetic fixture includes 500 accepted bootstrap and two accepted
maintenance samples, both non-counting boundary replays, and 25000 synthetic
clock observations. Sixteen independent corruption subcases refuse. A separate
behavioral RED exposed two correlated maintenance pairs with only one accepted;
requiring at least two accepted samples fixes that false pass.

Verification for this increment: **21 WSL unittest methods** (including three new
methods with the 16 corruption subcases) and **124 Windows pytest cases** passed;
changed-file Ruff passed. These suites overlap previous checks and are not added
into one unique-test total. An initial WSL command incorrectly included a pytest
module on an interpreter without pytest; its import failure remains in
`protocol-regression-v2.txt`. The test was routed to existing Windows pytest,
without installing dependencies. The synthetic fixture's remote origin is 1 ms,
not the prospective 0/0 profile, and its clock disk-shaped attempts are explicitly
reconstructed test data. No installed/live qualification follows from this test.

At that protocol-only increment, owner/descriptor/listener transport joins, raw
interval restoration, workload/shutdown and the study entry point were unfinished.
All live, fusion, transport-ownership, interval and workload qualification flags
from the protocol helper remain false; only supplied protocol consistency is
checked. No physical/UDP/native-estimator run was started.

### Subsequent interval and listener increment

The two raw joins above now have separate offline helpers. Interval auditing
decodes the actual command/ACK/readback bytes with the existing pinned codec,
checks pending deadlines and common outgoing sequence, and requires baseline
restoration before maintenance. It also accepts the production no-mutation path
when the original interval already equals 10000 us, but still requires final
readback. Twelve altered or missing-evidence cases refuse. This is the normal
transaction path, not a completed audit of failure-time restoration.

Listener auditing joins each of four recorded connection/peer observations,
allowed command bytes and send returns, daemon byte envelopes and EOF, decoded
snapshots/stream chunks, coordinator records and their redundant journal copies.
It reuses ReplyEnvelope, TimesyncListenerDecoder and parse_snapshot. Sixteen
negative cases include wrong peer/process/path, missing copies or EOF, altered
raw status, command bytes/count, terminal/clock and cancellation failures. A
behavioral RED exposed bool-as-int command indices; strict integer validation
now refuses them. The initial missing-API RED and first implementation's incorrect
cancellation schema assumption are retained separately. Cancellation events have
no own timestamp: their wrapper retains the last checked cleanup clock, not a
new observation of socket-close time.

The combined WSL suite passed **21 unittest methods** in 31.565 s, including the
interval/listener helpers, protocol regression and existing observed-interval
tests. Negative subcases are inside methods, not additional independent method
counts. The separate Windows reader/storage/prospective regression passed 72
cases in 8.55 s; these overlap earlier checks and are not summed into a new unique
total. Changed-file Ruff passed. No live sockets, simulator, PX4 or estimator
were started. Tests use explicitly injected I/O and synthetic clock records.
The existing listener-transport, owned-bootstrap and listener-decoder regression
suite also passed 356 cases in 3.19 s; it exercises the reused producer parsers.

These helpers report record consistency only. The producer does not journal every
owner recheck or a kernel descriptor ID for each listener operation; matching
SO_PEERCRED/owner observations cannot prove a fresh launch or exclude descriptor
transfer. Maintenance socket-close evidence does not prove daemon process exit.
The actual runtime/descriptor/launch binding, complete workload and cleanup,
startup-only refusal and whole-study adapter remain open, followed by Task 3's
installed preparation and whole-package review. No overall Task 2 pass is claimed.

The broader goal remains open: actual VIO-to-EKF2 fusion, complete fruit-fly
learning/division in that closed loop, fair upstream comparison, 5/20-aircraft
qualification and external hardware/flight evidence. The five-camera 0.873 RTF
result still fails its 0.95 threshold.

## Additional offline runtime/workload verification (Task 2 still open)

Three new read-only modules cover retained runtime mapping, unarmed ULog and
source/native work. Normal cleanup now reuses the existing supervisor auditor
with explicit completed/exit0/300s semantics; the original fault profile remains
the default. No process manager, alternate estimator, decoder or live launcher
was added. Whole-study qualification and Task 3 are still unfinished.

The runtime helper checks declared/observed roles, executable/owner identity,
raw `/proc` maps against file identities, generated snapshots and pre/post drift.
The earlier fixed development capture gave five self stages, four owned stages
and 1366 mapped-file observations. This positive predates the final two guard
fixes; final guards were verified synthetically, without re-running that capture.
Two assertion REDs exposed owned-map masquerading and an exceeded observation
budget, then passed after correction. The related regression recorded 111 passed.
Normal cleanup checked seven original disk/in-memory journal events and an empty
original group after reap, with no supervisor group signals; escaped descendants
remain explicitly unqualified.

ULog verification requires full framing, pinned pyulog1.2.4 decoding and equality
of raw topic counts and decoded samples. The retained development ULog has
68849 raw messages and 51 observations each of vehicle status and actuator armed,
all standby/unarmed. Recorded bounds are 0.215–24.725s; that is not continuous
coverage of the full 25s. Four WSL unittest methods (with binary/manifest/decoder
fault subcases) and 66 related Windows tests passed. No package was installed.

The new source/native audit joins 6251 IMU + 251 each RGB/info/depth + 24 heartbeat
source rows through 14056 fan-out records to 6501 sensor acknowledgements and one
motion-intent acknowledgement. It retains all 250 processed camera states (222
public) and the final `later_imu_missing` record. It re-encodes request bytes from
the retained source/pixels and compares their exact hashes, rather than trusting
the stored success flags. It does not recompute an accuracy pass or attest a
native process merely from those records.

The first workload test invocation failed collection because PYTHONPATH did not
select `src`; the corrected invocation produced a missing-API assertion RED.
The first fixed-input harness then incorrectly expected `native-session.json`
to contain session_id; it actually contains PID, and the capture producer derives
`online-native-<pid>`. That harness failure is preserved. Fixed attempt v2 refused
the auditor's incorrect sample<=callback-clock assumption. The retained record
has 107 IMU callbacks whose shared clock is 1ms behind the sensor stamp. Five
behavioral REDs covered this distinction, missing explicit null terminal fields
and unexpected IMU ack fields; all passed after correction. These are auditor
fixes, not changes to simulation timing or safety gates.

Fixed workload attempt v3 passed with input and producer hashes unchanged before
and after the read-only audit. The new 31 cases and directly reused causal-input,
fan-out and online-shadow regressions passed (129 total, 37.81s). Changed-file
Ruff and diff checks passed. Counts from these overlapping suites are not summed
into a new full-repository count. No full-repository test or independent whole-
package review is claimed for this incomplete increment.

All fixed checks reference the old development seed27201 capture; none launch
PX4, Gazebo, OpenVINS, UDP or training. Unarmed log observations, mapping records
and causal packet matches are distinct from actual live communication and EKF2
fusion. Full manifest/dispatch/descriptor joins, health/physics/fast coverage,
payload file provenance, startup-only refusal and the whole-study entry point
remain required. Historical failures and remote-publication limitations remain.

## Design evidence seal

`evidence/live-wire-study-design-dev-1701.zip` contains 30 members, 92,235 bytes,
SHA256 `db8d03f6b73585f14fa6711c0c3c3624412e6f27593fba9e60b8bc07faa4f0bc`.
All member lengths/hashes, uniqueness and CRC passed. It includes the reviewed
and clarified plan/spec, research references and retained sources, read-only
review record and selected current production source snapshots. Producer/report
commit is `8b18f0b`; the archived report precedes this seal paragraph. The earlier
`design-check-v1.json` binds the pre-clarification plan at `cc7db35`, while this
archive manifest binds the final version. Neither is a runtime pre/post freeze.

## Offline implementation progress evidence

Producer commit `5d88e62` follows Task 1 commit `a042dd6`.
`evidence/live-wire-study-offline-progress-dev-1701.zip` contains 21 members,
37,388 bytes, SHA256
`eaae9323953f644a5e8b182071f229fdb6178c21a637ad12dac0aa5b248a782e`.
All member hashes/lengths and ZIP CRC were verified. The archive retains both
REDs, the transient regression failure and its reruns, source/tests, the reviewed
spec/plan and reports before this seal paragraph. It is an interim progress
archive, not completion of Tasks 2–3 or the whole-package independent review.
These commits/artifacts are local; no successful remote upload is claimed.

Protocol increment producer `65dc05c` is preserved in
`evidence/live-wire-protocol-offline-progress-dev-1701.zip`: 23 members,
59,839 bytes, SHA256
`668792846b73427e5d66242c0595bac3fb6b0eaca05eb36045eedcde278ab3dd`.
Member hashes/lengths and CRC passed. It retains relevant producer/filter/fixture
sources and successful/failed test outputs. It contains synthetic test evidence,
not a physical capture or a completed study audit; independent review remains
pending. Archived report precedes this paragraph. Publication remains local.

Interval/listener increment producer `fab26b6` is preserved in
`evidence/live-wire-interval-listener-offline-progress-dev-1701.zip`: 37 members,
102,592 bytes, SHA256
`c2813a83a5a16265a62d11582cb2d3d6f298b1c75137c7e7b377328e94ac1ae3`.
Member hashes/lengths, uniqueness and CRC passed. It retains source/fixtures,
the failed implementation/schema run, missing-API and boolean-index REDs, final
GREEN/regressions and source-field inspection. The archive contains synthetic
and offline evidence only; this report inside it precedes this seal paragraph.
Task 2, Task 3 and whole-package review are unfinished. Publication is local;
this seal makes no remote-head or actual runtime qualification claim.

Runtime/workload increment producer `29ceeca` is preserved in
`evidence/live-wire-runtime-workload-offline-progress-dev-1701.zip`: 55 members,
201,875 bytes, SHA256
`4d474c645db983db05a3c66e14e2b0ea842ed2e0270ad26cc473ccffaa7b6ef8`.
All member hashes/lengths, uniqueness and CRC passed. Fixed audits retain input
hash references to the unchanged old development capture instead of duplicating
its raw images and ULog. The earlier runtime-positive helper's hash is recorded,
but its exact earlier source was not retained; the archive explicitly records
that limitation and contains the final guarded source and synthetic regressions.
Workload v1/v2/v3 sources and the failed harness/refusal outputs are preserved.
This is local offline progress, not Task 2 completion, a full-suite result,
whole-package review, remote publication or live-study qualification.
