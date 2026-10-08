# Live wire study preparation status

## Current outcome

The next unarmed communication study has a committed specification and offline
implementation plan. The prospective validator and several raw-chain consistency
checks are implemented and tested. The full study auditor and actual prepared
dispatch package remain unfinished. No new physical, network or estimator run
occurred in this preparation work. Fusion remains false.

The latest increment adds original resource-query/XML graph reconstruction and
official CameraInfo protobuf decoding to `audit_live_wire_study(study_path)`.
It invokes available raw auditors and returns staged refusals, consumed-file
hashes and explicit unverified gates. Task 2 still lacks a complete positive
study fixture and remaining failure-path coverage. Per-call watchdog/readiness observations are
not present in the historical logs and remain explicitly unproven.
Task 3's installed executor/package and whole-package review remain pending.

The previous safety/anchor increment passed 391 targeted/directly affected tests (77.95s), including
101 safety/anchor/file-entry tests. Changed-file Ruff and diff checks pass. The
initial anchor API assertion and three missing-entry-route assertions failed
before implementation; all outputs are retained. This is not a full-repository
test pass or the final whole-package review.

The coverage increment passes 336 targeted/directly affected regression tests
(108.52s), changed-file Ruff and diff checks. This is not a new full-repository
pass. Missing APIs first failed assertions; seven entry-route counterexamples
showed that absent physical/fast/health files were previously ignored. A later
behavioral RED exposed an unchecked final reference-attempt wall time and is now
GREEN. Intermediate wrong `maximum_rows` keyword and health profile lookup under
`inputs` instead of `profiles` caused retained test failures before correction.

Fresh reference/trace/clock coverage and fast IMU-call joins have synthetic
positive/negative tests. Actual retained development seed27201 health replays all
250 camera records exactly with quality 0. Its legacy 1ms-origin fast grid is
correctly refused under the current absolute-20ms producer profile; this is a
version mismatch, not a new VIO failure. All consumed files and producer hashes
were unchanged across that read-only check. The producer source before the final
reference wall-time guard was reconstructed afterward and matched its recorded
hash `51a3d12063ee0d9d9930bf1251bd723262f40beae84141a5fcf9ee438d6f72a5`;
it is not described as a pre-run source copy. No physical clock join against
that old run, new estimator execution, network transmission or fusion is claimed.

A byte-identical actual startup-only result (SHA256
`bea9ffb42b6a412ab757f1ad1d036e8db17c4871d63e17fec2441dcaeb6d930c`) says
`capture_completed` but has `estimator_run=false`. Under a synthetic valid study
manifest it is explicitly rejected without an audit-file write or process/socket.
Cross-file negatives change PID, executable inode, birth ticks, namespace/group,
lifecycle mirrors, clock/configuration/deadline, dispatch command/seed/manifest
and native command/configuration. File-routing positives use named leaf doubles;
they are not a complete positive raw chain or a live result.

Initial missing-API REDs were followed by 153 related Windows tests in 29.69s
and eight pinned-codec WSL unittest methods in 28.791s. Behavioral REDs exposed
the wrong ULog manifest shape, an unstructured malformed-file-index error,
binary-only native-command checking, numeric startup-flag acceptance and an
overly broad file-verification flag. All were corrected; the final 51 targeted
tests passed in 20.53s. Counts overlap and are not a new full-repository total.
Changed Ruff passed after one test-import ordering fix; diff-check passed.

An installed Python symlink was read/hash-checked without execution; an independent
same-content retarget refused. This is ordinary drift detection, not atomic or
hostile-ABA protection. No dispatcher was activated, existing physical input was
not modified, no full-repository pass is claimed, and publication remains local.

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

Study-entry increment producer `9622718` is preserved in
`evidence/live-wire-study-entry-offline-progress-dev-1701.zip`: 37 members,
98,652 bytes, SHA256
`03a4f8ba59944cf128251c6bdd948728044c43ac82767a53ca91639dc31e5ce8`.
Member lengths/hashes, uniqueness and CRC passed. It includes raw startup-negative
fixture provenance, synthetic cross-file/routing tests and retained RED/GREEN
outputs. The WSL declared-reader probe preceded the final metadata-scope fix;
its earlier auditor bytes were reconstructed afterward and matched exactly to
the source hash recorded by the probe. This is explicitly a verified post-run
reconstruction, not a pre-run source copy. The archived report precedes this seal
paragraph. No whole-study qualification, live run or remote upload is claimed.

