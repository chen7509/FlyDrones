# Installed startup preflight for the wire configuration

## Outcome

`results/installed-wire-startup-dev-1701/study-v1` completed one actual installed
WSL parent/worker `--startup-preflight` invocation at production commit
`600ada0aab1cf12e84d7a9078d3f6295353dc388`. The existing startup auditor reported
no failures. The actual worker result is `capture_completed`,
`startup_preflight_completed=true`, and `estimator_run=false`.

This closes the **installed files-only startup** gap left by the injected entry
tests. It does not qualify live UDP, TIMESYNC convergence, PX4 delivery, VIO,
fusion, physics, hardware, flight or multi-aircraft capacity.

## Prospective study and dependencies

The one-off preparation and executor are retained as experiment artifacts, not a
new production launcher. They reuse the existing startup preflight design,
`declared_command`, strict execution and runtime-binding validators, file snapshot
code, resource resolver, original-group supervisor and startup auditor. No new
runtime dependency was installed. A source/resource manifest existed before
dispatch; the executor checked its file identities, complete baseline, current
head argument, command and explicit startup flag, then refused any existing output.

The input declaration comes only from development seed 27601 in the sealed
`evidence/openvins-ekf2-file-shadow-dev-1701.zip`, SHA256
`d834874a46f8eedb6c2a0518036aa08dbe26a92ceeeacc8c1a8a9730bb77bdae`.
Archive hash/CRC and the three consumed manifest/binding/execution members were
checked before use. No held-out trajectory was read for adjustment. The original
source files and previous failed studies remain untouched.

The historical baseline contained 555 entries. Preparation accepted exactly three
content changes, all to current committed Python: `capture_contract.py`,
`capture_disarmed_sensors.py`, and `disarmed_sensor_provenance.py`. The before/after
hashes are in `source-drift.json`. This is an explicit new current-code declaration,
not a claim that historical production source remained unchanged. Non-code byte
changes would have refused preparation. Nineteen current-import entries (including
the preparation script) and the wire configuration were added, producing 575
declared entries. There were no unexpected source changes.

The same scene, models, estimator configuration, reference module, gravity-related
inputs, profiles, limits and search environment remain declared. Inherited
25 s / 1 ms / 250 Hz / 10 Hz 160×120 values describe the future physical workload;
**no simulation time was advanced in this study**. Seed 27601 was only declared,
not applied to a random generator. Wire clock origins 0/0 were only parsed; they
are not validated or authorized for a live clock session.

Selected unchanged binary SHA256 values:

| Input | SHA256 |
| --- | --- |
| PX4 development binary | `e8af7cbcac255ec3c79bb5fa278459fd0b130b4b189de9269e3689cb9789f4cb` |
| Aligned native OpenVINS probe | `97a1af94a9e5b29fa00a42ed1eba4e39a29ee732a524506fb95491ae236f24de` |
| Native diagnostic reference | `303b575e29d44bf50850ad03e3d3b865207a225e366418ec5733ed5292cc18ce` |
| Read-only resource resolver | `ef45d239e92fe23db8e63799503c1fe065547ca81311cffb92c9c06a200c7393` |

Only the resource resolver was executed. It performs the previously researched
installed SDK file/URI queries without creating a Server or loading a physics
study. Reused provenance: CPython 3.12.3 (PSF), Gazebo Sim 8.15 / Common 5.9 /
SDFormat 14.9 (Apache-2.0), and the fixed resolver source/dependencies already
recorded in the source binding. The prior source investigations used Sim
`446a443`, Common `442a7ab4f213e435c3ca93947004216f26ec728d`, and SDFormat
`97d9b0cea4a84003022d27d8d97b1def10b778ef`; installed-patch equivalence is not
asserted. Those are reused observations, not a new upstream-maintenance survey.
No new algorithm or paper-based capability was introduced. Reusing this bounded
path avoids running physics solely to validate startup resources.

## Raw result verification