Coverage increment producer `9145ea9` is preserved in
`evidence/live-wire-coverage-offline-progress-dev-1701.zip`: 42 members,
124,342 bytes, SHA256
`1071768d86ccb248cf25a9e7deb03b95da9ad8cbdc21fc5d53fce1213dec27cd`.
All member bytes/hashes and ZIP CRC were verified. The archive includes the
intermediate failures, final 336-test regression, fixed-input identity records,
source provenance and explicit partial-completion boundaries. Existing physical
inputs are referenced by hash, not duplicated or changed. The archived report
precedes this seal paragraph; publication remains local.

## Offline safety and anchor increment

Implemented source interval, fixture motion, existing-gauge scoring and anchor
source/estimator attribution checks in the read-only study entry. The new anchor
tests contain unchanged selected records with documented original input hashes;
they are explicitly an incomplete fixture. File-entry positive routing still
uses named leaf doubles and cannot qualify a full raw chain.

The fixed safety audit consumes old development seed27201 without launching a
simulator or estimator. It checks 25,000 pre-steps, 6,251 IMU and 251 RGB/info
arrivals, 22,382 support force records and 1,600 lateral force records. Reusing
the existing gauge gives approximately 0.06599 m maximum position error,
0.02288 m/s velocity error and 0.9451 degree attitude error. Diagnostic screens,
public coverage and capture completeness pass; the scorer's estimator health,
post-origin/full-motion and trajectory qualification remain false because the
quality/covariance requirements are not promoted by this offline audit.

A separate anchor-only audit of the same retained capture joins all 226 internal
estimator records and 24 heartbeat observations. The selected heartbeat wall
age is 2.294545129 seconds and simulation age is 0.975 seconds, consistent with
the frozen simulation-time heartbeat gate. Its post-flush receipt is bounded,
not independently timestamped. No later readiness-call history is fabricated.

Both new fixed audits preserve exact producer source copies before checking and
verify consumed inputs again afterward. Subsequent formatting/integration changes
are tested separately; no historical physical run is reattributed to them.
The earlier legacy fast-grid mismatch remains a refusal of the current profile.
Task 2 still needs resource/CameraInfo joins, a complete positive raw chain and
remaining failure-path coverage. Task 3 preparation and whole-package review are
pending. Live/fusion flags remain false; all changes are local pending publication.

The retained anchor subset has an explicit Git byte-preservation attribute.
An index-byte assertion caught JSON newline normalization after the first
implementation commit. Attribute-only re-add did not refresh the cached blob;
the misleadingly named `anchor-index-green-v1.txt` retains that second failure.
An explicit reindex now preserves SHA256 `421c15f47dc7ff9e91891369df69ccbc08a8c1f5bc25ce894899dba93e0117d5`.
The narrow `cr-at-eol` whitespace attribute recognizes the retained CRLF bytes.
The index-byte check and 24 anchor tests pass; no estimator algorithm changed.

## Resource and camera increment

The new pure resource audit reuses production traversal with in-memory original
XML and recorded SDK replies. It validates query arguments/context/raw stdout
and stderr, deadlines, no omitted/extra queries, graph equality and declared file
identity. Production `build_graph` retains bounded reads and final evidence write;
the private shared traversal introduces no additional process or search path.
CameraInfo is decoded with Gazebo's installed generated protobuf class, including
raw timestamps, fixed geometry and rectification rather than accepting hashes alone.

A new read-only check of retained seed27201 succeeds for 251 camera protobufs,
8 XML documents, 46 graph edges and 40 query records. It tracks 338 consumed files,
including exact pre-audit producer copies and hash identities of loaded decoder
modules, and verifies them again afterward. No original data was changed, SDK
resolver executed, estimator replayed, or new physical run performed. Gazebo
messages package10.4.0 and Python protobuf runtime4.21.12 are recorded separately
from Debian's protobuf package version3.21.12; installed source/license snapshots
are retained. Installed version is not a claim of active upstream maintenance.

The first CameraInfo entry test run overlapped the integration edit and passed;
its filename `camera-entry-red-v1.txt` does not make it RED evidence. Removing
only that entry stage, waiting for the run to finish, then restoring it produced
three actual failing assertions in `camera-entry-red-v2.txt`. Resource entry has
five independently observed missing-file/route REDs. Unit missing-API REDs and
all intermediate outputs are retained. Tests and fixed audits remain distinct
from a full positive raw-chain integration or final whole-package review.

Safety/anchor increment is sealed in
`evidence/live-wire-safety-anchor-offline-progress-dev-1701.zip`: 62 members,
210,733 bytes, SHA256
`40bc23faff20761a8d57761754aaea44520bebf293e7b91fd2202bb7da2e25ae`.
CRC and every member were verified. Core implementation is `588c5fb`; final
fixture byte preservation is `53e64ea`. Exact pre-audit producers, both old-input
checks, test failures and successful regressions are included. The report inside
the archive precedes this seal paragraph. Local only; no runtime authorization.

Final resource/camera regression: 249 passed, 3 skipped in 102.49 seconds.
The three skips require Gazebo's official Python message package unavailable on
Windows; all three real-protobuf unittest methods passed in WSL (0.198 seconds).
Changed-file Ruff and diff checks pass. This covers the new auditor, study entry,
source/native joins and affected production graph/runtime/calibration helpers;
it is not a full-repository pass or the final independent review.

Resource/camera producer `972912f` is sealed in
`evidence/live-wire-resource-camera-offline-progress-dev-1701.zip`: 46 members,
173,725 bytes, SHA256
`a5b47471421804182a6bb6e7267c4507a76d1a4ccb0d6540ffc723436a8d9f40`.
CRC and all member bytes/hashes were verified. The archive includes exact fixed-
audit producer copies, installed proto/license sources, decoder module hashes,
original input identities and all relevant RED/GREEN outputs. Loaded decoder
binary bytes are referenced by hash rather than embedded. The archived report
precedes this seal paragraph. Publication remains local, not verified on PR65.

## Interval response and failure regression increment

Five behavioral counterexamples showed that the normal interval auditor accepted
altered intermediate ACK/readback fields and a missing per-response snapshot
while the original decoded responses and terminal success remained intact. The
auditor now preserves response order within each datagram and compares every
corresponding pending-state snapshot. All five counterexamples now refuse; ACK
and readback in either legitimate order still pass. No transport or flight policy
changed.

The initial RED log also contains one test-construction failure: reindexing a
corrupted index undid the intended restore-before-body mutation. That test now
moves the actual record before reindexing. Missing-record cases likewise reindex
their synthetic envelopes so rejection exercises transaction evidence rather
than only the independent global-index check.

Six additional failure cases use the actual observed-session, interval and
segmented-retention classes with synthetic socket/owner/clock fixtures. Source
loss followed by successful restoration is still a failed capture. Missing ACK
and short send remain unverified even when later readbacks match baseline. Armed
input, cleanup expiry and unknown baseline also refuse. Replacing only the final
state with success does not make any case pass normal audit. These are new GREEN
coverage cases, not claimed as six newly repaired production failures. They do
not provide live failure-cleanup qualification.

WSL pinned-codec, interval, listener and production restoration regression:
47 unittest methods passed in 41.343 seconds. The full positive study fixture,
prospective package, producer attestation and whole-package review remain open.
No simulator, estimator, UDP, ODOMETRY, EKF2, arming or training was started.
The Windows study validator, file entry and evidence-reader regression passed
107 tests in 77.67 seconds. Changed-file Ruff and diff checks pass; this is not a
full-repository test run. All publication in this increment is local.

Producer `fe1e9c7` is sealed in
`evidence/live-wire-interval-failure-offline-progress-dev-1701.zip`: 15 members,
60,610 bytes, SHA256
`6a23585da5d8e5ff37b4d64b0a9987390659455a7c8193d9b84da88544e17d1f`.
CRC and every member hash were checked. The package retains the initial RED
output (five production counterexamples and one test-construction issue), final
regressions, source copies and ledger. Synthetic journals use temporary test
directories; their generators and outcomes are preserved, not a new physical
capture. The archived report precedes this seal paragraph.

## Shared-clock fixture integration (partial)

The old protocol unit fixture's remote origin is 1 ms, while the prospective
study requires origins 0/0. A new explicitly synthetic fixture uses the latter
without rewriting old records. It runs the production observed-session, codec,
clock and segmented journal classes with fake datagram/daemon/owner interfaces.
Each timesync response uses the simulation epoch actually committed to the
fixture's shared clock. Its 500 startup pairs and 149 maintenance pairs span a
25-second synthetic timeline, including both legal non-counting boundaries.
The chosen simulation-to-wall schedule is test data, not a measured RTF.

Physical callback rows and source arrivals share that timeline. The generator
retains 25,000 clock/reference cycles, 50,000 pre/post rows, 6,251 IMU and 251
RGB/CameraInfo/depth events. CameraInfo uses actual installed protobuf encoding;
the existing CausalInput and packet encoder generate 6,501 sensor requests.
ACKs and stationary physical states are synthetic. All 250 camera states remain
uninitialized and derived health remains quality zero. No estimator process ran.

The test discards the generator's in-memory output and reads the files using
the production bounded reader before invoking eight real auditors, with no leaf
auditor doubles. Cross-clock corruptions are refused. This joins protocol,
interval, listener, physical coverage, source/native, camera, health and watchdog
checks; it does **not** complete the full normal study fixture. Initialized motion,
anchor/gauge, fast predictions, resource/runtime bindings, ULog and the actual
file-entry composition still need to be joined. All whole-study/live/fusion and
physical-execution qualification flags remain false.