- 40 native resource queries completed without recorded errors; 46 resource-graph
  edges were verified under the declared local-file profile.
- Runtime pre/post lists contain **594 identical file records**. The additional
  entries are actual generated files and bootstrap self mappings. The direct
  checker also reread every referenced file and verified its size and SHA256.
- Worker environment and trajectory-policy evidence match their declarations.
  The exact wire config identity appears in the execution declaration and required
  runtime paths. Neither declaration drift nor missing inputs were bypassed.
- Actual observed phases are only `postgraph` and `bootstrap`. PX4 and OpenVINS
  owned-phase lists are empty; full mapping coverage and runtime closure remain false.
- Worker exit 0; seven on-disk supervisor events exactly match the cleanup record.
  Owner PID/process-group/session 488 was reaped; the final original group was
  absent and had no executing member. No supervisor group signal or SIGKILL was
  recorded. Escaped descendants are outside this supervisor's claimed scope.
- Dispatch-to-completion wall time was **24.211330143 s**, a startup-preflight
  duration, not 25 s of simulation, inference latency, or RTF.
- Resource scans before and after were empty; no sensor capture, estimator run,
  ULog or physical-study artifacts were produced.

The existing auditor and the separate `verify_evidence.py` direct checks both
passed. The latter also checks raw declaration/dispatch hashes, actual file bytes,
unchanged workload fields, wire identity and query/executable identities. No
production code changed and no regression suite was rerun in this experiment;
the earlier 140 tests remain prior evidence, not a new test count.

Independent read-only review found no Critical or Important issue for this narrow
result. Its reporting caveat is preserved: `launch.json` contains planned
`execution_contract.estimator_run=true`, the future 25-second workload and a
TIMESYNC command policy, while `result.json` records the actual preflight-only
execution with `estimator_run=false`. Preparation's qualification false is a
prospective state; the later audit's startup qualification true is the outcome.

There is no syscall trace (`strace` was unavailable and was not installed).
The frozen code path and artifacts establish that the capture receiver/physical
branches were not activated; artifact absence alone is not proof of zero network
syscalls in every imported/native library.

## Status and remaining work

| State | Evidence or limitation |
| --- | --- |
| Verified | Actual installed startup-only parent/worker, declared current inputs, local resource graph, stable files, bounded original-group cleanup. |
| Implemented and offline tested | Single-reader wire lifecycle, cold bootstrap/maintenance, heartbeat delivery, interval restoration and failure refusal. |
| Not verified by this study | Live clock mapping, actual PX4 TIMESYNC delivery/convergence, concurrent camera/IMU/native traffic, ODOMETRY reception, EKF2 fusion or flight. |
| Failed/pending elsewhere | Prior physical failures remain sealed; five-camera 0.873 RTF is still below 0.95; the earlier large archive and later local commits are still pending remote upload. |

Next dependency: independently freeze the **unarmed live wire-only validation**
conditions and actual clock-origin evidence, including startup/maintenance and
failure/restore acceptance. This result does not itself activate that study.
ODOMETRY, EKF2 parameter changes/injection, arming, training and 5/20-aircraft
expansion remain outside this startup result. Full fruit-fly learning/division
and fair upstream-baseline comparisons remain downstream goals.

## Evidence seal

`evidence/installed-wire-startup-dev-1701.zip` contains 93 members (728,872 bytes),
SHA256 `b9c25ae47336904033c9d557b04e66bf9b57dae70e6eb837ce4c85af8b0092de`.
CRC, unique member names, exact manifest membership, lengths and every member
SHA256 were checked after creation. The original source archive is referenced by
hash and consumed-member identities rather than duplicated. This archive includes
all 79 study/harness/log files present before sealing, including the sibling
supervisor journal, plus selected production source copies and the prior design.
Source copies were matched to the pre-run committed-source SHA256 map; their
copying happened after the run. The archived report is the pre-seal version from
`4b38e9f`, while the actual study producer remains `600ada0`. No study was rerun.
This seal is local; remote archive publication remains a separate pending check.