The first fixture attempt failed during construction because the interval-mode
heartbeat consumer was omitted. It is retained as a fixture setup failure, not
a production regression or behavioral RED. After supplying that explicit fake
consumer, the joined tests and existing WSL protocol/interval/listener tests
passed 12 unittest methods in 45.201 seconds. Windows source-generator and
coverage/health/safety regressions passed 129 tests in 49.22 seconds. Installed
protobuf deprecation warnings are retained. No full-repository or live validation
is claimed, and no production algorithm changed in this increment.

The retained `joined-clock-source-v1` synthetic bundle was independently read
back and passed those same eight checks over 524 consumed files. Fifty-six
already-loaded repository source files were copied and hashed before generation
and checked afterward. Two generator dependencies loaded later
(`live_wire_source_fixture.py` and `test_live_wire_camera_info.py`) have only
post-load hashes in this run; that limitation is explicit and is not repaired
retroactively. The bundle is not a complete runtime freeze or physical evidence.

Source commit `3919de3` and the partial synthetic bundle are sealed in
`evidence/live-wire-joined-clock-source-offline-dev-1701.zip`: 597 members,
3,492,233 bytes, SHA256
`3bd1d01262e9934cd29f9a5f16bed0968668daecff7160d99077bfc56c7f37d4`.
CRC and all member hashes were verified. Raw synthetic clock, wire, callback,
image/protobuf, source and native-protocol records are included alongside source
snapshots, initial setup failure and regression results. The report inside the
archive precedes this seal paragraph. This remains local publication only.

## Initialized synthetic chain integration (partial)

The new opt-in fixture keeps the shared zero-origin clock and full input counts,
then introduces explicitly synthetic internal state at 1.2 s and public state at
1.3 s. It uses the actual packet encoder, health contract, estimator readiness,
motion-intent gate and anchored force policy. It does not run OpenVINS, PX4,
Gazebo, network transport or force APIs. The original uninitialized fixture
remains a separate case.

A synthetic native M acknowledgement is inserted after the first initialized
camera acknowledgement. All later packet sequences and hashes are regenerated
together. The readiness journal attributes a camera update to the later IMU
delivery that actually releases that image; its original image arrival remains
recorded separately. The first combined attempt incorrectly grouped the update
by image arrival and was refused by the real readiness clock check. That fixture
construction failure, including an unclosed test output warning, is retained;
the generator now attributes by dispatch window and closes the journal on error.
This is a fixture repair, not a newly discovered production estimator defect.

The saved anchor is 1.405 s, selected at the next pre-step after the 1.2 s camera
update is released at 1.204 s. The production policies generate the expected
1,600 lateral command steps. They never call a physical force API. The recorded
stationary reference is independent of those force commands, so agreement with
the known synthetic camera trajectory is only a composition/coordinate test,
not mechanical consistency or VIO precision evidence. Identity world-from-FLU
requires the corresponding 180-degree x rotation for this FRD state; replacing
it with identity correctly fails the gauge's diagnostic screen.

The 1,249 aligned synthetic fast targets contain 60 unavailable and 1,189
successful numeric records. Initialization cannot be borrowed from a camera
processed after the triggering IMU. There are 238 internal and 237 public camera
states; all 250 derived health rows retain quality zero. No covariance, trajectory,
whole-study, physical, live, or fusion qualification is granted. The frozen
first-internal gauge origin remains 1.2 s; it is not picked after seeing errors.

The test discards generated memory and rereads the v2 synthetic bundle from
disk before invoking 12 real leaf auditors. Policies and result inputs used by
the gauge are saved files as well. Corruptions of IMU trigger time, processing
interval, initialization, quality, native intent identity, anchor source receipt
and camera receipt attribution are rejected. The v2 reader rejects older fixture
schemas explicitly; sealed v1 data is unchanged. Runtime/resource/ULog/full file
entry integration and the prospective preparation package remain incomplete.

Validation: Windows workload/physical-fast/health/safety/anchor/file-entry
regressions passed 200 tests in 117.95 s. WSL pinned-codec joined/protocol/interval/
listener regression passed 21 unittest methods in 64.521 s; after saving gauge
inputs as original fixture files, both joined suites passed 12 methods in
35.142 s. Changed-file Ruff and diff checks passed. The initial missing-key/API
failures are fixture-development evidence, not production behavioral REDs.
Installed protobuf deprecation warnings remain. No full-repository test run,
whole-package review, actual runtime activation or remote publication is claimed.
